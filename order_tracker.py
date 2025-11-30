"""
Order Tracker
Tracks processed orders to avoid duplicates
"""
import logging
from typing import Set
from sheets_handler import SheetsHandler

logger = logging.getLogger(__name__)


class OrderTracker:
    """Tracks processed orders using Google Sheets as database"""

    def __init__(self, sheets_handler: SheetsHandler):
        """
        Initialize order tracker
        
        Args:
            sheets_handler: SheetsHandler instance for Google Sheets access
        """
        self.sheets_handler = sheets_handler
        self.processed_ids: Set[str] = None
        self._refresh_processed_ids()

    def _refresh_processed_ids(self):
        """Refresh the set of processed order IDs from Google Sheets"""
        try:
            self.processed_ids = self.sheets_handler.get_processed_order_ids()
            logger.info(f"Refreshed processed order IDs: {len(self.processed_ids)} orders")
        except Exception as e:
            logger.error(f"Error refreshing processed order IDs: {e}")
            if self.processed_ids is None:
                self.processed_ids = set()

    def is_processed(self, order_id: int) -> bool:
        """
        Check if an order has been processed
        Checks both ProcessedOrders sheet and Tasks sheet to catch duplicates
        
        Args:
            order_id: Order ID to check
            
        Returns:
            True if order is already processed, False otherwise
        """
        if self.processed_ids is None:
            self._refresh_processed_ids()
        
        order_id_str = str(order_id)
        
        # Check ProcessedOrders sheet
        if order_id_str in self.processed_ids:
            return True
        
        # Also check if order exists in Tasks sheet (might be processed but not marked)
        try:
            if self.sheets_handler.order_exists_in_tasks(order_id):
                logger.debug(f"Order {order_id} found in Tasks sheet, treating as processed")
                return True
        except Exception as e:
            logger.warning(f"Error checking Tasks sheet for order {order_id}: {e}")
        
        return False

    def mark_processed(self, order_id: int, warehouse: str, api_key: str):
        """
        Mark an order as processed
        
        Args:
            order_id: Order ID
            warehouse: Warehouse name
            api_key: API key used
        """
        try:
            order_id_str = str(order_id)
            
            # Skip if already in cache (already marked)
            if self.processed_ids is not None and order_id_str in self.processed_ids:
                logger.debug(f"Order {order_id} already marked as processed in cache")
                return
            
            self.sheets_handler.mark_order_processed(order_id, warehouse, api_key)
            
            # Update local cache immediately
            if self.processed_ids is not None:
                self.processed_ids.add(order_id_str)
            
            logger.debug(f"Marked order {order_id} as processed")
        except Exception as e:
            logger.error(f"Error marking order as processed: {e}")

    def refresh(self):
        """Manually refresh processed order IDs from Google Sheets"""
        self._refresh_processed_ids()

