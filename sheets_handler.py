"""
Google Sheets Handler
Manages all Google Sheets operations including reading API keys, 
writing orders, and tracking processed orders
"""
import time
import logging
import gspread
import os
from datetime import datetime
from typing import List, Dict, Optional, Set, Any
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from functools import wraps
import io
import requests
from google.auth.transport.requests import Request as GoogleRequest
from config import (
    GOOGLE_SHEETS_ID,
    GOOGLE_SERVICE_ACCOUNT_JSON,
    SHEET_WB,
    SHEET_ACCESS,
    SHEET_TASKS,
    SHEET_PROCESSED_ORDERS,
    SHEET_PRODUCTS,
    SHEET_TASKS_FOR_PDF,
)

logger = logging.getLogger(__name__)

# Rate limiting: Google Sheets allows 60 read requests per minute per user
# We'll limit to ~30 requests per minute to be safe (more conservative)
SHEETS_MIN_DELAY = 2.0  # Minimum delay between requests (seconds)
last_request_time = 0


def rate_limit(func):
    """Decorator to rate limit Google Sheets API calls"""
    @wraps(func)
    def wrapper(*args, **kwargs):
        global last_request_time
        current_time = time.time()
        time_since_last = current_time - last_request_time
        
        if time_since_last < SHEETS_MIN_DELAY:
            sleep_time = SHEETS_MIN_DELAY - time_since_last
            time.sleep(sleep_time)
        
        last_request_time = time.time()
        
        # Retry logic for 429 errors
        max_retries = 3
        for attempt in range(max_retries):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                # Check if it's a rate limit error
                is_rate_limit = False
                error_str = str(e)
                
                # Check error message
                if "429" in error_str or "RESOURCE_EXHAUSTED" in error_str or "RATE_LIMIT_EXCEEDED" in error_str:
                    is_rate_limit = True
                
                # Check if error is a dict with rate limit code
                if hasattr(e, 'response') and isinstance(e.response, dict):
                    if e.response.get('code') == 429 or e.response.get('status') == 'RESOURCE_EXHAUSTED':
                        is_rate_limit = True
                
                if is_rate_limit:
                    if attempt < max_retries - 1:
                        wait_time = (attempt + 1) * 5  # Exponential backoff
                        logger.warning(
                            f"Rate limit hit for {func.__name__}. "
                            f"Waiting {wait_time}s before retry "
                            f"{attempt + 1}/{max_retries}"
                        )
                        time.sleep(wait_time)
                        last_request_time = time.time()
                        continue
                    else:
                        logger.error(
                            f"Rate limit exceeded for {func.__name__} "
                            f"after {max_retries} retries"
                        )
                        raise
                else:
                    # Not a rate limit error, re-raise immediately
                    raise
        return None
    return wrapper


class SheetsHandler:
    """Handler for Google Sheets operations"""

    def __init__(self):
        """Initialize Google Sheets client"""
        try:
            scope = [
                "https://spreadsheets.google.com/feeds",
                "https://www.googleapis.com/auth/drive",
            ]
            creds = Credentials.from_service_account_file(
                GOOGLE_SERVICE_ACCOUNT_JSON, scopes=scope
            )
            self.client = gspread.authorize(creds)
            self.spreadsheet = self.client.open_by_key(GOOGLE_SHEETS_ID)
            # Initialize Google Drive API for PDF export with increased timeout
            # Create HTTP object with longer timeout
            import google_auth_httplib2
            import httplib2
            http = httplib2.Http(timeout=300)  # 5 minutes timeout
            http = google_auth_httplib2.AuthorizedHttp(creds, http=http)
            # Use only http (not credentials) since http is already authorized
            self.drive_service = build('drive', 'v3', http=http)
            self.creds = creds  # Store for direct URL access
            logger.info(f"Successfully connected to Google Sheet: {GOOGLE_SHEETS_ID}")
            
            # Ensure required sheets exist
            self._ensure_sheets_exist()
        except Exception as e:
            logger.error(f"Failed to initialize Google Sheets client: {e}")
            raise

    def _ensure_sheets_exist(self):
        """Ensure all required sheets exist, create if missing"""
        existing_sheets = [sheet.title for sheet in self.spreadsheet.worksheets()]
        
        # Create Tasks sheet if it doesn't exist
        if SHEET_TASKS not in existing_sheets:
            self.spreadsheet.add_worksheet(
                title=SHEET_TASKS,
                rows=1000,
                cols=10,
            )
            task_sheet = self.spreadsheet.worksheet(SHEET_TASKS)
            # Set headers in row 1 (A1-F1)
            task_sheet.update("A1:F1", [[
                "№ задания",
                "Фото",
                "Наименование",
                "Артикул продавца",
                "Стикер",
                "Статус",
            ]], value_input_option='USER_ENTERED')
            logger.info(f"Created sheet: {SHEET_TASKS}")
        
        # Create ProcessedOrders sheet if it doesn't exist
        if SHEET_PROCESSED_ORDERS not in existing_sheets:
            self.spreadsheet.add_worksheet(
                title=SHEET_PROCESSED_ORDERS,
                rows=1000,
                cols=10,
            )
            processed_sheet = self.spreadsheet.worksheet(SHEET_PROCESSED_ORDERS)
            # Set headers
            processed_sheet.append_row([
                "Order ID",
                "Warehouse",
                "API Key",
                "Processed Date",
            ])
            logger.info(f"Created sheet: {SHEET_PROCESSED_ORDERS}")
        
        # Create Products sheet if it doesn't exist
        if SHEET_PRODUCTS not in existing_sheets:
            self.spreadsheet.add_worksheet(
                title=SHEET_PRODUCTS,
                rows=1000,
                cols=10,
            )
            products_sheet = self.spreadsheet.worksheet(SHEET_PRODUCTS)
            # Set headers in row 1 (A1-C1)
            products_sheet.update("A1:C1", [[
                "Артикул продавца",
                "Фото",
                "Наименование",
            ]], value_input_option='USER_ENTERED')
            logger.info(f"Created sheet: {SHEET_PRODUCTS}")
        
        # Create TasksForPDF sheet if it doesn't exist
        if SHEET_TASKS_FOR_PDF not in existing_sheets:
            self.spreadsheet.add_worksheet(
                title=SHEET_TASKS_FOR_PDF,
                rows=1000,
                cols=10,
            )
            pdf_sheet = self.spreadsheet.worksheet(SHEET_TASKS_FOR_PDF)
            
            # Set formula in A1 for automatic image insertion
            # Formula: ={"Изображение";ARRAYFORMULA(IF(C2:C="";;IMAGE(C2:C;4;350;350)))}
            formula = '={"Изображение";ARRAYFORMULA(IF(C2:C="";;IMAGE(C2:C;4;350;350)))}'
            pdf_sheet.update("A1", [[formula]], value_input_option='USER_ENTERED')
            
            # Set headers in row 1 for columns B-F
            pdf_sheet.update("B1:F1", [[
                "№ задания",
                "Фото URL",
                "Наименование",
                "Артикул продавца",
                "Стикер",
            ]], value_input_option='USER_ENTERED')
            
            logger.info(f"Created sheet: {SHEET_TASKS_FOR_PDF} with image formula")

    @rate_limit
    def get_warehouse_api_keys(self) -> List[Dict[str, str]]:
        """
        Read warehouse and API key information from WB sheet
        
        Returns:
            List of dictionaries with keys: city, warehouse, api_key
        """
        try:
            sheet = self.spreadsheet.worksheet(SHEET_WB)
            records = sheet.get_all_records()
            
            result = []
            for record in records:
                city_raw = record.get("Город", "")
                city = str(city_raw).strip() if city_raw else ""
                
                warehouse_raw = record.get("Название склада", "")
                warehouse = str(warehouse_raw).strip() if warehouse_raw else ""
                
                api_key_raw = record.get("API_KEY", "")
                api_key = str(api_key_raw).strip() if api_key_raw else ""
                
                if warehouse and api_key:
                    result.append({
                        "city": city,
                        "warehouse": warehouse,
                        "api_key": api_key,
                    })
            
            logger.info(f"Loaded {len(result)} warehouse API keys from sheet")
            return result
        except Exception as e:
            logger.error(f"Error reading warehouse API keys: {e}")
            return []

    @rate_limit
    def get_warehouse_access(self) -> Dict[str, List[int]]:
        """
        Read warehouse access permissions from Access sheet
        
        Returns:
            Dictionary mapping warehouse name to list of chat_ids
        """
        try:
            sheet = self.spreadsheet.worksheet(SHEET_ACCESS)
            records = sheet.get_all_records()
            
            result = {}
            for record in records:
                warehouse_raw = record.get("Название склада", "")
                warehouse = str(warehouse_raw).strip() if warehouse_raw else ""
                
                chat_id_raw = record.get("Chat_id", "")
                # Handle both string and integer values from Google Sheets
                if isinstance(chat_id_raw, (int, float)):
                    chat_id = int(chat_id_raw)
                else:
                    chat_id_str = str(chat_id_raw).strip() if chat_id_raw else ""
                    if not chat_id_str:
                        continue
                    try:
                        chat_id = int(chat_id_str)
                    except (ValueError, TypeError):
                        logger.warning(
                            f"Invalid chat_id '{chat_id_raw}' for warehouse "
                            f"'{warehouse}'"
                        )
                        continue
                
                if warehouse and chat_id:
                    if warehouse not in result:
                        result[warehouse] = []
                    # Avoid adding duplicate chat_ids to the same warehouse
                    if chat_id not in result[warehouse]:
                        result[warehouse].append(chat_id)
            
            logger.info(f"Loaded access for {len(result)} warehouses")
            return result
        except Exception as e:
            logger.error(f"Error reading warehouse access: {e}")
            return {}

    def get_user_access(self) -> Dict[int, Dict[str, List[str]]]:
        """
        Get user access organized by chat_id
        
        Returns:
            Dictionary mapping chat_id to dict with cities and warehouses
            Structure: {chat_id: {"cities": [...], "warehouses": [...]}}
        """
        warehouse_access = self.get_warehouse_access()
        warehouse_api_keys = self.get_warehouse_api_keys()
        
        # Create warehouse -> city mapping
        warehouse_to_city = {}
        for item in warehouse_api_keys:
            warehouse_to_city[item["warehouse"]] = item["city"]
        
        # Organize by chat_id (support multiple warehouses per user)
        result = {}
        for warehouse, chat_ids in warehouse_access.items():
            city = warehouse_to_city.get(warehouse, "")
            for chat_id in chat_ids:
                if chat_id not in result:
                    result[chat_id] = {
                        "cities": set(),
                        "warehouses": set(),  # Use set to avoid duplicates
                    }
                result[chat_id]["warehouses"].add(warehouse)
                if city:
                    result[chat_id]["cities"].add(city)
        
        # Convert sets to sorted lists
        for chat_id in result:
            result[chat_id]["cities"] = sorted(list(result[chat_id]["cities"]))
            result[chat_id]["warehouses"] = sorted(list(result[chat_id]["warehouses"]))
        
        return result

    @rate_limit
    def get_processed_order_ids(self) -> Set[str]:
        """
        Get set of all processed order IDs from ProcessedOrders sheet
        
        Returns:
            Set of order ID strings
        """
        try:
            sheet = self.spreadsheet.worksheet(SHEET_PROCESSED_ORDERS)
            
            # Check if sheet has data (more than header row)
            if sheet.row_count <= 1:
                logger.debug("ProcessedOrders sheet is empty")
                return set()
            
            records = sheet.get_all_records()
            
            processed_ids = set()
            for record in records:
                order_id_raw = record.get("Order ID", "")
                order_id = str(order_id_raw).strip() if order_id_raw else ""
                if order_id:
                    processed_ids.add(order_id)
            
            logger.info(f"Loaded {len(processed_ids)} processed order IDs")
            return processed_ids
        except Exception as e:
            logger.error(f"Error reading processed orders: {e}")
            return set()

    @rate_limit
    def mark_order_processed(self, order_id: int, warehouse: str, api_key: str):
        """
        Mark an order as processed in ProcessedOrders sheet
        
        Args:
            order_id: Order ID
            warehouse: Warehouse name
            api_key: API key used (first 20 chars for privacy)
        """
        try:
            sheet = self.spreadsheet.worksheet(SHEET_PROCESSED_ORDERS)
            
            # Truncate API key for privacy
            api_key_short = api_key[:20] + "..." if len(api_key) > 20 else api_key
            
            sheet.append_row([
                str(order_id),
                warehouse,
                api_key_short,
                datetime.now().isoformat(),
            ])
            logger.debug(f"Marked order {order_id} as processed")
        except Exception as e:
            logger.error(f"Error marking order as processed: {e}")

    @rate_limit
    def order_exists_in_tasks(self, order_id: int) -> bool:
        """
        Check if an order already exists in Tasks sheet
        
        Args:
            order_id: Order ID to check
            
        Returns:
            True if order exists, False otherwise
        """
        try:
            sheet = self.spreadsheet.worksheet(SHEET_TASKS)
            # Check if order ID exists in column A
            try:
                cell = sheet.find(str(order_id), in_column=1)
                return cell is not None
            except gspread.exceptions.CellNotFound:
                return False
        except Exception as e:
            logger.error(f"Error checking if order exists in Tasks: {e}")
            # If error, assume it doesn't exist to avoid skipping valid orders
            return False

    @rate_limit
    def add_order_to_tasks(
        self,
        order_id: int,
        photo_url: Optional[str],
        product_name: str,
        article: str,
        sticker: str,
    ):
        """
        Add a new order to Tasks sheet (only if it doesn't already exist)
        
        Args:
            order_id: Order ID
            photo_url: Product photo URL
            product_name: Product name/title
            article: Seller article/vendor code
            sticker: Sticker string (partA + partB)
        """
        try:
            # Check if order already exists to prevent duplicates
            if self.order_exists_in_tasks(order_id):
                logger.warning(f"Order {order_id} already exists in Tasks sheet, skipping")
                return
            
            sheet = self.spreadsheet.worksheet(SHEET_TASKS)
            
            # Ensure headers exist in row 1 (A1-F1)
            header_row = sheet.row_values(1)
            if not header_row or len(header_row) < 6:
                # Write headers in row 1
                sheet.update("A1:F1", [[
                    "№ задания",
                    "Фото",
                    "Наименование",
                    "Артикул продавца",
                    "Стикер",
                    "Статус",
                ]], value_input_option='USER_ENTERED')
            
            # Find next empty row by checking column A (starting from row 2)
            values = sheet.col_values(1)  # Get all values in column A
            # If only header exists, next_row is 2, otherwise it's len(values) + 1
            if len(values) <= 1:
                next_row = 2
            else:
                next_row = len(values) + 1
            
            # Write data in columns A-F starting from row 2 (Status defaults to "new")
            range_name = f"A{next_row}:F{next_row}"
            sheet.update(range_name, [[
                str(order_id),
                photo_url or "",
                product_name or "",
                article or "",
                sticker or "",
                "new",  # Default status
            ]], value_input_option='USER_ENTERED')
            logger.info(f"Added order {order_id} to Tasks sheet (row {next_row})")
        except Exception as e:
            logger.error(f"Error adding order to Tasks sheet: {e}")
            raise

    @rate_limit
    def add_orders_to_tasks_batch(
        self,
        orders: List[Dict[str, Any]],
    ):
        """
        Add multiple orders to Tasks sheet using batch update (much faster!)
        
        Args:
            orders: List of order dictionaries, each with:
                - order_id: int
                - photo_url: Optional[str]
                - product_name: str
                - article: str
                - sticker: str
        """
        try:
            if not orders:
                logger.info("No orders to add to Tasks sheet")
                return
            
            sheet = self.spreadsheet.worksheet(SHEET_TASKS)
            
            # Ensure headers exist in row 1 (A1-F1)
            header_row = sheet.row_values(1)
            if not header_row or len(header_row) < 6:
                # Write headers in row 1
                sheet.update("A1:F1", [[
                    "№ задания",
                    "Фото",
                    "Наименование",
                    "Артикул продавца",
                    "Стикер",
                    "Статус",
                ]], value_input_option='USER_ENTERED')
            
            # Get existing order IDs to avoid duplicates
            existing_order_ids = set()
            try:
                existing_values = sheet.col_values(1)  # Column A has order IDs
                # Skip header (row 1), get all order IDs
                for value in existing_values[1:]:
                    try:
                        existing_order_ids.add(int(value))
                    except (ValueError, TypeError):
                        continue
            except Exception as e:
                logger.warning(f"Error reading existing order IDs: {e}")
            
            # Filter out orders that already exist
            new_orders = []
            for order in orders:
                order_id = order.get('order_id')
                if order_id and int(order_id) not in existing_order_ids:
                    new_orders.append(order)
            
            if not new_orders:
                logger.info(f"All {len(orders)} orders already exist in Tasks sheet, skipping")
                return
            
            # Find starting row for batch insert
            values = sheet.col_values(1)
            start_row = len(values) + 1 if len(values) > 1 else 2
            
            # Prepare batch data (columns A-F)
            rows_to_write = []
            for order in new_orders:
                rows_to_write.append([
                    str(order.get('order_id', '')),
                    str(order.get('photo_url', '')),
                    str(order.get('product_name', '')),
                    str(order.get('article', '')),
                    str(order.get('sticker', '')),
                    'new',  # Default status
                ])
            
            # Write all rows in one batch update
            if rows_to_write:
                end_row = start_row + len(rows_to_write) - 1
                range_name = f"A{start_row}:F{end_row}"
                sheet.update(range_name, rows_to_write, value_input_option='USER_ENTERED')
                logger.info(f"Added {len(rows_to_write)} orders to Tasks sheet in batch (rows {start_row}-{end_row})")
        
        except Exception as e:
            logger.error(f"Error adding orders to Tasks sheet in batch: {e}")
            raise

    @rate_limit
    def update_order_status(self, order_id: str, status: str):
        """
        Update order status in Tasks sheet
        
        Args:
            order_id: Order ID (as string)
            status: New status (e.g., "new", "completed")
        """
        try:
            sheet = self.spreadsheet.worksheet(SHEET_TASKS)
            
            # Find the row with this order ID (check column A)
            try:
                cell = sheet.find(str(order_id), in_column=1)
                row = cell.row
                
                # Update status (column F, index 6)
                sheet.update_cell(row, 6, status)
                
                logger.info(f"Updated order {order_id} status to: {status}")
                return True
            except gspread.exceptions.CellNotFound:
                logger.warning(f"Order {order_id} not found in Tasks sheet for status update")
                return False
        except Exception as e:
            logger.error(f"Error updating order status: {e}")
            return False

    @rate_limit
    def get_tasks_from_sheet(
        self, 
        warehouse: Optional[str] = None, 
        limit: int = 50,
        status_filter: Optional[str] = None
    ) -> List[Dict]:
        """
        Get tasks/orders from Tasks sheet, optionally filtered by warehouse and status
        
        Args:
            warehouse: Optional warehouse name to filter by
            limit: Maximum number of tasks to return (most recent first)
            status_filter: Optional status filter (e.g., "new", "completed", None for all)
            
        Returns:
            List of task dictionaries with keys: order_id, photo_url, product_name, 
            article, sticker, status
        """
        try:
            sheet = self.spreadsheet.worksheet(SHEET_TASKS)
            records = sheet.get_all_records()
            
            # Filter by warehouse if provided (we need to match via ProcessedOrders)
            warehouse_order_ids = set()
            if warehouse:
                # Get order IDs for this warehouse from ProcessedOrders
                try:
                    processed_sheet = self.spreadsheet.worksheet(SHEET_PROCESSED_ORDERS)
                    processed_records = processed_sheet.get_all_records()
                    
                    for proc_record in processed_records:
                        proc_warehouse_raw = proc_record.get("Warehouse", "")
                        proc_warehouse = str(proc_warehouse_raw).strip() if proc_warehouse_raw else ""
                        if proc_warehouse == warehouse:
                            order_id_raw = proc_record.get("Order ID", "")
                            order_id = str(order_id_raw).strip() if order_id_raw else ""
                            if order_id:
                                warehouse_order_ids.add(order_id)
                except Exception as e:
                    logger.warning(f"Error getting warehouse order IDs: {e}")
            
            # Filter tasks
            tasks = []
            for record in records:
                order_id_raw = record.get("№ задания", "")
                order_id = str(order_id_raw).strip() if order_id_raw else ""
                
                # Skip empty rows
                if not order_id:
                    continue
                
                # Filter by warehouse if specified
                if warehouse and order_id not in warehouse_order_ids:
                    continue
                
                # Get status (default to "new" if not set)
                status_raw = record.get("Статус", "")
                status = str(status_raw).strip().lower() if status_raw else "new"
                
                # Filter by status if specified
                if status_filter and status != status_filter.lower():
                    continue
                
                tasks.append({
                    "order_id": order_id,
                    "photo_url": str(record.get("Фото", "")).strip(),
                    "product_name": str(record.get("Наименование", "")).strip(),
                    "article": str(record.get("Артикул продавца", "")).strip(),
                    "sticker": str(record.get("Стикер", "")).strip(),
                    "status": status,
                })
            
            # Sort by order_id (descending, most recent first) and limit
            tasks = sorted(
                tasks,
                key=lambda x: int(x.get("order_id", "0")) if x.get("order_id", "").isdigit() else 0,
                reverse=True
            )[:limit]
            
            return tasks
        except Exception as e:
            logger.error(f"Error getting tasks from sheet: {e}")
            return []
    
    @rate_limit
    def get_task_by_order_id(self, order_id: str) -> Optional[Dict]:
        """
        Get a single task by order ID
        
        Args:
            order_id: Order ID to search for
            
        Returns:
            Task dictionary or None if not found
        """
        try:
            sheet = self.spreadsheet.worksheet(SHEET_TASKS)
            records = sheet.get_all_records()
            
            order_id_str = str(order_id).strip()
            
            for record in records:
                record_order_id = str(record.get("№ задания", "")).strip()
                if record_order_id == order_id_str:
                    status_raw = record.get("Статус", "")
                    status = str(status_raw).strip().lower() if status_raw else "new"
                    
                    return {
                        "order_id": record_order_id,
                        "photo_url": str(record.get("Фото", "")).strip(),
                        "product_name": str(record.get("Наименование", "")).strip(),
                        "article": str(record.get("Артикул продавца", "")).strip(),
                        "sticker": str(record.get("Стикер", "")).strip(),
                        "status": status,
                    }
            
            return None
        except Exception as e:
            logger.error(f"Error getting task by order ID {order_id}: {e}")
            return None

    @rate_limit
    def get_product_from_sheet(self, vendor_code: str) -> Optional[Dict[str, str]]:
        """
        Get product info (photo URL and title) from Products sheet by vendorCode
        
        Args:
            vendor_code: Vendor code (Артикул продавца)
            
        Returns:
            Dictionary with 'photo_url' and 'title' or None if not found
        """
        try:
            sheet = self.spreadsheet.worksheet(SHEET_PRODUCTS)
            records = sheet.get_all_records()
            
            vendor_code_lower = str(vendor_code).strip().lower()
            
            for record in records:
                record_vendor_code = str(record.get("Артикул продавца", "")).strip().lower()
                if record_vendor_code == vendor_code_lower:
                    photo_url = str(record.get("Фото", "")).strip()
                    title = str(record.get("Наименование", "")).strip()
                    return {
                        "photo_url": photo_url if photo_url else None,
                        "title": title if title else None,
                    }
            
            return None
        except Exception as e:
            logger.error(f"Error getting product from sheet: {e}")
            return None
    
    @rate_limit
    def get_tasks_for_pdf(self, supply_id: Optional[str] = None) -> List[Dict]:
        """
        Get tasks from TasksForPDF sheet
        
        Args:
            supply_id: Optional supply ID to filter tasks
            
        Returns:
            List of task dictionaries with keys:
            - order_id (№ задания)
            - photo_url (Фото URL)
            - product_name (Наименование)
            - article (Артикул продавца)
            - sticker (Стикер)
        """
        try:
            # Check if sheet exists, if not use Tasks sheet
            try:
                sheet = self.spreadsheet.worksheet(SHEET_TASKS_FOR_PDF)
            except gspread.exceptions.WorksheetNotFound:
                logger.warning(f"Sheet {SHEET_TASKS_FOR_PDF} not found, using {SHEET_TASKS} instead")
                sheet = self.spreadsheet.worksheet(SHEET_TASKS)
            
            records = sheet.get_all_records()
            
            tasks = []
            for record in records:
                order_id = str(record.get("№ задания", "")).strip()
                if not order_id:
                    continue
                
                tasks.append({
                    "order_id": order_id,
                    "photo_url": str(record.get("Фото URL", record.get("Фото", ""))).strip(),
                    "product_name": str(record.get("Наименование", "")).strip(),
                    "article": str(record.get("Артикул продавца", "")).strip(),
                    "sticker": str(record.get("Стикер", "")).strip(),
                })
            
            return tasks
        except Exception as e:
            logger.error(f"Error getting tasks for PDF: {e}")
            return []
    
    @rate_limit
    def write_tasks_to_pdf_sheet(self, tasks: List[Dict]):
        """
        Write tasks to TasksForPDF sheet for PDF generation
        
        Args:
            tasks: List of task dictionaries with keys:
                   order_id, photo_url, product_name, article, sticker
        """
        try:
            # Get or create TasksForPDF sheet
            try:
                sheet = self.spreadsheet.worksheet(SHEET_TASKS_FOR_PDF)
            except gspread.exceptions.WorksheetNotFound:
                # Create sheet if it doesn't exist
                self.spreadsheet.add_worksheet(
                    title=SHEET_TASKS_FOR_PDF,
                    rows=1000,
                    cols=10,
                )
                sheet = self.spreadsheet.worksheet(SHEET_TASKS_FOR_PDF)
                
                # Set formula in A1 for automatic image insertion
                formula = '={"Изображение";ARRAYFORMULA(IF(C2:C="";;IMAGE(C2:C;4;350;350)))}'
                sheet.update("A1", [[formula]], value_input_option='USER_ENTERED')
                
                # Set headers in row 1 for columns B-F
                sheet.update("B1:F1", [[
                    "№ задания",
                    "Фото URL",
                    "Наименование",
                    "Артикул продавца",
                    "Стикер",
                ]], value_input_option='USER_ENTERED')
            
            # Clear existing data (keep headers and formula)
            # Delete rows 2 onwards
            existing_values = sheet.get_all_values()
            if len(existing_values) > 1:
                # Delete rows starting from row 2
                sheet.delete_rows(2, len(existing_values))
            
            if not tasks:
                logger.info("No tasks to write to TasksForPDF sheet")
                return
            
            # Prepare data for writing (columns B-F, starting from row 2)
            rows_to_write = []
            for task in tasks:
                row = [
                    str(task.get('order_id', '')),
                    str(task.get('photo_url', '')),
                    str(task.get('product_name', '')),
                    str(task.get('article', '')),
                    str(task.get('sticker', '')),
                ]
                rows_to_write.append(row)
            
            # Write data starting from B2 (A1 has formula, so data starts from row 2, column B)
            if rows_to_write:
                range_name = f"B2:F{len(rows_to_write) + 1}"
                sheet.update(range_name, rows_to_write, value_input_option='USER_ENTERED')
                logger.info(f"Wrote {len(rows_to_write)} tasks to TasksForPDF sheet")
            
        except Exception as e:
            logger.error(f"Error writing tasks to TasksForPDF sheet: {e}")
            raise
    
    @rate_limit
    def export_sheet_to_pdf(self, sheet_name: str, output_path: str, page_size: str = 'A4', orientation: str = 'portrait') -> bool:
        """
        Export Google Sheet to PDF (like CMD+P print)
        
        Args:
            sheet_name: Name of the sheet to export
            output_path: Path to save PDF file
            page_size: Page size (A4, Letter, etc.)
            orientation: 'portrait' or 'landscape'
            
        Returns:
            True if successful, False otherwise
        """
        max_retries = 3
        retry_delay = 5  # seconds
        
        for attempt in range(max_retries):
            try:
                # Get sheet by name to get its GID
                sheet = self.spreadsheet.worksheet(sheet_name)
                sheet_gid = sheet.id  # Get the GID (sheet ID) within the spreadsheet
                
                # Get file ID from spreadsheet
                file_id = GOOGLE_SHEETS_ID
                
                logger.info(f"Exporting sheet '{sheet_name}' (GID: {sheet_gid}) to PDF (attempt {attempt + 1}/{max_retries})...")
                
                # Method 1: Try using Drive API with increased timeout
                try:
                    request = self.drive_service.files().export_media(
                        fileId=file_id,
                        mimeType='application/pdf',
                    )
                    
                    # Download the PDF with timeout
                    file_handle = io.BytesIO()
                    downloader = MediaIoBaseDownload(file_handle, request, chunksize=1024*1024)  # 1MB chunks
                    
                    done = False
                    last_progress = 0
                    while done is False:
                        status, done = downloader.next_chunk(num_retries=3)
                        if status:
                            progress = int(status.progress() * 100)
                            if progress > last_progress:
                                logger.debug(f"Download progress: {progress}%")
                                last_progress = progress
                    
                    # Save to file
                    file_handle.seek(0)
                    pdf_data = file_handle.read()
                    
                    if len(pdf_data) > 0:
                        with open(output_path, 'wb') as f:
                            f.write(pdf_data)
                        
                        logger.info(f"Successfully exported sheet '{sheet_name}' (GID: {sheet_gid}) to PDF: {output_path} ({len(pdf_data)} bytes)")
                        return True
                    else:
                        raise Exception("Downloaded PDF is empty")
                        
                except Exception as api_error:
                    logger.warning(f"Drive API export failed: {api_error}, trying direct URL method...")
                    
                    # Method 2: Fallback to direct URL export
                    # Refresh credentials for direct URL access
                    if not self.creds.valid:
                        self.creds.refresh(GoogleRequest())
                    
                    # Get access token
                    self.creds.refresh(GoogleRequest())
                    access_token = self.creds.token
                    
                    # Direct export URL
                    export_url = f"https://docs.google.com/spreadsheets/d/{file_id}/export"
                    params = {
                        'format': 'pdf',
                        'gid': sheet_gid,
                        'size': 'A4',
                        'portrait': 'true' if orientation == 'portrait' else 'false',
                        'fitw': 'true',
                        'sheetnames': 'false',
                        'printtitle': 'false',
                        'pagenumbers': 'false',
                        'gridlines': 'true',
                    }
                    
                    headers = {
                        'Authorization': f'Bearer {access_token}'
                    }
                    
                    # Download with timeout
                    response = requests.get(
                        export_url,
                        params=params,
                        headers=headers,
                        timeout=300,  # 5 minutes
                        stream=True
                    )
                    response.raise_for_status()
                    
                    # Save to file
                    with open(output_path, 'wb') as f:
                        for chunk in response.iter_content(chunk_size=8192):
                            if chunk:
                                f.write(chunk)
                    
                    file_size = os.path.getsize(output_path)
                    if file_size > 0:
                        logger.info(f"Successfully exported sheet '{sheet_name}' via direct URL to PDF: {output_path} ({file_size} bytes)")
                        return True
                    else:
                        raise Exception("Downloaded PDF is empty")
                        
            except Exception as e:
                error_msg = str(e)
                logger.warning(f"Attempt {attempt + 1}/{max_retries} failed: {error_msg}")
                
                if attempt < max_retries - 1:
                    logger.info(f"Retrying in {retry_delay} seconds...")
                    time.sleep(retry_delay)
                else:
                    logger.error(f"Failed to export sheet '{sheet_name}' to PDF after {max_retries} attempts")
                    import traceback
                    logger.error(traceback.format_exc())
                    return False
        
        return False

