"""
Script to load all products into Products sheet
Run this separately to populate the Products sheet with vendorCode and photo URLs
"""
import logging
from config import LOG_LEVEL, LOG_FILE
from sheets_handler import SheetsHandler
from wb_api import WildberriesAPI

# Configure logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=getattr(logging, LOG_LEVEL.upper(), logging.INFO),
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler(),
    ],
)

logger = logging.getLogger(__name__)


def load_all_products(api_key: str):
    """
    Load all products into Products sheet
    
    Args:
        api_key: Wildberries API key
    """
    sheets_handler = SheetsHandler()
    wb_api = WildberriesAPI(api_key)
    
    # Use content API base from config
    from config import WB_CONTENT_API_BASE
    url = f"{WB_CONTENT_API_BASE}/content/v2/get/cards/list"
    
    logger.info("Starting to load products into Products sheet...")
    
    products_sheet = sheets_handler.spreadsheet.worksheet("Products")
    
    # Get existing products to avoid duplicates
    # Use batch reading to handle large sheets
    existing_products = set()
    current_row_in_sheet = 1  # Start from row 1 (header)
    
    try:
        # Read existing products in batches to handle large sheets
        batch_size = 1000
        start_row = 2  # Start from row 2 (skip header)
        
        while True:
            try:
                range_name = f"A{start_row}:A{start_row + batch_size - 1}"
                vendor_codes = products_sheet.get(range_name)
                
                if not vendor_codes or len(vendor_codes) == 0:
                    break
                
                for row in vendor_codes:
                    if row and len(row) > 0 and row[0]:
                        existing_products.add(str(row[0]).strip().lower())
                
                if len(vendor_codes) < batch_size:
                    break  # Last batch
                
                start_row += batch_size
            except Exception as e:
                logger.warning(f"Stopped reading at row {start_row}: {e}")
                break
        
        # Get total current row count
        try:
            # Get last row by finding first empty cell going backwards
            all_col_a = products_sheet.col_values(1)
            current_row_in_sheet = len(all_col_a) if all_col_a else 1
        except:
            current_row_in_sheet = 1
        
        logger.info(f"Found {len(existing_products)} existing products in sheet (last row: {current_row_in_sheet})")
    except Exception as e:
        logger.warning(f"Could not read existing products: {e}")
    
    current_cursor = None
    pages_fetched = 0
    total_products_written = 0
    products_to_add = []  # Collect products here (batch of 1000)
    max_pages = 1000  # Increased for 10k+ products
    
    while pages_fetched < max_pages:
        # Always set limit to 100, update cursor with limit
        if current_cursor:
            cursor = current_cursor.copy()
            cursor["limit"] = 100
        else:
            cursor = {"limit": 100}
        
        settings = {
            "cursor": cursor,
            "filter": {"withPhoto": -1},
        }
        
        data = {"settings": settings}
        
        logger.info(f"Fetching product cards page {pages_fetched + 1} (limit: 100)...")
        
        response = wb_api._make_request(wb_api.content_session, "POST", url, data=data)
        
        if not response:
            logger.error(f"Failed to fetch product cards at page {pages_fetched + 1}")
            break
        
        try:
            response_data = response.json()
            cards = response_data.get("cards", [])
            next_cursor = response_data.get("cursor")
            
            logger.debug(f"Received {len(cards)} cards, cursor: {next_cursor}")
            
            if not cards:
                logger.info("No more cards to fetch")
                break
            
            # Process cards and collect products (batch 1000 before writing)
            page_new_count = 0
            for card in cards:
                vendor_code = str(card.get("vendorCode", "")).strip()
                if not vendor_code:
                    continue
                
                vendor_code_lower = vendor_code.lower()
                
                # Skip if already exists
                if vendor_code_lower in existing_products:
                    continue
                
                # Get photo URL (big image)
                photos = card.get("photos", [])
                photo_url = ""
                if photos and len(photos) > 0:
                    photo_url = photos[0].get("big", "")
                
                # Get product title
                title = str(card.get("title", "")).strip()
                
                # Add: vendorCode, photo URL, title (columns A, B, C)
                products_to_add.append([vendor_code, photo_url, title])
                existing_products.add(vendor_code_lower)
                page_new_count += 1
            
            logger.info(
                f"Page {pages_fetched + 1}: Processed {len(cards)} cards, "
                f"found {page_new_count} new products "
                f"(collected {len(products_to_add)} total, need {max(0, 1000 - len(products_to_add))} more to reach 1000)"
            )
            
            # Write when we have 1000 products (10 fetches of 100 each)
            if len(products_to_add) >= 1000:
                try:
                    next_row = current_row_in_sheet + 1
                    needed_rows = next_row + len(products_to_add) - 1
                    
                    # Check current sheet max size and expand if needed
                    max_rows = products_sheet.row_count
                    if needed_rows > max_rows:
                        rows_to_add = ((needed_rows - max_rows) // 1000 + 1) * 1000
                        products_sheet.add_rows(rows_to_add)
                        logger.info(
                            f"Expanded Products sheet: added {rows_to_add} rows "
                            f"(total now: {max_rows + rows_to_add})"
                        )
                    
                    # Write all 1000 products in one batch (columns A-C)
                    range_name = f"A{next_row}:C{next_row + len(products_to_add) - 1}"
                    products_sheet.update(
                        range_name,
                        products_to_add,
                        value_input_option='USER_ENTERED'
                    )
                    
                    # Update our row counter
                    current_row_in_sheet += len(products_to_add)
                    total_products_written += len(products_to_add)
                    
                    logger.info(
                        f"✅ Batch write: Added {len(products_to_add)} products to sheet "
                        f"(rows {next_row}-{next_row + len(products_to_add) - 1}, "
                        f"total written: {total_products_written})"
                    )
                    
                    # Clear batch
                    products_to_add = []
                    
                except Exception as e:
                    logger.error(f"Error writing products to sheet: {e}")
                    import traceback
                    logger.error(traceback.format_exc())
            
            if not next_cursor:
                logger.info("No more pages available")
                break
            
            current_cursor = next_cursor
            pages_fetched += 1
            
        except Exception as e:
            logger.error(f"Error parsing product cards response: {e}")
            import traceback
            logger.error(traceback.format_exc())
            break
    
    # Write remaining products if any (less than 1000)
    if products_to_add:
        try:
            next_row = current_row_in_sheet + 1
            needed_rows = next_row + len(products_to_add) - 1
            
            # Check current sheet max size and expand if needed
            max_rows = products_sheet.row_count
            if needed_rows > max_rows:
                rows_to_add = ((needed_rows - max_rows) // 1000 + 1) * 1000
                products_sheet.add_rows(rows_to_add)
                logger.info(
                    f"Expanded Products sheet: added {rows_to_add} rows"
                )
            
            # Write remaining products (columns A-C)
            range_name = f"A{next_row}:C{next_row + len(products_to_add) - 1}"
            products_sheet.update(
                range_name,
                products_to_add,
                value_input_option='USER_ENTERED'
            )
            
            total_products_written += len(products_to_add)
            logger.info(
                f"✅ Final batch: Added {len(products_to_add)} remaining products "
                f"(total written: {total_products_written})"
            )
        except Exception as e:
            logger.error(f"Error writing remaining products to sheet: {e}")
            import traceback
            logger.error(traceback.format_exc())
    
    logger.info(
        f"Completed loading products. "
        f"Total products written: {total_products_written} from {pages_fetched + 1} pages"
    )


def main():
    """Main entry point"""
    sheets_handler = SheetsHandler()
    warehouses = sheets_handler.get_warehouse_api_keys()
    
    if not warehouses:
        logger.error("No warehouses found. Please configure warehouses in the WB sheet.")
        return
    
    # Use first warehouse's API key
    api_key = warehouses[0]["api_key"]
    logger.info(f"Using API key from warehouse: {warehouses[0]['warehouse']}")
    
    load_all_products(api_key)


if __name__ == "__main__":
    main()
