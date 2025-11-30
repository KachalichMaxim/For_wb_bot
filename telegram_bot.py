"""
Main Telegram Bot for Wildberries DBS Orders
Polls WB API every 5 minutes and sends notifications
"""
import logging
import asyncio
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)

from config import TELEGRAM_BOT_TOKEN, POLLING_INTERVAL, LOG_LEVEL, LOG_FILE
from sheets_handler import SheetsHandler
from order_tracker import OrderTracker
from telegram_handler import TelegramHandler
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


class WBBot:
    """Main bot class for Wildberries DBS orders"""

    def __init__(self):
        """Initialize the bot"""
        self.sheets_handler = SheetsHandler()
        self.order_tracker = OrderTracker(self.sheets_handler)
        self.telegram_handler = TelegramHandler(self.sheets_handler)
        self.application = None
        self.processing_task = None

    async def process_new_orders(self):
        """Process new orders from all warehouses"""
        logger.info("Starting order processing cycle...")
        
        try:
            # Refresh processed orders list
            self.order_tracker.refresh()
            
            # Get all warehouse API keys
            warehouses = self.sheets_handler.get_warehouse_api_keys()
            
            if not warehouses:
                logger.warning("No warehouses found in Google Sheets")
                return
            
            # Process orders for each warehouse
            for warehouse_info in warehouses:
                warehouse = warehouse_info["warehouse"]
                api_key = warehouse_info["api_key"]
                city = warehouse_info.get("city", "")
                
                logger.info(f"Processing orders for warehouse: {warehouse} (City: {city})")
                
                try:
                    await self._process_warehouse_orders(warehouse, api_key)
                except Exception as e:
                    logger.error(f"Error processing warehouse {warehouse}: {e}")
                    continue
            
            logger.info("Order processing cycle completed")
            
        except Exception as e:
            logger.error(f"Error in order processing cycle: {e}")

    async def _process_warehouse_orders(self, warehouse: str, api_key: str):
        """
        Process new orders for a specific warehouse
        
        Args:
            warehouse: Warehouse name
            api_key: Wildberries API key
        """
        try:
            # Initialize WB API client
            wb_api = WildberriesAPI(api_key)
            
            # Refresh processed order IDs cache before processing
            # This ensures we catch orders added manually or by other instances
            self.order_tracker.refresh()
            
            # Fetch new orders
            orders = wb_api.get_new_orders()
            
            if not orders:
                logger.debug(f"No new orders for warehouse: {warehouse}")
                return
            
            logger.info(f"Found {len(orders)} new orders for warehouse: {warehouse}")
            
            # Filter out already processed orders
            new_orders = [
                order for order in orders
                if not self.order_tracker.is_processed(order.get("id"))
            ]
            
            if not new_orders:
                logger.debug(f"All {len(orders)} orders already processed for warehouse: {warehouse}")
                return
            
            logger.info(f"Processing {len(new_orders)} new orders for warehouse: {warehouse}")
            
            # Process each new order with delays to prevent rate limiting
            import time
            for idx, order in enumerate(new_orders):
                try:
                    await self._process_order(order, warehouse, api_key, wb_api)
                    # Add delay between orders to prevent rate limiting
                    # More delay if we're processing many orders
                    if idx < len(new_orders) - 1:  # Don't delay after last order
                        delay = 2.0  # 2 seconds between orders
                        time.sleep(delay)
                except Exception as e:
                    logger.error(f"Error processing order {order.get('id')}: {e}")
                    # Still delay even on error to prevent rate limiting
                    if idx < len(new_orders) - 1:
                        time.sleep(1.0)
                    continue
                    
        except Exception as e:
            logger.error(f"Error fetching orders for warehouse {warehouse}: {e}")

    async def _process_order(
        self,
        order: dict,
        warehouse: str,
        api_key: str,
        wb_api: WildberriesAPI,
    ):
        """
        Process a single order
        
        Args:
            order: Order dictionary from WB API
            warehouse: Warehouse name
            api_key: API key used
            wb_api: WildberriesAPI instance
        """
        order_id = order.get("id")
        if not order_id:
            logger.warning("Order missing ID, skipping")
            return
        
        # Double-check: Skip if order already exists in Tasks sheet
        # This prevents duplicates from race conditions or partial failures
        if self.sheets_handler.order_exists_in_tasks(order_id):
            logger.info(f"Order {order_id} already exists in Tasks sheet, skipping")
            # Still mark as processed to avoid retrying
            try:
                self.order_tracker.mark_processed(order_id, warehouse, api_key)
            except Exception:
                pass
            return
        
        logger.info(f"Processing order {order_id}")
        
        # Extract order data
        article = order.get("article", "")
        sku = order.get("skus", [""])[0] if order.get("skus") else ""
        
        # Initialize variables
        product_name = ""  # Not stored in Products sheet, leave empty
        photo_url = None
        sticker = ""
        
        # Fetch sticker with delay to prevent rate limiting
        try:
            import time
            time.sleep(0.5)  # Small delay between API calls
            stickers = wb_api.get_stickers([order_id])
            sticker = stickers.get(order_id, "")
            if sticker:
                logger.debug(f"Got sticker for order {order_id}: {sticker}")
        except Exception as e:
            logger.error(f"Error fetching sticker for order {order_id}: {e}")
        
        # Get product photo URL and name from Products sheet by article (vendorCode)
        photo_url = None
        if article:
            try:
                import time
                time.sleep(0.5)  # Small delay to prevent rate limiting
                product_info = self.sheets_handler.get_product_from_sheet(article)
                if product_info:
                    photo_url = product_info.get("photo_url")
                    # Get product name from sheet if available
                    if product_info.get("title"):
                        product_name = product_info.get("title")
                        logger.info(
                            f"Found product in sheet for article '{article}' "
                            f"(order {order_id}): {product_name}"
                        )
                    if photo_url:
                        logger.info(f"Found product photo in sheet for article '{article}' (order {order_id})")
                else:
                    logger.warning(f"Product not found in sheet for article '{article}' (order {order_id})")
            except Exception as e:
                logger.error(f"Error looking up product in sheet for article '{article}': {e}")
        
        # Record to Google Sheets (always record, even if incomplete)
        # This method now checks for duplicates internally
        try:
            self.sheets_handler.add_order_to_tasks(
                order_id=order_id,
                photo_url=photo_url,
                product_name=product_name,
                article=article or sku,
                sticker=sticker,
            )
        except Exception as e:
            logger.error(f"Error recording order {order_id} to Google Sheets: {e}")
        
        # Send Telegram notifications for ALL new orders (even without sticker/photo)
        try:
            # Get bot instance for sending messages
            if self.application and self.application.bot:
                await self.telegram_handler.send_order_notifications_to_warehouse(
                    bot=self.application.bot,
                    warehouse=warehouse,
                    order_id=order_id,
                    product_name=product_name or "Не указано",
                    article=article or sku or "Не указано",
                    sticker=sticker or "Не получен",
                    photo_url=photo_url,
                )
            else:
                logger.warning(
                    "Application not initialized, skipping Telegram notification"
                )
        except Exception as e:
            logger.error(
                f"Error sending Telegram notification for order {order_id}: {e}"
            )
        
        # Mark as processed
        try:
            self.order_tracker.mark_processed(order_id, warehouse, api_key)
        except Exception as e:
            logger.error(f"Error marking order {order_id} as processed: {e}")

    async def periodic_task(self):
        """Periodic task that runs every POLLING_INTERVAL seconds"""
        while True:
            try:
                await self.process_new_orders()
            except Exception as e:
                logger.error(f"Error in periodic task: {e}")
            
            # Wait for next interval
            await asyncio.sleep(POLLING_INTERVAL)

    async def start_command_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command"""
        await self.telegram_handler.start_command(update, context)

    async def callback_query_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle callback queries"""
        await self.telegram_handler.callback_query_handler(update, context)

    def setup_handlers(self):
        """Setup Telegram bot handlers"""
        # Add command handlers
        self.application.add_handler(CommandHandler("start", self.start_command_handler))
        
        # Add callback query handler
        self.application.add_handler(CallbackQueryHandler(self.callback_query_handler))

    async def post_init(self, application: Application):
        """Post-initialization callback"""
        self.application = application
        logger.info("Bot initialized. Orders are fetched from supplies when warehouse is selected.")
        
        # DISABLED: Automatic order processing
        # Orders are now fetched from supplies when user selects a warehouse in Telegram
        # self.processing_task = asyncio.create_task(self.periodic_task())
        # await self.process_new_orders()

    async def post_shutdown(self, application: Application):
        """Post-shutdown callback"""
        if self.processing_task:
            self.processing_task.cancel()
            try:
                await self.processing_task
            except asyncio.CancelledError:
                pass
        logger.info("Bot shut down")

    def run(self):
        """Run the bot"""
        logger.info("Starting Wildberries DBS Orders Telegram Bot...")
        
        # Create application
        # Note: Timeouts are configured per-message in telegram_handler.py
        # (send_photo calls include read_timeout, write_timeout, connect_timeout)
        builder = Application.builder().token(TELEGRAM_BOT_TOKEN)
        builder = builder.post_init(self.post_init)
        builder = builder.post_shutdown(self.post_shutdown)
        self.application = builder.build()
        
        # Setup handlers
        self.setup_handlers()
        
        # Run the bot
        logger.info("Bot is running. Press Ctrl+C to stop.")
        self.application.run_polling(allowed_updates=Update.ALL_TYPES)


def main():
    """Main entry point"""
    try:
        bot = WBBot()
        bot.run()
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        raise


if __name__ == "__main__":
    main()

