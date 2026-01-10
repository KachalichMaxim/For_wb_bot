"""
Supply Orders Module
Fetches orders from supplies and syncs them with Tasks sheet
"""
import logging
import requests
import time
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Optional, Set
from sheets_handler import SheetsHandler
from wb_api import WildberriesAPI

logger = logging.getLogger(__name__)

WB_MARKETPLACE_API_BASE = "https://marketplace-api.wildberries.ru"


class SupplyOrdersHandler:
    """Handles fetching orders from supplies"""
    
    def __init__(self, api_key: str, sheets_handler: SheetsHandler):
        """
        Initialize Supply Orders Handler
        
        Args:
            api_key: Wildberries API key
            sheets_handler: SheetsHandler instance
        """
        self.api_key = api_key
        self.sheets_handler = sheets_handler
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": api_key,
            "Content-Type": "application/json",
        })
    
    def fetch_supplies(
        self,
        limit: int = 1000,
        next_token: int = 0,
    ) -> Dict:
        """
        Fetch supplies from Wildberries API
        
        Args:
            limit: Maximum number of supplies to return (1-1000)
            next_token: Pagination token (0 for first request)
            
        Returns:
            Dictionary with 'supplies' list and 'next' token
        """
        url = f"{WB_MARKETPLACE_API_BASE}/api/v3/supplies"
        
        params = {
            "limit": limit,
            "next": next_token,
        }
        
        try:
            response = self.session.get(url, params=params, timeout=30)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"Error fetching supplies: {e}")
            if hasattr(e, 'response') and e.response is not None:
                logger.error(f"Response: {e.response.text}")
            return {}
    
    def fetch_all_incomplete_supplies(self, max_age_days: int = 7) -> List[Dict]:
        """
        Fetch all incomplete supplies not older than max_age_days
        
        Args:
            max_age_days: Maximum age of supplies in days (default: 7)
            
        Returns:
            List of incomplete supply dictionaries
        """
        all_supplies = []
        next_token = 0
        request_count = 0
        max_requests = 100
        
        # Create cutoff_date as timezone-aware (UTC)
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=max_age_days)
        cutoff_date_str = cutoff_date.strftime('%Y-%m-%d %H:%M:%S UTC')
        
        logger.info(f"Fetching incomplete supplies from last {max_age_days} days...")
        logger.info(f"Cutoff date: {cutoff_date_str} (supplies before this date will be filtered out)")
        
        total_supplies_received = 0
        total_filtered_done = 0
        total_filtered_age = 0
        total_filtered_no_created = 0
        
        while request_count < max_requests:
            request_count += 1
            logger.info(f"Request {request_count}/{max_requests}: Fetching supplies (next_token={next_token})...")
            
            result = self.fetch_supplies(limit=1000, next_token=next_token)
            
            if not result:
                logger.warning(f"Failed to fetch supplies on request {request_count}, stopping")
                break
            
            supplies = result.get("supplies", [])
            next_token = result.get("next")
            
            total_supplies_received += len(supplies)
            logger.info(f"Request {request_count}: Received {len(supplies)} supplies in batch (total so far: {total_supplies_received})")
            
            if len(supplies) == 0:
                logger.info(f"Request {request_count}: No more supplies to fetch")
                break
            
            # Filter supplies
            batch_filtered_done = 0
            batch_filtered_age = 0
            batch_filtered_no_created = 0
            batch_added = 0
            
            for supply in supplies:
                supply_id = supply.get("id", "unknown")
                supply_name = supply.get("name", "unknown")
                
                # Check if done is False (incomplete supplies have done=False)
                done_status = supply.get("done", True)
                if done_status:
                    batch_filtered_done += 1
                    logger.debug(f"Supply {supply_id} ({supply_name}) filtered: done=True (completed)")
                    continue
                
                # Check age - use createdAt
                created_str = supply.get("createdAt")
                if not created_str:
                    batch_filtered_no_created += 1
                    logger.warning(f"Supply {supply_id} ({supply_name}) filtered: no createdAt date")
                    continue
                
                try:
                    # Parse ISO format with timezone (Z means UTC)
                    if created_str.endswith('Z'):
                        created_dt = datetime.fromisoformat(created_str.replace('Z', '+00:00'))
                    else:
                        created_dt = datetime.fromisoformat(created_str)
                    
                    # Ensure timezone-aware for comparison
                    if created_dt.tzinfo is None:
                        created_dt = created_dt.replace(tzinfo=timezone.utc)
                    
                    created_str_formatted = created_dt.strftime('%Y-%m-%d %H:%M:%S UTC')
                    age_days = (datetime.now(timezone.utc) - created_dt).days
                    
                    if created_dt < cutoff_date:
                        batch_filtered_age += 1
                        logger.info(
                            f"Supply {supply_id} ({supply_name}) filtered: too old "
                            f"(created: {created_str_formatted}, age: {age_days} days, cutoff: {cutoff_date_str})"
                        )
                        continue
                    
                    # Supply passed all filters
                    all_supplies.append(supply)
                    batch_added += 1
                    logger.info(
                        f"Supply {supply_id} ({supply_name}) added: "
                        f"(created: {created_str_formatted}, age: {age_days} days, done: {done_status})"
                    )
                    
                except Exception as e:
                    logger.error(
                        f"Error parsing createdAt for supply {supply_id} ({supply_name}): {e}, "
                        f"createdAt value: {created_str}"
                    )
                    continue
            
            total_filtered_done += batch_filtered_done
            total_filtered_age += batch_filtered_age
            total_filtered_no_created += batch_filtered_no_created
            
            logger.info(
                f"Request {request_count} batch summary: "
                f"received={len(supplies)}, "
                f"added={batch_added}, "
                f"filtered_done={batch_filtered_done}, "
                f"filtered_age={batch_filtered_age}, "
                f"filtered_no_created={batch_filtered_no_created}"
            )
            
            # If no next token, we've fetched all supplies
            if not next_token:
                logger.info(f"No next token, all supplies fetched after {request_count} requests")
                break
            
            # Small delay to avoid rate limiting
            time.sleep(0.1)
        
        logger.info(
            f"Fetching complete. Summary: "
            f"total_received={total_supplies_received}, "
            f"total_added={len(all_supplies)}, "
            f"total_filtered_done={total_filtered_done}, "
            f"total_filtered_age={total_filtered_age}, "
            f"total_filtered_no_created={total_filtered_no_created}"
        )
        
        if len(all_supplies) == 0 and total_supplies_received > 0:
            logger.warning(
                f"WARNING: Received {total_supplies_received} supplies but all were filtered out! "
                f"Filtered by done: {total_filtered_done}, by age: {total_filtered_age}, "
                f"no createdAt: {total_filtered_no_created}"
            )
        
        logger.info(f"Total incomplete supplies found: {len(all_supplies)}")
        return all_supplies
    
    def fetch_order_ids_for_supply(self, supply_id: str) -> List[int]:
        """
        Fetch order IDs for a specific supply
        
        Args:
            supply_id: Supply ID (e.g., "WB-GI-1234567")
            
        Returns:
            List of order IDs
        """
        url = (
            f"{WB_MARKETPLACE_API_BASE}/api/marketplace/v3/supplies/"
            f"{supply_id}/order-ids"
        )
        
        try:
            response = self.session.get(url, timeout=30)
            response.raise_for_status()
            result = response.json()
            
            # Response might be a list of order IDs or a dict with 'orderIds'
            if isinstance(result, list):
                return result
            elif isinstance(result, dict):
                return result.get("orderIds", [])
            else:
                logger.warning(
                    f"Unexpected response format for supply {supply_id}: {result}"
                )
                return []
        except requests.exceptions.RequestException as e:
            logger.error(f"Error fetching order IDs for supply {supply_id}: {e}")
            if hasattr(e, 'response') and e.response is not None:
                logger.error(f"Response: {e.response.text}")
            return []
    
    def fetch_orders_for_supplies(
        self,
        max_age_days: int = 365,
        date_from: Optional[int] = None,
    ) -> Dict[int, Dict]:
        """
        Fetch all orders from incomplete supplies
        
        Args:
            max_age_days: Maximum age of supplies in days
            date_from: Optional Unix timestamp for order date filter
            
        Returns:
            Dictionary mapping order_id to order data
        """
        # Get all incomplete supplies
        supplies = self.fetch_all_incomplete_supplies(max_age_days=max_age_days)
        
        if not supplies:
            logger.info("No incomplete supplies found")
            return {}
        
        # Collect all order IDs from supplies
        all_order_ids = []
        for supply in supplies:
            supply_id = supply.get("id")
            if not supply_id:
                continue
            
            order_ids = self.fetch_order_ids_for_supply(supply_id)
            all_order_ids.extend(order_ids)
            time.sleep(0.3)  # Rate limiting
        
        logger.info(f"Found {len(all_order_ids)} total order IDs from supplies")
        
        if not all_order_ids:
            return {}
        
        # Fetch order details using /api/v3/orders endpoint
        if not date_from:
            date_from_dt = datetime.now() - timedelta(days=max_age_days + 7)
            date_from = int(date_from_dt.timestamp())
        
        orders_map = self._fetch_orders_by_ids(all_order_ids, date_from)
        
        return orders_map
    
    def _fetch_orders_by_ids(
        self,
        order_ids: List[int],
        date_from: Optional[int] = None,
    ) -> Dict[int, Dict]:
        """
        Fetch order details by order IDs using /api/v3/orders endpoint
        
        Args:
            order_ids: List of order IDs to fetch
            date_from: Optional Unix timestamp for date filter
            
        Returns:
            Dictionary mapping order_id to order data
        """
        orders_map = {}
        order_ids_set = set(order_ids)
        next_token = 0
        request_count = 0
        max_requests = 100
        
        url = f"{WB_MARKETPLACE_API_BASE}/api/v3/orders"
        
        logger.info(
            f"Fetching orders to find {len(order_ids)} specific orders..."
        )
        
        while (
            request_count < max_requests
            and len(orders_map) < len(order_ids_set)
        ):
            params = {
                "limit": 1000,
                "next": next_token,
            }
            
            if date_from:
                params["dateFrom"] = date_from
            
            try:
                response = self.session.get(url, params=params, timeout=30)
                response.raise_for_status()
                result = response.json()
                
                orders = result.get("orders", [])
                next_token = result.get("next")
                
                logger.debug(f"Received {len(orders)} orders in batch")
                
                # Filter orders we need
                for order in orders:
                    order_id = order.get("id")
                    if order_id and order_id in order_ids_set:
                        orders_map[order_id] = order
                        logger.debug(f"Found order {order_id}")
                        
                        # If we found all orders, we can stop early
                        if len(orders_map) >= len(order_ids_set):
                            logger.info(
                                "Found all requested orders, stopping fetch"
                            )
                            break
                
                # Check if we should continue pagination
                if not next_token or next_token == 0:
                    logger.info("No next token, all orders fetched")
                    break
                
                request_count += 1
                time.sleep(0.5)  # Rate limiting
                
            except requests.exceptions.RequestException as e:
                logger.error(f"Error fetching orders: {e}")
                break
        
        logger.info(
            f"Found {len(orders_map)} out of {len(order_ids)} requested orders"
        )
        return orders_map
    
    def get_warehouse_id_mapping(self) -> Dict[str, int]:
        """
        Get mapping of warehouse names to warehouse IDs from ProcessedOrders
        
        Returns:
            Dictionary mapping warehouse name to warehouse_id
        """
        mapping = {}
        try:
            # Get warehouse mapping from ProcessedOrders sheet
            # We'll need to match order IDs to get warehouse IDs
            # For now, return empty dict - this will be populated when we
            # process orders and can extract warehouse_id from order data
            return mapping
        except Exception as e:
            logger.error(f"Error getting warehouse ID mapping: {e}")
            return mapping
    
    def get_orders_for_warehouse_name(
        self,
        warehouse_name: str,
        max_age_days: int = 7,
    ) -> List[Dict]:
        """
        Get orders for a warehouse by name
        Fetches orders from supplies and filters by matching warehouse_id
        from ProcessedOrders sheet
        
        Args:
            warehouse_name: Warehouse name from WB sheet
            max_age_days: Maximum age of supplies in days
            
        Returns:
            List of order dictionaries for this warehouse
        """
        logger.info(f"Fetching orders for warehouse: {warehouse_name}")
        
        # Get warehouse_id for this warehouse from ProcessedOrders
        # We'll match by checking which warehouse_id is associated
        # with orders from this warehouse name in ProcessedOrders
        warehouse_id = self._get_warehouse_id_for_name(warehouse_name)
        
        if not warehouse_id:
            logger.warning(
                f"Could not determine warehouse_id for {warehouse_name}, "
                "fetching all orders from supplies"
            )
        
        # Fetch all orders from supplies
        orders_map = self.fetch_orders_for_supplies(max_age_days=max_age_days)
        
        if not orders_map:
            logger.info("No orders found in supplies")
            return []
        
        # Filter by warehouse_id if we have it
        if warehouse_id:
            warehouse_orders = [
                order_data
                for order_id, order_data in orders_map.items()
                if order_data.get("warehouseId") == warehouse_id
            ]
            logger.info(
                f"Found {len(warehouse_orders)} orders for warehouse_id "
                f"{warehouse_id} ({warehouse_name})"
            )
            return warehouse_orders
        else:
            # If we can't determine warehouse_id, return all orders
            # and let the user filter manually
            logger.info(
                f"Returning all {len(orders_map)} orders from supplies "
                "(warehouse_id not determined)"
            )
            return list(orders_map.values())
    
    def _get_warehouse_id_for_name(self, warehouse_name: str) -> Optional[int]:
        """
        Get warehouse_id for a warehouse name by checking ProcessedOrders
        
        Args:
            warehouse_name: Warehouse name
            
        Returns:
            Warehouse ID or None
        """
        try:
            # Check ProcessedOrders to find orders for this warehouse
            # Then fetch one order to get its warehouse_id
            processed_sheet = self.sheets_handler.spreadsheet.worksheet(
                "ProcessedOrders"
            )
            processed_records = processed_sheet.get_all_records()
            
            # Find an order ID for this warehouse
            order_id_for_warehouse = None
            for record in processed_records:
                record_warehouse = str(record.get("Warehouse", "")).strip()
                if record_warehouse == warehouse_name:
                    order_id_str = str(record.get("Order ID", "")).strip()
                    if order_id_str:
                        try:
                            order_id_for_warehouse = int(order_id_str)
                            break
                        except ValueError:
                            continue
            
            if order_id_for_warehouse:
                # Fetch this order to get warehouse_id
                orders_map = self._fetch_orders_by_ids(
                    [order_id_for_warehouse], date_from=None
                )
                if orders_map:
                    order_data = orders_map.get(order_id_for_warehouse)
                    if order_data:
                        warehouse_id = order_data.get("warehouseId")
                        logger.info(
                            f"Determined warehouse_id {warehouse_id} for "
                            f"warehouse {warehouse_name}"
                        )
                        return warehouse_id
            
            return None
        except Exception as e:
            logger.error(f"Error getting warehouse_id for {warehouse_name}: {e}")
            return None
