"""
Telegram Handler
Manages Telegram bot interactions, navigation, and message sending
"""
import logging
import time
import asyncio
import re
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Dict
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from sheets_handler import SheetsHandler
from supply_orders import SupplyOrdersHandler
from wb_api import WildberriesAPI
from pdf_generator import PDFGenerator
from config import SHEET_TASKS_FOR_PDF
import tempfile
import os

logger = logging.getLogger(__name__)


def extract_article_number(article: str) -> int:
    """
    Extract numeric value from article/Offer ID for sorting.
    
    Examples:
        "р20-п5-33" -> 20
        "р25-п5-33" -> 25
        "мд33-п2-30" -> 33
        
    Args:
        article: Article string (e.g., "р20-п5-33")
        
    Returns:
        Extracted number (1-99) or 999 if not found (for sorting)
    """
    if not article:
        return 999
    
    article = str(article).strip()
    
    # Strategy: Remove first 1-2 NON-DIGIT characters, then find first number
    # Try removing 2 non-digit chars first
    if len(article) >= 2 and not article[0].isdigit() and not article[1].isdigit():
        remaining = article[2:]
        if remaining and remaining[0].isdigit() and remaining[0] != '0':
            # Extract first number
            match = re.search(r'\d+', remaining)
            if match:
                number = int(match.group())
                if 1 <= number <= 99:
                    return number
    
    # Try removing 1 non-digit char
    if len(article) >= 1 and not article[0].isdigit():
        remaining = article[1:]
        if remaining and remaining[0].isdigit() and remaining[0] != '0':
            # Extract first number
            match = re.search(r'\d+', remaining)
            if match:
                number = int(match.group())
                if 1 <= number <= 99:
                    return number
    
    # If article starts with a digit, try to extract directly
    if article and article[0].isdigit() and article[0] != '0':
        match = re.search(r'\d+', article)
        if match:
            number = int(match.group())
            if 1 <= number <= 99:
                return number
    
    # If no valid number found, return 999 for sorting (will appear last)
    return 999


class TelegramHandler:
    """Handler for Telegram bot interactions"""

    def __init__(self, sheets_handler: SheetsHandler):
        """
        Initialize Telegram handler
        
        Args:
            sheets_handler: SheetsHandler instance
        """
        self.sheets_handler = sheets_handler
        self.supply_handlers: Dict[str, SupplyOrdersHandler] = {}  # Cache by api_key

    def _get_warehouse_for_order(self, order_id: str) -> Optional[str]:
        """Get warehouse name for a given order ID from ProcessedOrders sheet"""
        try:
            processed_sheet = self.sheets_handler.spreadsheet.worksheet("ProcessedOrders")
            processed_records = processed_sheet.get_all_records()

            for record in processed_records:
                if str(record.get("Order ID", "")).strip() == str(order_id).strip():
                    warehouse = str(record.get("Warehouse", "")).strip()
                    return warehouse if warehouse else None
            return None
        except Exception as e:
            logger.error(f"Error getting warehouse for order {order_id}: {e}")
            return None

    async def send_order_notification(
        self,
        bot,
        chat_id: int,
        order_id: int,
        product_name: str,
        article: str,
        sticker: str,
        warehouse: str = "",
        photo_url: Optional[str] = None,
    ):
        """
        Send order notification to a Telegram user
        
        Args:
            bot: Telegram bot instance
            chat_id: Telegram chat ID
            order_id: Order ID
            product_name: Product name
            article: Seller article
            sticker: Sticker string
            warehouse: Warehouse name (optional)
            photo_url: Optional product photo URL
        """
        try:
            # Format message text
            # Check if sticker is empty or "Не получен"
            has_sticker = sticker and sticker != "Не получен" and sticker.strip()
            
            warehouse_text = f"Склад : {warehouse}\n" if warehouse else ""
            
            if not has_sticker:
                message_text = (
                    f"🆕 НОВОЕ ЗАДАНИЕ!\n"
                    f"Артикул продавца: {article}\n"
                    f"⚠️ Статус: Нужно собрать!\n"
                    f"Наименование: {product_name}\n"
                    f"№ задания: {order_id}\n"
                    f"{warehouse_text}"
                )
            else:
                message_text = (
                    f"🆕 НОВОЕ ЗАДАНИЕ!\n"
                    f"Артикул продавца: {article}\n"
                    f"Стикер: {sticker}\n"
                    f"Наименование: {product_name}\n"
                    f"№ задания: {order_id}\n"
                    f"{warehouse_text}"
                )
            
            # Send photo with caption if available, otherwise send text only
            if photo_url:
                try:
                    await bot.send_photo(
                        chat_id=chat_id,
                        photo=photo_url,
                        caption=message_text,
                    )
                    logger.info(
                        f"Sent order {order_id} notification with photo to chat {chat_id}"
                    )
                except Exception as e:
                    logger.warning(
                        f"Failed to send photo for order {order_id}: {e}. "
                        "Sending text only."
                    )
                    await bot.send_message(
                        chat_id=chat_id,
                        text=message_text,
                    )
            else:
                await bot.send_message(
                    chat_id=chat_id,
                    text=message_text,
                )
                logger.info(f"Sent order {order_id} notification (text only) to chat {chat_id}")
                
        except Exception as e:
            logger.error(f"Error sending order notification to chat {chat_id}: {e}")

    async def send_order_notifications_to_warehouse(
        self,
        bot,
        warehouse: str,
        order_id: int,
        product_name: str,
        article: str,
        sticker: str,
        photo_url: Optional[str] = None,
    ):
        """
        Send order notification to all users with access to a warehouse
        
        Args:
            context: Telegram bot context
            warehouse: Warehouse name
            order_id: Order ID
            product_name: Product name
            article: Seller article
            sticker: Sticker string
            photo_url: Optional product photo URL
        """
        try:
            warehouse_access = self.sheets_handler.get_warehouse_access()
            chat_ids = warehouse_access.get(warehouse, [])
            
            if not chat_ids:
                logger.warning(f"No chat IDs found for warehouse: {warehouse}")
                return
            
            # Send to all chat IDs with access to this warehouse
            for chat_id in chat_ids:
                await self.send_order_notification(
                    bot=bot,
                    chat_id=chat_id,
                    order_id=order_id,
                    product_name=product_name,
                    article=article,
                    sticker=sticker,
                    warehouse=warehouse,
                    photo_url=photo_url,
                )
            
            logger.info(f"Sent order {order_id} notifications to {len(chat_ids)} users for warehouse: {warehouse}")
        except Exception as e:
            logger.error(f"Error sending notifications for warehouse {warehouse}: {e}")

    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command"""
        chat_id = update.effective_chat.id
        
        try:
            user_access = self.sheets_handler.get_user_access()
            user_info = user_access.get(chat_id)
            
            if not user_info:
                # Still show a button to try again
                keyboard = [[InlineKeyboardButton("🔄 Попробовать снова", callback_data="back_to_start")]]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await update.message.reply_text(
                    "Привет! У вас нет доступа к складам.\n"
                    "Обратитесь к администратору для получения доступа.\n\n"
                    "Если доступ был предоставлен, нажмите кнопку ниже:",
                    reply_markup=reply_markup,
                )
                return
            
            warehouses = user_info["warehouses"]
            cities = user_info["cities"]
            
            # Always show city selection if multiple cities
            if len(cities) > 1:
                keyboard = []
                for city in cities:
                    keyboard.append([
                        InlineKeyboardButton(city, callback_data=f"city_{city}")
                    ])
                # Add "View All Orders" button if user has access to all warehouses
                if len(warehouses) > 1:
                    keyboard.append([
                        InlineKeyboardButton(
                            "📋 Все заказы",
                            callback_data="view_all_orders"
                        )
                    ])
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await update.message.reply_text(
                    "👋 Привет! Выберите город или просмотрите все заказы:",
                    reply_markup=reply_markup,
                )
            else:
                # Single city - show warehouse selection
                keyboard = []
                for warehouse in warehouses:
                    keyboard.append([
                        InlineKeyboardButton(warehouse, callback_data=f"warehouse_{warehouse}")
                    ])
                # Add "View All Orders" button if multiple warehouses
                if len(warehouses) > 1:
                    keyboard.append([
                        InlineKeyboardButton(
                            "📋 Все заказы",
                            callback_data="view_all_orders"
                        )
                    ])
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await update.message.reply_text(
                    "👋 Привет! Выберите склад или просмотрите все заказы:",
                    reply_markup=reply_markup,
                )
                    
        except Exception as e:
            logger.error(f"Error in start command: {e}")
            keyboard = [[InlineKeyboardButton("🔄 Попробовать снова", callback_data="back_to_start")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.message.reply_text(
                "Произошла ошибка. Попробуйте позже.",
                reply_markup=reply_markup,
            )

    async def _show_warehouse_selection(
        self, update: Update, warehouses: List[str]
    ):
        """Show warehouse selection keyboard"""
        keyboard = []
        for warehouse in warehouses:
            keyboard.append([
                InlineKeyboardButton(warehouse, callback_data=f"warehouse_{warehouse}")
            ])
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        text = "Выберите склад:" if update.callback_query else "Привет! Выберите склад:"
        
        if update.callback_query:
            await update.callback_query.edit_message_text(
                text=text,
                reply_markup=reply_markup,
            )
        else:
            await update.message.reply_text(
                text=text,
                reply_markup=reply_markup,
            )

    async def callback_query_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle callback queries from inline keyboards"""
        query = update.callback_query
        
        # Handle expired queries gracefully
        try:
            await query.answer()
        except Exception as e:
            logger.warning(f"Error answering callback query (query may be expired): {e}")
        
        data = query.data
        
        if data == "back_to_start":
            await self._handle_back_to_start(update)
        elif data.startswith("city_"):
            city = data.replace("city_", "")
            await self._handle_city_selection(update, city)
        elif data.startswith("warehouse_"):
            warehouse = data.replace("warehouse_", "")
            await self._handle_warehouse_selection(update, warehouse)
        elif data.startswith("supply_"):
            # Parse supply_id and warehouse from callback_data
            parts = data.replace("supply_", "").split("|warehouse_")
            supply_id = parts[0]
            warehouse = parts[1] if len(parts) > 1 else None
            await self._handle_supply_selection(update, supply_id, warehouse)
        elif data.startswith("send_list_"):
            # Parse supply_id and warehouse from callback_data
            parts = data.replace("send_list_", "").split("|warehouse_")
            supply_id = parts[0]
            warehouse = parts[1] if len(parts) > 1 else None
            await self._handle_send_list(update, context, supply_id, warehouse)
        elif data.startswith("send_pdf_"):
            # Parse supply_id and warehouse from callback_data
            parts = data.replace("send_pdf_", "").split("|warehouse_")
            supply_id = parts[0]
            warehouse = parts[1] if len(parts) > 1 else None
            await self._handle_send_pdf(update, context, supply_id, warehouse)
        elif data.startswith("order_"):
            order_id = data.replace("order_", "")
            await self._handle_order_selection(update, order_id)
        elif data.startswith("complete_"):
            order_id = data.replace("complete_", "")
            await self._handle_order_complete(update, order_id)
        elif data.startswith("back_to_warehouse_"):
            warehouse = data.replace("back_to_warehouse_", "")
            await self._handle_warehouse_selection(update, warehouse)
        elif data.startswith("back_to_supplies_"):
            warehouse = data.replace("back_to_supplies_", "")
            await self._handle_warehouse_selection(update, warehouse)
        elif data == "view_all_orders":
            await self._handle_view_all_orders(update)

    async def _handle_city_selection(self, update: Update, city: str):
        """Handle city selection callback"""
        chat_id = update.effective_chat.id
        user_access = self.sheets_handler.get_user_access()
        user_info = user_access.get(chat_id)
        
        if not user_info:
            keyboard = [[InlineKeyboardButton("◀️ Назад", callback_data="back_to_start")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.callback_query.edit_message_text(
                "Ошибка: доступ не найден",
                reply_markup=reply_markup,
            )
            return
        
        # Filter warehouses by city
        warehouse_api_keys = self.sheets_handler.get_warehouse_api_keys()
        city_warehouses = [
            w for w in user_info["warehouses"]
            for item in warehouse_api_keys
            if item["warehouse"] == w and item["city"] == city
        ]
        
        if not city_warehouses:
            keyboard = [[InlineKeyboardButton("◀️ Назад", callback_data="back_to_start")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.callback_query.edit_message_text(
                f"Нет складов в городе {city}",
                reply_markup=reply_markup,
            )
            return
        
        # Show warehouse selection for this city
        keyboard = []
        for warehouse in city_warehouses:
            keyboard.append([
                InlineKeyboardButton(warehouse, callback_data=f"warehouse_{warehouse}")
            ])
        # Add back button
        keyboard.append([
            InlineKeyboardButton("◀️ Назад", callback_data="back_to_start")
        ])
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.callback_query.edit_message_text(
            f"Город: {city}\n\nВыберите склад:",
            reply_markup=reply_markup,
        )
    
    async def _handle_back_to_start(self, update: Update):
        """Handle back to start callback - show initial menu"""
        chat_id = update.effective_chat.id
        
        try:
            user_access = self.sheets_handler.get_user_access()
            user_info = user_access.get(chat_id)
            
            if not user_info:
                keyboard = [[InlineKeyboardButton("◀️ Назад", callback_data="back_to_start")]]
                reply_markup = InlineKeyboardMarkup(keyboard)
                await update.callback_query.edit_message_text(
                    "Ошибка: доступ не найден",
                    reply_markup=reply_markup,
                )
                return
            
            warehouses = user_info["warehouses"]
            cities = user_info["cities"]
            
            # Always show city selection if multiple cities
            if len(cities) > 1:
                keyboard = []
                for city in cities:
                    keyboard.append([
                        InlineKeyboardButton(city, callback_data=f"city_{city}")
                    ])
                # Add "View All Orders" button if user has access to all warehouses
                if len(warehouses) > 1:
                    keyboard.append([
                        InlineKeyboardButton(
                            "📋 Все заказы",
                            callback_data="view_all_orders"
                        )
                    ])
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await update.callback_query.edit_message_text(
                    "👋 Привет! Выберите город или просмотрите все заказы:",
                    reply_markup=reply_markup,
                )
            else:
                # Single city - show warehouse selection
                keyboard = []
                for warehouse in warehouses:
                    keyboard.append([
                        InlineKeyboardButton(warehouse, callback_data=f"warehouse_{warehouse}")
                    ])
                # Add "View All Orders" button if multiple warehouses
                if len(warehouses) > 1:
                    keyboard.append([
                        InlineKeyboardButton(
                            "📋 Все заказы",
                            callback_data="view_all_orders"
                        )
                    ])
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await update.callback_query.edit_message_text(
                    "👋 Привет! Выберите склад или просмотрите все заказы:",
                    reply_markup=reply_markup,
                )
        except Exception as e:
            logger.error(f"Error in back to start: {e}")
            await update.callback_query.edit_message_text("Произошла ошибка. Попробуйте позже.")

    def _get_supply_handler_for_warehouse(self, warehouse: str) -> Optional[SupplyOrdersHandler]:
        """Get SupplyOrdersHandler for a warehouse"""
        try:
            # Get API key for this warehouse
            warehouse_api_keys = self.sheets_handler.get_warehouse_api_keys()
            api_key = None
            
            for item in warehouse_api_keys:
                if item["warehouse"] == warehouse:
                    api_key = item["api_key"]
                    break
            
            if not api_key:
                logger.warning(f"No API key found for warehouse: {warehouse}")
                return None
            
            # Use cached handler or create new one
            if api_key not in self.supply_handlers:
                self.supply_handlers[api_key] = SupplyOrdersHandler(
                    api_key=api_key,
                    sheets_handler=self.sheets_handler
                )
            
            return self.supply_handlers[api_key]
        except Exception as e:
            logger.error(f"Error getting supply handler for warehouse {warehouse}: {e}")
            return None

    async def _handle_warehouse_selection(self, update: Update, warehouse: str):
        """Handle warehouse selection callback - show supplies list"""
        query = update.callback_query
        
        try:
            await query.answer()
        except Exception:
            pass  # Query may be expired, continue anyway
        
        try:
            # Show loading message
            await query.edit_message_text(
                f"📦 Склад: {warehouse}\n\n"
                "⏳ Загрузка поставок...",
            )
            
            # Get supply handler for this warehouse
            supply_handler = self._get_supply_handler_for_warehouse(warehouse)
            
            if not supply_handler:
                keyboard = [[InlineKeyboardButton("◀️ Назад", callback_data="back_to_start")]]
                reply_markup = InlineKeyboardMarkup(keyboard)
                await query.edit_message_text(
                    f"📦 Склад: {warehouse}\n\n"
                    "❌ Ошибка: не найден API ключ для склада.",
                    reply_markup=reply_markup,
                )
                return
            
            # Fetch incomplete supplies for this warehouse
            supplies = supply_handler.fetch_all_incomplete_supplies(max_age_days=365)
            
            if not supplies:
                keyboard = [[InlineKeyboardButton("◀️ Назад", callback_data="back_to_start")]]
                reply_markup = InlineKeyboardMarkup(keyboard)
                await query.edit_message_text(
                    f"📦 Склад: {warehouse}\n\n"
                    "✅ Нет незавершенных поставок за последние 7 дней.\n\n"
                    "Проверьте поставки на портале Wildberries.",
                    reply_markup=reply_markup,
                )
                return
            
            # Show supplies list
            keyboard = []
            
            # Group supplies in rows of 1 (each supply on its own row)
            for supply in supplies[:50]:  # Limit to 50 supplies
                supply_id = supply.get("id", "")
                supply_name = supply.get("name", supply_id)
                created_str = supply.get("createdAt", "")
                
                # Format date for display
                try:
                    if created_str:
                        created_dt = datetime.fromisoformat(created_str.replace('Z', '+00:00'))
                        date_str = created_dt.strftime('%d.%m.%Y')
                    else:
                        date_str = ""
                except Exception:
                    date_str = ""
                
                # Button text: Supply name and date
                button_text = f"📦 {supply_name}"
                if date_str:
                    button_text += f" ({date_str})"
                
                # Store warehouse in callback_data for navigation back
                keyboard.append([
                    InlineKeyboardButton(
                        button_text,
                        callback_data=f"supply_{supply_id}|warehouse_{warehouse}"
                    )
                ])
            
            # Add back button
            keyboard.append([
                InlineKeyboardButton("◀️ Назад", callback_data="back_to_start")
            ])
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(
                f"📦 Склад: {warehouse}\n\n"
                f"📋 Найдено незавершенных поставок: {len(supplies)}\n\n"
                "Выберите поставку для просмотра заказов:",
                reply_markup=reply_markup,
            )
            
        except Exception as e:
            logger.error(f"Error showing supplies for warehouse {warehouse}: {e}")
            keyboard = [[InlineKeyboardButton("◀️ Назад", callback_data="back_to_start")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            try:
                await query.edit_message_text(
                    f"❌ Ошибка при загрузке поставок для склада {warehouse}\n\n"
                    f"Ошибка: {str(e)}",
                    reply_markup=reply_markup,
                )
            except Exception:
                await query.message.reply_text(
                    f"❌ Ошибка при загрузке поставок для склада {warehouse}"
                )
    
    async def _handle_supply_selection(self, update: Update, supply_id: str, warehouse: Optional[str] = None):
        """Handle supply selection - show all orders with details for this supply"""
        query = update.callback_query
        
        try:
            await query.answer()
        except Exception:
            pass
        
        try:
            # Show loading message
            await query.edit_message_text(
                f"📦 Поставка: {supply_id}\n\n"
                "⏳ Загрузка заказов...",
            )
            
            # Get warehouse from parameter or find it
            if not warehouse:
                # Try to find warehouse from context
                warehouse_api_keys = self.sheets_handler.get_warehouse_api_keys()
                for item in warehouse_api_keys:
                    warehouse = item["warehouse"]
                    break
            
            if not warehouse:
                keyboard = [[InlineKeyboardButton("◀️ Назад", callback_data="back_to_start")]]
                reply_markup = InlineKeyboardMarkup(keyboard)
                await query.edit_message_text(
                    f"❌ Ошибка: не определен склад",
                    reply_markup=reply_markup,
                )
                return
            
            # Get supply handler for this warehouse
            supply_handler = self._get_supply_handler_for_warehouse(warehouse)
            
            if not supply_handler:
                keyboard = [[InlineKeyboardButton("◀️ Назад", callback_data="back_to_start")]]
                reply_markup = InlineKeyboardMarkup(keyboard)
                await query.edit_message_text(
                    f"❌ Ошибка: не найден обработчик для склада {warehouse}",
                    reply_markup=reply_markup,
                )
                return
            
            # Fetch order IDs for this supply
            order_ids = supply_handler.fetch_order_ids_for_supply(supply_id)
            
            if not order_ids:
                keyboard = [[InlineKeyboardButton("◀️ Назад", callback_data="back_to_start")]]
                reply_markup = InlineKeyboardMarkup(keyboard)
                await query.edit_message_text(
                    f"📦 Поставка: {supply_id}\n\n"
                    "✅ В этой поставке нет заказов.",
                    reply_markup=reply_markup,
                )
                return
            
            logger.info(f"Found {len(order_ids)} orders in supply {supply_id}")
            
            # Show choice menu: PDF or List
            keyboard = [
                [
                    InlineKeyboardButton(
                        "📄 PDF файл",
                        callback_data=f"send_pdf_{supply_id}|warehouse_{warehouse}"
                    ),
                    InlineKeyboardButton(
                        "📋 Список заказов",
                        callback_data=f"send_list_{supply_id}|warehouse_{warehouse}"
                    )
                ],
                [
                    InlineKeyboardButton(
                        "◀️ Назад",
                        callback_data=f"back_to_supplies_{warehouse}"
                    )
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(
                f"📦 Поставка: {supply_id}\n\n"
                f"📋 Найдено заказов: {len(order_ids)}\n\n"
                "Выберите формат:",
                reply_markup=reply_markup,
            )
            return
            
        except Exception as e:
            logger.error(f"Error showing supply selection menu: {e}")
            keyboard = [[InlineKeyboardButton("◀️ Назад", callback_data="back_to_start")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            try:
                await query.edit_message_text(
                    f"❌ Ошибка при загрузке поставки {supply_id}\n\n"
                    f"Ошибка: {str(e)}",
                    reply_markup=reply_markup,
                )
            except Exception:
                await query.message.reply_text(
                    f"❌ Ошибка при загрузке поставки {supply_id}"
                )
    
    async def _handle_send_list(self, update: Update, context: ContextTypes.DEFAULT_TYPE, supply_id: str, warehouse: str):
        """Handle sending orders as list (individual messages)"""
        query = update.callback_query
        chat_id = update.effective_chat.id
        
        try:
            await query.answer()
        except Exception:
            pass
        
        try:
            # Store the menu message ID to delete later
            menu_message_id = query.message.message_id
            
            # Show loading message
            await query.edit_message_text(
                f"📦 Поставка: {supply_id}\n\n"
                "⏳ Отправка списка заказов...",
            )
            
            # Get supply handler
            supply_handler = self._get_supply_handler_for_warehouse(warehouse)
            if not supply_handler:
                await query.edit_message_text("❌ Ошибка: обработчик не найден")
                return
            
            # Fetch order IDs
            order_ids = supply_handler.fetch_order_ids_for_supply(supply_id)
            if not order_ids:
                await query.edit_message_text(
                    f"📦 Поставка: {supply_id}\n\n✅ В этой поставке нет заказов."
                )
                return
            
            # Fetch order details
            date_from = datetime.now(timezone.utc) - timedelta(days=30)
            date_from_ts = int(date_from.timestamp())
            orders_map = supply_handler._fetch_orders_by_ids(order_ids, date_from_ts)
            
            if not orders_map:
                await query.edit_message_text(
                    "❌ Не удалось загрузить детали заказов."
                )
                return
            
            # Get API key and WB API instance
            warehouse_api_keys = self.sheets_handler.get_warehouse_api_keys()
            api_key = None
            for item in warehouse_api_keys:
                if item["warehouse"] == warehouse:
                    api_key = item["api_key"]
                    break
            wb_api = WildberriesAPI(api_key) if api_key else None
            
            # Prepare orders list and sort by article (Артикул продавца)
            orders_list = []
            for order_id, order_data in orders_map.items():
                article = order_data.get("article", "")
                sku = order_data.get("skus", [""])[0] if order_data.get("skus") else ""
                # Use article or sku for sorting
                article_for_sort = article or sku or ""
                # Extract numeric value for sorting (1-99)
                sort_key = extract_article_number(article_for_sort)
                orders_list.append((sort_key, order_id, order_data))
            
            # Sort by extracted number (ascending: lower to higher)
            orders_list.sort(key=lambda x: x[0])
            logger.info(f"Sorted {len(orders_list)} orders. Starting to fetch stickers...")
            
            # Fetch all stickers in batches (up to 100 per request)
            all_stickers = {}
            if wb_api:
                all_order_ids = [order_id for _, order_id, _ in orders_list]
                logger.info(f"Fetching stickers for {len(all_order_ids)} orders in batches...")
                
                # Process in batches of 100
                batch_size = 100
                for i in range(0, len(all_order_ids), batch_size):
                    batch = all_order_ids[i:i + batch_size]
                    try:
                        batch_stickers = wb_api.get_stickers(batch)
                        all_stickers.update(batch_stickers)
                        logger.info(f"Fetched stickers for batch {i//batch_size + 1} ({len(batch)} orders)")
                    except Exception as e:
                        logger.warning(f"Error fetching stickers for batch: {e}")
            
            # Load all products from sheet once (optimization - avoid multiple API calls)
            logger.info("Loading all products from Products sheet for fast lookup...")
            try:
                products_sheet = self.sheets_handler.spreadsheet.worksheet("Products")
                all_products_records = products_sheet.get_all_records()
                # Create a dictionary for fast lookup: {vendor_code_lower: {photo_url, title}}
                products_cache = {}
                for record in all_products_records:
                    vendor_code = str(record.get("Артикул продавца", "")).strip().lower()
                    if vendor_code:
                        products_cache[vendor_code] = {
                            'photo_url': str(record.get("Фото", "")).strip(),
                            'title': str(record.get("Наименование", "")).strip(),
                        }
                logger.info(f"Loaded {len(products_cache)} products into cache")
            except Exception as e:
                logger.warning(f"Error loading products cache: {e}, will use per-order lookup")
                products_cache = {}
            
            # Prepare all orders data first (for parallel sending)
            logger.info(f"Preparing {len(orders_list)} orders for sending...")
            orders_to_send = []
            for idx, (sort_key, order_id, order_data) in enumerate(orders_list, 1):
                try:
                    article = order_data.get("article", "")
                    sku = order_data.get("skus", [""])[0] if order_data.get("skus") else ""
                    
                    if idx % 10 == 0:
                        logger.info(f"Preparing order {idx}/{len(orders_list)}: {order_id}")
                    
                    # Get product info from cache (fast!) or fallback to API call
                    article_lower = article.strip().lower() if article else ""
                    product_info = products_cache.get(article_lower) if products_cache else None
                    if not product_info and products_cache:
                        # Fallback: try to get from sheet (slower)
                        product_info_dict = self.sheets_handler.get_product_from_sheet(article)
                        product_info = product_info_dict if product_info_dict else None
                    
                    photo_url = product_info.get("photo_url") if product_info else None
                    product_name = product_info.get("title", "") if product_info else ""
                    
                    # Get sticker from batch results
                    sticker = all_stickers.get(order_id, "")
                    if not sticker:
                        sticker = "Нужно собрать!"
                    
                    # Format order details message
                    warehouse_text = f"Склад : {warehouse}\n" if warehouse else ""
                    
                    if sticker and sticker != "Нужно собрать!":
                        message_text = (
                            f"🆕 НОВОЕ ЗАДАНИЕ!\n"
                            f"Артикул продавца: {article or sku or 'Не указано'}\n"
                            f"Стикер: {sticker}\n"
                            f"Наименование: {product_name or 'Не указано'}\n"
                            f"📦 Поставка: {supply_id}\n"
                            f"№ задания: {order_id}\n"
                            f"{warehouse_text}"
                        )
                    else:
                        message_text = (
                            f"🆕 НОВОЕ ЗАДАНИЕ!\n"
                            f"Артикул продавца: {article or sku or 'Не указано'}\n"
                            f"⚠️ Статус: Нужно собрать!\n"
                            f"Наименование: {product_name or 'Не указано'}\n"
                            f"📦 Поставка: {supply_id}\n"
                            f"№ задания: {order_id}\n"
                            f"{warehouse_text}"
                        )
                    
                    orders_to_send.append({
                        'order_id': order_id,
                        'photo_url': photo_url,
                        'message_text': message_text,
                        'article': article or sku or "",
                        'product_name': product_name,
                        'sticker': sticker,
                    })
                except Exception as e:
                    logger.error(f"Error preparing order {order_id}: {e}")
                    continue
            
            if not orders_to_send:
                logger.warning("No orders prepared for sending!")
                await query.edit_message_text(
                    "❌ Не удалось подготовить заказы для отправки."
                )
                return
            
            logger.info(f"Prepared {len(orders_to_send)} orders. Starting to send...")
            
            # Helper function to send a single order
            async def send_single_order(order_data):
                """Send a single order with photo or text"""
                order_id = order_data['order_id']
                photo_url = order_data['photo_url']
                message_text = order_data['message_text']
                
                if photo_url:
                    # Try to send photo (1 attempt only for speed, with fallback)
                    try:
                        await context.bot.send_photo(
                            chat_id=chat_id,
                            photo=photo_url,
                            caption=message_text,
                            read_timeout=60,
                            write_timeout=60,
                            connect_timeout=30,
                        )
                        return True
                    except Exception as e:
                        logger.warning(f"Failed to send photo for order {order_id}: {e}, falling back to text")
                        # Fallback to text message
                        try:
                            await context.bot.send_message(chat_id=chat_id, text=message_text)
                            return True
                        except Exception as e:
                            logger.error(f"Failed to send text message for order {order_id}: {e}")
                            return False
                else:
                    # Send text message
                    try:
                        await context.bot.send_message(chat_id=chat_id, text=message_text)
                        return True
                    except Exception as e:
                        logger.error(f"Failed to send text message for order {order_id}: {e}")
                        return False
            
            # Send orders in parallel batches (10 orders at a time for maximum speed)
            # Telegram API can handle multiple concurrent requests efficiently
            batch_size = 10
            orders_sent = 0
            logger.info(f"Sending {len(orders_to_send)} orders in parallel batches of {batch_size}...")
            
            for i in range(0, len(orders_to_send), batch_size):
                batch = orders_to_send[i:i + batch_size]
                # Send batch in parallel using asyncio.gather
                results = await asyncio.gather(*[send_single_order(order) for order in batch], return_exceptions=True)
                orders_sent += sum(1 for result in results if result is True)
                
                # Very small delay between batches to avoid rate limiting (50ms)
                if i + batch_size < len(orders_to_send):
                    await asyncio.sleep(0.05)
            
            logger.info(f"Sent {orders_sent} out of {len(orders_to_send)} orders")
            
            # Add all orders to Tasks sheet in one batch operation (much faster!)
            logger.info(f"Adding {len(orders_to_send)} orders to Tasks sheet in batch...")
            try:
                # Prepare orders list for batch insert
                orders_for_batch = []
                for order_data in orders_to_send:
                    orders_for_batch.append({
                        'order_id': order_data['order_id'],
                        'photo_url': order_data.get('photo_url') or "",
                        'product_name': order_data.get('product_name') or "",
                        'article': order_data.get('article') or "",
                        'sticker': order_data.get('sticker') or "Нужно собрать!",
                    })
                
                # Write all orders in one batch operation
                if orders_for_batch:
                    self.sheets_handler.add_orders_to_tasks_batch(orders_for_batch)
                    logger.info(f"Successfully added {len(orders_for_batch)} orders to Tasks sheet in batch")
            except Exception as e:
                logger.error(f"Error adding orders to Tasks sheet in batch: {e}")
            
            # Delete the old menu message after all orders are sent
            try:
                await context.bot.delete_message(chat_id=chat_id, message_id=menu_message_id)
                logger.info(f"Deleted old menu message after sending orders from supply {supply_id}")
            except Exception as e:
                logger.debug(f"Could not delete old menu message (may already be deleted): {e}")
            
            # Send menu message at the bottom after all orders are sent
            # This will appear chronologically after all order messages
            keyboard = [
                [InlineKeyboardButton("◀️ Назад к поставкам", callback_data=f"back_to_supplies_{warehouse}")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            try:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=f"📦 Поставка: {supply_id}\n\n"
                         f"✅ Отправлено заказов: {orders_sent} из {len(orders_to_send)}\n\n"
                         "Все заказы загружены ✅",
                    reply_markup=reply_markup,
                )
            except Exception as e:
                logger.warning(f"Could not send menu message: {e}")
            
        except Exception as e:
            import traceback
            logger.error(f"Error showing orders for supply {supply_id}: {e}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            keyboard = [[InlineKeyboardButton("◀️ Назад", callback_data="back_to_start")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            try:
                await query.edit_message_text(
                    f"❌ Ошибка при загрузке заказов для поставки {supply_id}\n\n"
                    f"Ошибка: {str(e)}",
                    reply_markup=reply_markup,
                )
            except Exception:
                await query.message.reply_text(
                    f"❌ Ошибка при загрузке заказов для поставки {supply_id}"
                )
    
    async def _handle_send_pdf(self, update: Update, context: ContextTypes.DEFAULT_TYPE, supply_id: str, warehouse: str):
        """Handle sending PDF file with orders"""
        query = update.callback_query
        chat_id = update.effective_chat.id
        
        try:
            await query.answer()
        except Exception:
            pass
        
        try:
            # Store the menu message ID to delete later
            menu_message_id = query.message.message_id
            
            # Show loading message
            await query.edit_message_text(
                f"📦 Поставка: {supply_id}\n\n"
                "⏳ Генерация PDF файла...",
            )
            
            # Always generate PDF from current supply orders (not from TasksForPDF sheet)
            # TasksForPDF sheet will be populated for viewing in Google Sheets
            tasks = None
            
            # Generate from current supply orders
            if True:  # Always fetch from supply
                # Fetch orders from supply to generate PDF
                supply_handler = self._get_supply_handler_for_warehouse(warehouse)
                if not supply_handler:
                    keyboard = [[InlineKeyboardButton("◀️ Назад", callback_data=f"back_to_supplies_{warehouse}")]]
                    reply_markup = InlineKeyboardMarkup(keyboard)
                    await query.edit_message_text(
                        f"❌ Ошибка: обработчик не найден",
                        reply_markup=reply_markup,
                    )
                    return
                
                # Fetch order IDs
                order_ids = supply_handler.fetch_order_ids_for_supply(supply_id)
                logger.info(f"Found {len(order_ids)} order IDs in supply {supply_id}")
                if not order_ids:
                    keyboard = [[InlineKeyboardButton("◀️ Назад", callback_data=f"back_to_supplies_{warehouse}")]]
                    reply_markup = InlineKeyboardMarkup(keyboard)
                    await query.edit_message_text(
                        f"✅ В этой поставке нет заказов.",
                        reply_markup=reply_markup,
                    )
                    return
                
                # Fetch order details
                date_from = datetime.now(timezone.utc) - timedelta(days=30)
                date_from_ts = int(date_from.timestamp())
                orders_map = supply_handler._fetch_orders_by_ids(order_ids, date_from_ts)
                logger.info(f"Fetched {len(orders_map)} order details from {len(order_ids)} order IDs")
                
                if not orders_map:
                    keyboard = [[InlineKeyboardButton("◀️ Назад", callback_data=f"back_to_supplies_{warehouse}")]]
                    reply_markup = InlineKeyboardMarkup(keyboard)
                    await query.edit_message_text(
                        f"❌ Не удалось загрузить детали заказов.",
                        reply_markup=reply_markup,
                    )
                    return
                
                # Get API key
                warehouse_api_keys = self.sheets_handler.get_warehouse_api_keys()
                api_key = None
                for item in warehouse_api_keys:
                    if item["warehouse"] == warehouse:
                        api_key = item["api_key"]
                        break
                wb_api = WildberriesAPI(api_key) if api_key else None
                
                # Fetch all stickers in batches (up to 100 per request) before processing tasks
                all_stickers = {}
                if wb_api:
                    all_order_ids = list(orders_map.keys())
                    logger.info(f"Fetching stickers for {len(all_order_ids)} orders in batches for PDF...")
                    
                    # Process in batches of 100
                    batch_size = 100
                    for i in range(0, len(all_order_ids), batch_size):
                        batch = all_order_ids[i:i + batch_size]
                        try:
                            batch_stickers = wb_api.get_stickers(batch)
                            all_stickers.update(batch_stickers)
                            logger.info(f"Fetched stickers for batch {i//batch_size + 1} ({len(batch)} orders)")
                        except Exception as e:
                            logger.warning(f"Error fetching stickers for batch: {e}")
                
                # Convert orders to tasks format and sort by article
                tasks = []
                for order_id, order_data in orders_map.items():
                    article = order_data.get("article", "")
                    sku = order_data.get("skus", [""])[0] if order_data.get("skus") else ""
                    
                    # Get product info
                    product_info = self.sheets_handler.get_product_from_sheet(article)
                    photo_url = product_info.get("photo_url") if product_info else None
                    product_name = product_info.get("title", "") if product_info else ""
                    
                    # Get sticker from batch results
                    sticker = all_stickers.get(order_id, "")
                    if not sticker:
                        sticker = "Нужно собрать!"
                    
                    tasks.append({
                        "order_id": str(order_id),
                        "photo_url": photo_url or "",
                        "product_name": product_name or "",
                        "article": article or sku or "",
                        "sticker": sticker,
                    })
                
                # Sort tasks by article (Артикул продавца) - extract number and sort ascending
                if tasks:
                    tasks.sort(key=lambda t: extract_article_number(t.get("article", "") or ""))
                    logger.info(f"Prepared {len(tasks)} tasks for PDF generation from supply {supply_id}")
            
            if not tasks or len(tasks) == 0:
                keyboard = [[InlineKeyboardButton("◀️ Назад", callback_data=f"back_to_supplies_{warehouse}")]]
                reply_markup = InlineKeyboardMarkup(keyboard)
                await query.edit_message_text(
                    f"❌ Нет данных для генерации PDF.",
                    reply_markup=reply_markup,
                )
                return
            
            # Write tasks to TasksForPDF sheet (for viewing in Google Sheets, formula in A1 displays images)
            try:
                self.sheets_handler.write_tasks_to_pdf_sheet(tasks)
                logger.info(f"Wrote {len(tasks)} tasks to TasksForPDF sheet for viewing")
            except Exception as e:
                logger.warning(f"Error writing to TasksForPDF sheet: {e}, continuing with PDF generation...")
                # Continue anyway, PDF can be generated from in-memory data
            
            # Generate PDF using PDFGenerator (reportlab)
            logger.info(f"Generating PDF with {len(tasks)} tasks for supply {supply_id}")
            pdf_generator = PDFGenerator()
            temp_dir = tempfile.mkdtemp()
            pdf_path = os.path.join(temp_dir, f"orders_{supply_id}.pdf")
            
            success = pdf_generator.generate_pdf_from_tasks(
                tasks=tasks,
                output_path=pdf_path,
                title=f"Заказы из поставки {supply_id}",
            )
            
            if not success or not os.path.exists(pdf_path):
                keyboard = [[InlineKeyboardButton("◀️ Назад", callback_data=f"back_to_supplies_{warehouse}")]]
                reply_markup = InlineKeyboardMarkup(keyboard)
                await query.edit_message_text(
                    f"❌ Ошибка при генерации PDF файла.",
                    reply_markup=reply_markup,
                )
                return
            
            # Send PDF file
            try:
                with open(pdf_path, 'rb') as pdf_file:
                    await context.bot.send_document(
                        chat_id=chat_id,
                        document=pdf_file,
                        filename=f"orders_{supply_id}.pdf",
                        caption=f"📄 PDF файл с заказами из поставки {supply_id}\n\n"
                                f"Количество заказов: {len(tasks)}",
                    )
                
                # Delete the old menu message after PDF is sent
                try:
                    await context.bot.delete_message(chat_id=chat_id, message_id=menu_message_id)
                    logger.info(f"Deleted old menu message after sending PDF from supply {supply_id}")
                except Exception as e:
                    logger.debug(f"Could not delete old menu message (may already be deleted): {e}")
                
                # Send menu message at the bottom after PDF is sent
                # This will appear chronologically after PDF message
                keyboard = [
                    [InlineKeyboardButton("◀️ Назад к поставкам", callback_data=f"back_to_supplies_{warehouse}")]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                try:
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text=f"📦 Поставка: {supply_id}\n\n"
                             f"✅ PDF файл успешно отправлен!\n"
                             f"Количество заказов: {len(tasks)}",
                        reply_markup=reply_markup,
                    )
                except Exception as e:
                    logger.warning(f"Could not send menu message: {e}")
                
            except Exception as e:
                logger.error(f"Error sending PDF file: {e}")
                keyboard = [[InlineKeyboardButton("◀️ Назад", callback_data=f"back_to_supplies_{warehouse}")]]
                reply_markup = InlineKeyboardMarkup(keyboard)
                await query.edit_message_text(
                    f"❌ Ошибка при отправке PDF файла: {str(e)}",
                    reply_markup=reply_markup,
                )
            finally:
                # Cleanup
                try:
                    if os.path.exists(pdf_path):
                        os.remove(pdf_path)
                    if os.path.exists(temp_dir):
                        os.rmdir(temp_dir)
                except Exception as e:
                    logger.warning(f"Error cleaning up temp files: {e}")
                
                pdf_generator.cleanup()
            
        except Exception as e:
            logger.error(f"Error generating PDF for supply {supply_id}: {e}")
            keyboard = [[InlineKeyboardButton("◀️ Назад", callback_data=f"back_to_supplies_{warehouse}")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            try:
                await query.edit_message_text(
                    f"❌ Ошибка при генерации PDF для поставки {supply_id}\n\n"
                    f"Ошибка: {str(e)}",
                    reply_markup=reply_markup,
                )
            except Exception:
                await query.message.reply_text(
                    f"❌ Ошибка при генерации PDF для поставки {supply_id}"
                )
    
    async def _handle_order_selection(self, update: Update, order_id: str):
        """Handle order selection - show order details"""
        try:
            # Get order details
            task = self.sheets_handler.get_task_by_order_id(order_id)
            
            if not task:
                await update.callback_query.answer("Заказ не найден", show_alert=True)
                return
            
            # Determine warehouse from ProcessedOrders
            warehouse = self._get_warehouse_for_order(order_id)
            
            # Format message
            status_icon = "🟢" if task.get('status', 'new') == 'new' else "✅"
            status_text = "Новый" if task.get('status', 'new') == 'new' else "Завершен"
            
            message_text = (
                f"{status_icon} Заказ №{task['order_id']}\n"
                f"Статус: {status_text}\n\n"
                f"📦 Наименование: {task['product_name'] or 'Не указано'}\n"
                f"🔖 Артикул продавца: {task['article'] or 'Не указано'}\n"
            )
            
            sticker = task.get('sticker', '').strip()
            if sticker and sticker != "Не получен":
                message_text += f"🏷️ Стикер: {sticker}\n"
            else:
                message_text += "⚠️ Стикер: Нужно собрать!\n"
            
            # Build keyboard
            keyboard = []
            
            # Add complete button if order is new
            if task.get('status', 'new') == 'new':
                keyboard.append([
                    InlineKeyboardButton(
                        "✅ Отметить как выполненный",
                        callback_data=f"complete_{order_id}"
                    )
                ])
            
            # Add back button
            if warehouse:
                keyboard.append([
                    InlineKeyboardButton(
                        "◀️ Назад к списку",
                        callback_data=f"back_to_warehouse_{warehouse}"
                    )
                ])
            else:
                keyboard.append([
                    InlineKeyboardButton("◀️ Назад", callback_data="back_to_start")
                ])
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            # Send order details
            photo_url = task.get('photo_url', '').strip()
            if photo_url:
                # Retry sending photo up to 3 times with increased timeouts
                photo_sent = False
                for retry in range(3):
                    try:
                        await update.callback_query.message.reply_photo(
                            photo=photo_url,
                            caption=message_text,
                            reply_markup=reply_markup,
                            read_timeout=60,
                            write_timeout=60,
                            connect_timeout=30,
                        )
                        photo_sent = True
                        break
                    except Exception as e:
                        if retry < 2:
                            logger.warning(f"Failed to send photo (attempt {retry + 1}/3): {e}, retrying...")
                            await asyncio.sleep(1)
                        else:
                            logger.warning(f"Failed to send photo after 3 attempts: {e}")
                
                if not photo_sent:
                    # Fallback to text message
                    await update.callback_query.message.reply_text(
                        message_text,
                        reply_markup=reply_markup,
                    )
            else:
                await update.callback_query.message.reply_text(
                    message_text,
                    reply_markup=reply_markup,
                )
            
            # Edit original message to remove order list
            await update.callback_query.edit_message_text(
                "Выбран заказ. Детали отправлены ниже ⬇️"
            )
            
        except Exception as e:
            logger.error(f"Error showing order details: {e}")
            await update.callback_query.answer("Ошибка при загрузке деталей заказа", show_alert=True)
    
    async def _handle_order_complete(self, update: Update, order_id: str):
        """Handle marking order as completed"""
        try:
            # Update order status in sheet
            success = self.sheets_handler.update_order_status(order_id, "completed")
            
            if success:
                await update.callback_query.answer("✅ Заказ отмечен как выполненный!", show_alert=True)
                
                # Update the message to reflect new status
                task = self.sheets_handler.get_task_by_order_id(order_id)
                
                if task:
                    message_text = (
                        f"✅ Заказ №{task['order_id']}\n"
                        f"Статус: Завершен\n\n"
                        f"📦 Наименование: {task['product_name'] or 'Не указано'}\n"
                        f"🔖 Артикул продавца: {task['article'] or 'Не указано'}\n"
                    )
                    
                    sticker = task.get('sticker', '').strip()
                    if sticker and sticker != "Не получен":
                        message_text += f"🏷️ Стикер: {sticker}\n"
                    
                    # Remove complete button, only show back
                    warehouse = self._get_warehouse_for_order(order_id)
                    
                    keyboard = []
                    if warehouse:
                        keyboard.append([
                            InlineKeyboardButton(
                                "◀️ Назад к списку",
                                callback_data=f"back_to_warehouse_{warehouse}"
                            )
                        ])
                    else:
                        keyboard.append([
                            InlineKeyboardButton("◀️ Назад", callback_data="back_to_start")
                        ])
                    
                    reply_markup = InlineKeyboardMarkup(keyboard)
                    
                    # Try to edit the last message with order details
                    try:
                        await update.callback_query.message.edit_caption(
                            caption=message_text,
                            reply_markup=reply_markup,
                        )
                    except Exception:
                        # If it's a text message, edit it
                        try:
                            await update.callback_query.message.edit_text(
                                text=message_text,
                                reply_markup=reply_markup,
                            )
                        except Exception:
                            pass
            else:
                await update.callback_query.answer("❌ Ошибка при обновлении статуса", show_alert=True)
                
        except Exception as e:
            logger.error(f"Error marking order as complete: {e}")
            await update.callback_query.answer("❌ Ошибка при обновлении статуса", show_alert=True)

    async def _handle_view_all_orders(self, update: Update):
        """Handle view all orders callback - show order list"""
        try:
            # Get only incomplete (new) orders
            tasks = self.sheets_handler.get_tasks_from_sheet(
                warehouse=None, 
                limit=50,
                status_filter="new"  # Only show incomplete orders
            )
            
            if not tasks:
                # No incomplete orders - show all orders instead
                all_tasks = self.sheets_handler.get_tasks_from_sheet(
                    warehouse=None,
                    limit=50,
                    status_filter=None  # Show all orders
                )
                
                if all_tasks:
                    # Show all orders (completed and new)
                    keyboard = []
                    
                    # Group orders in rows of 2
                    for i in range(0, min(len(all_tasks), 20), 2):  # Limit to 20 orders
                        row = []
                        for task in all_tasks[i:i+2]:
                            order_id = task['order_id']
                            status_icon = "🟢" if task.get('status', 'new') == 'new' else "✅"
                            row.append(
                                InlineKeyboardButton(
                                    f"{status_icon} {order_id}",
                                    callback_data=f"order_{order_id}"
                                )
                            )
                        keyboard.append(row)
                    
                    # Add back button
                    keyboard.append([
                        InlineKeyboardButton("◀️ Назад", callback_data="back_to_start")
                    ])
                    
                    reply_markup = InlineKeyboardMarkup(keyboard)
                    
                    completed_count = sum(1 for t in all_tasks if t.get('status', 'new') != 'new')
                    new_count = len(all_tasks) - completed_count
                    
                    await update.callback_query.edit_message_text(
                        "📋 Все заказы\n\n"
                        f"✅ Нет незавершенных заказов.\n"
                        f"📦 Всего заказов: {len(all_tasks)} "
                        f"(🟢 новых: {new_count}, ✅ завершенных: {completed_count})\n\n"
                        "Выберите заказ для просмотра:",
                        reply_markup=reply_markup,
                    )
                else:
                    # No orders at all
                    keyboard = [[InlineKeyboardButton("◀️ Назад", callback_data="back_to_start")]]
                    reply_markup = InlineKeyboardMarkup(keyboard)
                    
                    await update.callback_query.edit_message_text(
                        "📋 Все заказы\n\n"
                        "✅ Нет заказов.\n\n"
                        "Бот будет автоматически отправлять вам уведомления о новых заказах.",
                        reply_markup=reply_markup,
                    )
                return
            
            # Show order list
            keyboard = []
            
            # Group orders in rows of 2
            for i in range(0, len(tasks), 2):
                row = []
                for task in tasks[i:i+2]:
                    order_id = task['order_id']
                    status_icon = "🟢" if task.get('status', 'new') == 'new' else "✅"
                    row.append(
                        InlineKeyboardButton(
                            f"{status_icon} {order_id}",
                            callback_data=f"order_{order_id}"
                        )
                    )
                keyboard.append(row)
            
            # Add back button
            keyboard.append([
                InlineKeyboardButton("◀️ Назад", callback_data="back_to_start")
            ])
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.callback_query.edit_message_text(
                f"📋 Все заказы\n\n"
                f"📦 Найдено незавершенных: {len(tasks)}\n\n"
                "Выберите заказ для просмотра деталей:",
                reply_markup=reply_markup,
            )
            
        except Exception as e:
            logger.error(f"Error showing all orders: {e}")
            keyboard = [[InlineKeyboardButton("◀️ Назад", callback_data="back_to_start")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.callback_query.edit_message_text(
                "❌ Ошибка при загрузке заказов",
                reply_markup=reply_markup,
            )

