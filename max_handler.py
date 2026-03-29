"""
MAX Handler
Manages MAX bot interactions, navigation, and message sending
"""
import logging
import asyncio
import re
import tempfile
import os
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Dict

import requests
from maxapi import Bot
from maxapi.types import (
    MessageCreated,
    MessageCallback,
    BotStarted,
    CallbackButton,
    InputMedia,
    InputMediaBuffer,
)
from maxapi.utils.inline_keyboard import InlineKeyboardBuilder
from sheets_handler import SheetsHandler
from supply_orders import SupplyOrdersHandler
from wb_api import WildberriesAPI
from pdf_generator import PDFGenerator

logger = logging.getLogger(__name__)


def extract_article_number(article: str) -> int:
    if not article:
        return 999

    article = str(article).strip()

    if len(article) >= 2 and not article[0].isdigit() and not article[1].isdigit():
        remaining = article[2:]
        if remaining and remaining[0].isdigit() and remaining[0] != '0':
            match = re.search(r'\d+', remaining)
            if match:
                number = int(match.group())
                if 1 <= number <= 99:
                    return number

    if len(article) >= 1 and not article[0].isdigit():
        remaining = article[1:]
        if remaining and remaining[0].isdigit() and remaining[0] != '0':
            match = re.search(r'\d+', remaining)
            if match:
                number = int(match.group())
                if 1 <= number <= 99:
                    return number

    if article and article[0].isdigit() and article[0] != '0':
        match = re.search(r'\d+', article)
        if match:
            number = int(match.group())
            if 1 <= number <= 99:
                return number

    return 999


class MaxHandler:
    """Handler for MAX bot interactions"""

    def __init__(self, sheets_handler: SheetsHandler, bot: Bot):
        self.sheets_handler = sheets_handler
        self.bot = bot
        self.supply_handlers: Dict[str, SupplyOrdersHandler] = {}

    def _get_chat_id(self, event: 'MessageCallback') -> int:
        """Extract chat_id from a MessageCallback event."""
        if event.message and event.message.recipient:
            cid = event.message.recipient.chat_id
            if cid:
                return cid
        return event.callback.user.user_id

    def _get_message_id(self, event: 'MessageCallback') -> Optional[str]:
        """Extract message id from a MessageCallback event."""
        if event.message and event.message.body:
            return event.message.body.mid
        return None

    async def _image_bytes_from_url(self, url: str) -> Optional[bytes]:
        """Download image bytes for MAX upload (InputMedia only accepts local path)."""
        url = (url or "").strip()
        if not url:
            return None

        def _fetch() -> Optional[bytes]:
            try:
                r = requests.get(url, timeout=30)
                if r.status_code == 200 and r.content:
                    return r.content
            except Exception as e:
                logger.warning("Failed to download image %s: %s", url[:160], e)
            return None

        return await asyncio.to_thread(_fetch)

    async def _edit_or_send(self, event: 'MessageCallback',
                            text: str,
                            keyboard: Optional[InlineKeyboardBuilder] = None):
        """Edit the callback message, or send a new one if edit fails."""
        attachments = [keyboard.as_markup()] if keyboard else None
        mid = self._get_message_id(event)
        if mid:
            try:
                await self.bot.edit_message(
                    message_id=mid,
                    text=text,
                    attachments=attachments,
                )
                return
            except Exception as e:
                logger.warning("edit_message failed mid=%s: %s", mid, e)
        chat_id = self._get_chat_id(event)
        user_id = (
            event.callback.user.user_id
            if event.callback and event.callback.user
            else None
        )
        try:
            await self.bot.send_message(
                chat_id=chat_id,
                text=text,
                attachments=attachments,
            )
        except Exception as e:
            logger.warning(
                "send_message chat_id=%s failed: %s; retry user_id=%s",
                chat_id,
                e,
                user_id,
            )
            if user_id is not None:
                await self.bot.send_message(
                    user_id=user_id,
                    text=text,
                    attachments=attachments,
                )
            else:
                raise

    def _get_warehouse_for_order(self, order_id: str) -> Optional[str]:
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

    def _build_keyboard(self, buttons_rows: List[List[Dict]]) -> InlineKeyboardBuilder:
        """Build an InlineKeyboardBuilder from rows of button dicts with text+payload."""
        builder = InlineKeyboardBuilder()
        for row in buttons_rows:
            row_buttons = []
            for btn in row:
                row_buttons.append(
                    CallbackButton(text=btn["text"], payload=btn["payload"])
                )
            builder.row(*row_buttons)
        return builder

    async def handle_bot_started(self, event: BotStarted):
        """Handle when user presses 'Start' button on the bot."""
        chat_id = event.chat_id

        user_name = ""
        user_username = ""
        if hasattr(event, "user") and event.user:
            user_name = getattr(event.user, "first_name", "") or ""
            user_username = getattr(event.user, "username", "") or ""
        elif hasattr(event, "from_user") and event.from_user:
            user_name = getattr(event.from_user, "first_name", "") or ""
            user_username = getattr(event.from_user, "username", "") or ""

        try:
            self.sheets_handler.log_user_contact(
                chat_id=chat_id,
                username=user_username,
                first_name=user_name,
            )
        except Exception as e:
            logger.warning(f"Could not log user contact: {e}")

        try:
            user_access = self.sheets_handler.get_user_access()
            user_info = user_access.get(chat_id)

            if not user_info:
                builder = self._build_keyboard([
                    [{"text": "🔄 Попробовать снова", "payload": "back_to_start"}]
                ])
                await self.bot.send_message(
                    chat_id=chat_id,
                    text=f"Привет! У вас нет доступа к складам.\n"
                         f"Ваш Chat ID: {chat_id}\n\n"
                         f"Сообщите этот ID администратору "
                         f"для получения доступа.\n\n"
                         f"Если доступ был предоставлен, "
                         f"нажмите кнопку ниже:",
                    attachments=[builder.as_markup()],
                )
                return

            warehouses = user_info["warehouses"]
            cities = user_info["cities"]

            if len(cities) > 1:
                rows = []
                for city in cities:
                    rows.append([{"text": city, "payload": f"city_{city}"}])
                if len(warehouses) > 1:
                    rows.append([{"text": "📋 Все заказы", "payload": "view_all_orders"}])
                builder = self._build_keyboard(rows)
                await self.bot.send_message(
                    chat_id=chat_id,
                    text="👋 Привет! Выберите город или просмотрите все заказы:",
                    attachments=[builder.as_markup()],
                )
            else:
                rows = []
                for warehouse in warehouses:
                    rows.append([{"text": warehouse, "payload": f"warehouse_{warehouse}"}])
                if len(warehouses) > 1:
                    rows.append([{"text": "📋 Все заказы", "payload": "view_all_orders"}])
                builder = self._build_keyboard(rows)
                await self.bot.send_message(
                    chat_id=chat_id,
                    text="👋 Привет! Выберите склад или просмотрите все заказы:",
                    attachments=[builder.as_markup()],
                )
        except Exception as e:
            logger.error(f"Error in bot_started handler: {e}")
            builder = self._build_keyboard([
                [{"text": "🔄 Попробовать снова", "payload": "back_to_start"}]
            ])
            await self.bot.send_message(
                chat_id=chat_id,
                text="Произошла ошибка. Попробуйте позже.",
                attachments=[builder.as_markup()],
            )

    async def handle_start_command(self, event: MessageCreated):
        """Handle /start command."""
        chat_id = event.chat_id

        user_name = ""
        user_username = ""
        if hasattr(event, "from_user") and event.from_user:
            user_name = getattr(event.from_user, "first_name", "") or ""
            user_username = getattr(event.from_user, "username", "") or ""

        try:
            self.sheets_handler.log_user_contact(
                chat_id=chat_id,
                username=user_username,
                first_name=user_name,
            )
        except Exception as e:
            logger.warning(f"Could not log user contact: {e}")

        try:
            user_access = self.sheets_handler.get_user_access()
            user_info = user_access.get(chat_id)

            if not user_info:
                builder = self._build_keyboard([
                    [{"text": "🔄 Попробовать снова", "payload": "back_to_start"}]
                ])
                await event.message.answer(
                    text=f"Привет! У вас нет доступа к складам.\n"
                         f"Ваш Chat ID: {chat_id}\n\n"
                         f"Сообщите этот ID администратору "
                         f"для получения доступа.\n\n"
                         f"Если доступ был предоставлен, "
                         f"нажмите кнопку ниже:",
                    attachments=[builder.as_markup()],
                )
                return

            warehouses = user_info["warehouses"]
            cities = user_info["cities"]

            if len(cities) > 1:
                rows = []
                for city in cities:
                    rows.append([{"text": city, "payload": f"city_{city}"}])
                if len(warehouses) > 1:
                    rows.append([{"text": "📋 Все заказы", "payload": "view_all_orders"}])
                builder = self._build_keyboard(rows)
                await event.message.answer(
                    text="👋 Привет! Выберите город или просмотрите все заказы:",
                    attachments=[builder.as_markup()],
                )
            else:
                rows = []
                for warehouse in warehouses:
                    rows.append([{"text": warehouse, "payload": f"warehouse_{warehouse}"}])
                if len(warehouses) > 1:
                    rows.append([{"text": "📋 Все заказы", "payload": "view_all_orders"}])
                builder = self._build_keyboard(rows)
                await event.message.answer(
                    text="👋 Привет! Выберите склад или просмотрите все заказы:",
                    attachments=[builder.as_markup()],
                )
        except Exception as e:
            logger.error(f"Error in start command: {e}")
            builder = self._build_keyboard([
                [{"text": "🔄 Попробовать снова", "payload": "back_to_start"}]
            ])
            await event.message.answer(
                text="Произошла ошибка. Попробуйте позже.",
                attachments=[builder.as_markup()],
            )

    async def handle_plain_text(self, event: MessageCreated):
        """Reply when user sends text without /start — avoids 'silent' bot."""
        builder = self._build_keyboard([
            [{"text": "🔄 Открыть меню", "payload": "back_to_start"}]
        ])
        try:
            await event.message.answer(
                text=(
                    "Я работаю через кнопки под сообщениями.\n"
                    "Нажми «Старт» у бота или команду /start, "
                    "затем выбирай пункты меню.\n\n"
                    "Или нажми кнопку ниже:"
                ),
                attachments=[builder.as_markup()],
            )
        except Exception as e:
            logger.warning("handle_plain_text answer failed: %s", e)

    async def handle_callback(self, event: MessageCallback):
        """Route callback events based on payload prefix."""
        # MAX: acknowledge callback (POST /answers), else client may hang on buttons
        try:
            await self.bot.send_callback(
                callback_id=event.callback.callback_id,
            )
        except Exception as e:
            logger.warning("send_callback ack failed: %s", e)

        data = event.callback.payload
        if not data:
            return

        if data == "back_to_start":
            await self._handle_back_to_start(event)
        elif data.startswith("city_"):
            city = data[len("city_"):]
            await self._handle_city_selection(event, city)
        elif data.startswith("warehouse_"):
            warehouse = data[len("warehouse_"):]
            await self._handle_warehouse_selection(event, warehouse)
        elif data.startswith("supply_"):
            parts = data[len("supply_"):].split("|warehouse_")
            supply_id = parts[0]
            warehouse = parts[1] if len(parts) > 1 else None
            await self._handle_supply_selection(event, supply_id, warehouse)
        elif data.startswith("send_list_"):
            parts = data[len("send_list_"):].split("|warehouse_")
            supply_id = parts[0]
            warehouse = parts[1] if len(parts) > 1 else None
            await self._handle_send_list(event, supply_id, warehouse)
        elif data.startswith("send_pdf_"):
            parts = data[len("send_pdf_"):].split("|warehouse_")
            supply_id = parts[0]
            warehouse = parts[1] if len(parts) > 1 else None
            await self._handle_send_pdf(event, supply_id, warehouse)
        elif data.startswith("send_stickers_"):
            parts = data[len("send_stickers_"):].split("|warehouse_")
            supply_id = parts[0]
            warehouse = parts[1] if len(parts) > 1 else None
            await self._handle_send_stickers_pdf(event, supply_id, warehouse)
        elif data.startswith("order_"):
            order_id = data[len("order_"):]
            await self._handle_order_selection(event, order_id)
        elif data.startswith("complete_"):
            order_id = data[len("complete_"):]
            await self._handle_order_complete(event, order_id)
        elif data.startswith("back_to_warehouse_"):
            warehouse = data[len("back_to_warehouse_"):]
            await self._handle_warehouse_selection(event, warehouse)
        elif data.startswith("back_to_supplies_"):
            warehouse = data[len("back_to_supplies_"):]
            await self._handle_warehouse_selection(event, warehouse)
        elif data == "view_all_orders":
            await self._handle_view_all_orders(event)

    async def _handle_back_to_start(self, event: MessageCallback):
        chat_id = self._get_chat_id(event)
        try:
            user_access = self.sheets_handler.get_user_access()
            user_info = user_access.get(chat_id)

            if not user_info:
                builder = self._build_keyboard([
                    [{"text": "◀️ Назад", "payload": "back_to_start"}]
                ])
                await self._edit_or_send(event, "Ошибка: доступ не найден", builder)
                return

            warehouses = user_info["warehouses"]
            cities = user_info["cities"]

            if len(cities) > 1:
                rows = []
                for city in cities:
                    rows.append([{"text": city, "payload": f"city_{city}"}])
                if len(warehouses) > 1:
                    rows.append([{"text": "📋 Все заказы", "payload": "view_all_orders"}])
                builder = self._build_keyboard(rows)
                await self._edit_or_send(event, "👋 Привет! Выберите город или просмотрите все заказы:", builder)
            else:
                rows = []
                for warehouse in warehouses:
                    rows.append([{"text": warehouse, "payload": f"warehouse_{warehouse}"}])
                if len(warehouses) > 1:
                    rows.append([{"text": "📋 Все заказы", "payload": "view_all_orders"}])
                builder = self._build_keyboard(rows)
                await self._edit_or_send(event, "👋 Привет! Выберите склад или просмотрите все заказы:", builder)
        except Exception as e:
            logger.error(f"Error in back to start: {e}")
            await self._edit_or_send(event, "Произошла ошибка. Попробуйте позже.")

    async def _handle_city_selection(self, event: MessageCallback, city: str):
        chat_id = self._get_chat_id(event)
        user_access = self.sheets_handler.get_user_access()
        user_info = user_access.get(chat_id)

        if not user_info:
            builder = self._build_keyboard([
                [{"text": "◀️ Назад", "payload": "back_to_start"}]
            ])
            await self._edit_or_send(event, "Ошибка: доступ не найден", builder)
            return

        warehouse_api_keys = self.sheets_handler.get_warehouse_api_keys()
        city_warehouses = [
            w for w in user_info["warehouses"]
            for item in warehouse_api_keys
            if item["warehouse"] == w and item["city"] == city
        ]

        if not city_warehouses:
            builder = self._build_keyboard([
                [{"text": "◀️ Назад", "payload": "back_to_start"}]
            ])
            await self._edit_or_send(event, f"Нет складов в городе {city}", builder)
            return

        rows = []
        for warehouse in city_warehouses:
            rows.append([{"text": warehouse, "payload": f"warehouse_{warehouse}"}])
        rows.append([{"text": "◀️ Назад", "payload": "back_to_start"}])
        builder = self._build_keyboard(rows)
        await self._edit_or_send(event, f"Город: {city}\n\nВыберите склад:", builder)

    def _get_supply_handler_for_warehouse(self, warehouse: str) -> Optional[SupplyOrdersHandler]:
        try:
            warehouse_api_keys = self.sheets_handler.get_warehouse_api_keys()
            api_key = None
            for item in warehouse_api_keys:
                if item["warehouse"] == warehouse:
                    api_key = item["api_key"]
                    break
            if not api_key:
                logger.warning(f"No API key found for warehouse: {warehouse}")
                return None
            if api_key not in self.supply_handlers:
                self.supply_handlers[api_key] = SupplyOrdersHandler(
                    api_key=api_key,
                    sheets_handler=self.sheets_handler
                )
            return self.supply_handlers[api_key]
        except Exception as e:
            logger.error(f"Error getting supply handler for warehouse {warehouse}: {e}")
            return None

    async def _handle_warehouse_selection(self, event: MessageCallback, warehouse: str):
        chat_id = self._get_chat_id(event)
        try:
            await self._edit_or_send(event, f"📦 Склад: {warehouse}\n\n⏳ Загрузка поставок...")

            supply_handler = self._get_supply_handler_for_warehouse(warehouse)
            if not supply_handler:
                builder = self._build_keyboard([
                    [{"text": "◀️ Назад", "payload": "back_to_start"}]
                ])
                await self.bot.send_message(
                    chat_id=chat_id,
                    text=f"📦 Склад: {warehouse}\n\n❌ Ошибка: не найден API ключ для склада.",
                    attachments=[builder.as_markup()],
                )
                return

            logger.info(f"Starting to fetch incomplete supplies for warehouse: {warehouse}")
            try:
                supplies = supply_handler.fetch_all_incomplete_supplies(max_age_days=365)
                logger.info(f"Fetched {len(supplies)} incomplete supplies for warehouse {warehouse}")
            except Exception as e:
                logger.error(f"Error fetching supplies for warehouse {warehouse}: {e}", exc_info=True)
                builder = self._build_keyboard([
                    [{"text": "◀️ Назад", "payload": "back_to_start"}]
                ])
                await self.bot.send_message(
                    chat_id=chat_id,
                    text=f"📦 Склад: {warehouse}\n\n❌ Ошибка при загрузке поставок.\n\nОшибка: {str(e)}",
                    attachments=[builder.as_markup()],
                )
                return

            if not supplies:
                builder = self._build_keyboard([
                    [{"text": "◀️ Назад", "payload": "back_to_start"}]
                ])
                await self.bot.send_message(
                    chat_id=chat_id,
                    text=f"📦 Склад: {warehouse}\n\n✅ Нет незавершенных поставок за последние 365 дней.\n\n"
                         "Проверьте поставки на портале Wildberries.",
                    attachments=[builder.as_markup()],
                )
                return

            rows = []
            for supply in supplies[:50]:
                supply_id = supply.get("id", "")
                supply_name = supply.get("name", supply_id)
                created_str = supply.get("createdAt", "")

                try:
                    if created_str:
                        created_dt = datetime.fromisoformat(created_str.replace('Z', '+00:00'))
                        date_str = created_dt.strftime('%d.%m.%Y')
                    else:
                        date_str = ""
                except Exception:
                    date_str = ""

                button_text = f"📦 {supply_name}"
                if date_str:
                    button_text += f" ({date_str})"

                rows.append([{
                    "text": button_text,
                    "payload": f"supply_{supply_id}|warehouse_{warehouse}"
                }])

            rows.append([{"text": "◀️ Назад", "payload": "back_to_start"}])
            builder = self._build_keyboard(rows)

            await self.bot.send_message(
                chat_id=chat_id,
                text=f"📦 Склад: {warehouse}\n\n📋 Найдено незавершенных поставок: {len(supplies)}\n\n"
                     "Выберите поставку для просмотра заказов:",
                attachments=[builder.as_markup()],
            )

        except Exception as e:
            logger.error(f"Error showing supplies for warehouse {warehouse}: {e}")
            builder = self._build_keyboard([
                [{"text": "◀️ Назад", "payload": "back_to_start"}]
            ])
            try:
                await self.bot.send_message(
                    chat_id=chat_id,
                    text=f"❌ Ошибка при загрузке поставок для склада {warehouse}\n\nОшибка: {str(e)}",
                    attachments=[builder.as_markup()],
                )
            except Exception:
                pass

    async def _handle_supply_selection(self, event: MessageCallback, supply_id: str, warehouse: Optional[str] = None):
        chat_id = self._get_chat_id(event)
        try:
            await self._edit_or_send(event, f"📦 Поставка: {supply_id}\n\n⏳ Загрузка заказов...")

            if not warehouse:
                warehouse_api_keys = self.sheets_handler.get_warehouse_api_keys()
                for item in warehouse_api_keys:
                    warehouse = item["warehouse"]
                    break

            if not warehouse:
                builder = self._build_keyboard([
                    [{"text": "◀️ Назад", "payload": "back_to_start"}]
                ])
                await self.bot.send_message(
                    chat_id=chat_id, text="❌ Ошибка: не определен склад",
                    attachments=[builder.as_markup()],
                )
                return

            supply_handler = self._get_supply_handler_for_warehouse(warehouse)
            if not supply_handler:
                builder = self._build_keyboard([
                    [{"text": "◀️ Назад", "payload": "back_to_start"}]
                ])
                await self.bot.send_message(
                    chat_id=chat_id,
                    text=f"❌ Ошибка: не найден обработчик для склада {warehouse}",
                    attachments=[builder.as_markup()],
                )
                return

            order_ids = supply_handler.fetch_order_ids_for_supply(supply_id)

            if not order_ids:
                builder = self._build_keyboard([
                    [{"text": "◀️ Назад", "payload": "back_to_start"}]
                ])
                await self.bot.send_message(
                    chat_id=chat_id,
                    text=f"📦 Поставка: {supply_id}\n\n✅ В этой поставке нет заказов.",
                    attachments=[builder.as_markup()],
                )
                return

            logger.info(f"Found {len(order_ids)} orders in supply {supply_id}")

            builder = self._build_keyboard([
                [
                    {"text": "📄 PDF файл", "payload": f"send_pdf_{supply_id}|warehouse_{warehouse}"},
                    {"text": "📋 Список заказов", "payload": f"send_list_{supply_id}|warehouse_{warehouse}"},
                ],
                [
                    {"text": "🏷️ Стикеры PDF", "payload": f"send_stickers_{supply_id}|warehouse_{warehouse}"},
                ],
                [
                    {"text": "◀️ Назад", "payload": f"back_to_supplies_{warehouse}"},
                ],
            ])

            await self.bot.send_message(
                chat_id=chat_id,
                text=f"📦 Поставка: {supply_id}\n\n📋 Найдено заказов: {len(order_ids)}\n\nВыберите формат:",
                attachments=[builder.as_markup()],
            )

        except Exception as e:
            logger.error(f"Error showing supply selection menu: {e}")
            builder = self._build_keyboard([
                [{"text": "◀️ Назад", "payload": "back_to_start"}]
            ])
            try:
                await self.bot.send_message(
                    chat_id=chat_id,
                    text=f"❌ Ошибка при загрузке поставки {supply_id}\n\nОшибка: {str(e)}",
                    attachments=[builder.as_markup()],
                )
            except Exception:
                pass

    def _get_api_key_for_warehouse(self, warehouse: str) -> Optional[str]:
        warehouse_api_keys = self.sheets_handler.get_warehouse_api_keys()
        for item in warehouse_api_keys:
            if item["warehouse"] == warehouse:
                return item["api_key"]
        return None

    async def _handle_send_list(self, event: MessageCallback, supply_id: str, warehouse: str):
        chat_id = self._get_chat_id(event)
        try:
            await self._edit_or_send(event, f"📦 Поставка: {supply_id}\n\n⏳ Отправка списка заказов...")

            supply_handler = self._get_supply_handler_for_warehouse(warehouse)
            if not supply_handler:
                await self.bot.send_message(chat_id=chat_id, text="❌ Ошибка: обработчик не найден")
                return

            order_ids = supply_handler.fetch_order_ids_for_supply(supply_id)
            if not order_ids:
                await self.bot.send_message(
                    chat_id=chat_id,
                    text=f"📦 Поставка: {supply_id}\n\n✅ В этой поставке нет заказов.",
                )
                return

            date_from = datetime.now(timezone.utc) - timedelta(days=30)
            date_from_ts = int(date_from.timestamp())
            orders_map = supply_handler._fetch_orders_by_ids(order_ids, date_from_ts)

            if not orders_map:
                await self.bot.send_message(chat_id=chat_id, text="❌ Не удалось загрузить детали заказов.")
                return

            api_key = self._get_api_key_for_warehouse(warehouse)
            wb_api = WildberriesAPI(api_key) if api_key else None

            orders_list = []
            for order_id, order_data in orders_map.items():
                article = order_data.get("article", "")
                sku = order_data.get("skus", [""])[0] if order_data.get("skus") else ""
                article_for_sort = article or sku or ""
                sort_key = extract_article_number(article_for_sort)
                orders_list.append((sort_key, order_id, order_data))
            orders_list.sort(key=lambda x: x[0])

            all_stickers = {}
            if wb_api:
                all_order_ids = [order_id for _, order_id, _ in orders_list]
                batch_size = 100
                for i in range(0, len(all_order_ids), batch_size):
                    batch = all_order_ids[i:i + batch_size]
                    try:
                        batch_stickers = wb_api.get_stickers(batch)
                        all_stickers.update(batch_stickers)
                    except Exception as e:
                        logger.warning(f"Error fetching stickers for batch: {e}")

            logger.info("Loading products from Products sheet...")
            try:
                products_sheet = self.sheets_handler.spreadsheet.worksheet("Products")
                all_products_records = products_sheet.get_all_records()
                products_cache = {}
                for record in all_products_records:
                    vendor_code = str(record.get("Артикул продавца", "")).strip().lower()
                    if vendor_code:
                        products_cache[vendor_code] = {
                            'photo_url': str(record.get("Фото", "")).strip(),
                            'title': str(record.get("Наименование", "")).strip(),
                        }
            except Exception as e:
                logger.warning(f"Error loading products cache: {e}")
                products_cache = {}

            orders_to_send = []
            for idx, (sort_key, order_id, order_data) in enumerate(orders_list, 1):
                try:
                    article = order_data.get("article", "")
                    sku = order_data.get("skus", [""])[0] if order_data.get("skus") else ""

                    article_lower = article.strip().lower() if article else ""
                    product_info = products_cache.get(article_lower) if products_cache else None
                    if not product_info and products_cache:
                        product_info_dict = self.sheets_handler.get_product_from_sheet(article)
                        product_info = product_info_dict if product_info_dict else None

                    photo_url = product_info.get("photo_url") if product_info else None
                    product_name = product_info.get("title", "") if product_info else ""

                    sticker = all_stickers.get(order_id, "")
                    if not sticker:
                        sticker = "Нужно собрать!"

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
                await self.bot.send_message(chat_id=chat_id, text="❌ Не удалось подготовить заказы для отправки.")
                return

            orders_sent = 0
            for order in orders_to_send:
                try:
                    attachments = []
                    if order['photo_url']:
                        img = await self._image_bytes_from_url(order['photo_url'])
                        if img:
                            attachments.append(
                                InputMediaBuffer(img, filename="photo.jpg")
                            )

                    await self.bot.send_message(
                        chat_id=chat_id,
                        text=order['message_text'],
                        attachments=attachments if attachments else None,
                    )
                    orders_sent += 1
                except Exception as e:
                    logger.error(f"Failed to send order {order['order_id']}: {e}")
                await asyncio.sleep(0.1)

            try:
                orders_for_batch = []
                for order_data in orders_to_send:
                    orders_for_batch.append({
                        'order_id': order_data['order_id'],
                        'photo_url': order_data.get('photo_url') or "",
                        'product_name': order_data.get('product_name') or "",
                        'article': order_data.get('article') or "",
                        'sticker': order_data.get('sticker') or "Нужно собрать!",
                    })
                if orders_for_batch:
                    self.sheets_handler.add_orders_to_tasks_batch(orders_for_batch)
            except Exception as e:
                logger.error(f"Error adding orders to Tasks sheet in batch: {e}")

            builder = self._build_keyboard([
                [{"text": "◀️ Назад к поставкам", "payload": f"back_to_supplies_{warehouse}"}]
            ])
            await self.bot.send_message(
                chat_id=chat_id,
                text=f"📦 Поставка: {supply_id}\n\n✅ Отправлено заказов: {orders_sent} из {len(orders_to_send)}\n\n"
                     "Все заказы загружены ✅",
                attachments=[builder.as_markup()],
            )

        except Exception as e:
            import traceback
            logger.error(f"Error showing orders for supply {supply_id}: {e}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            builder = self._build_keyboard([
                [{"text": "◀️ Назад", "payload": "back_to_start"}]
            ])
            try:
                await self.bot.send_message(
                    chat_id=chat_id,
                    text=f"❌ Ошибка при загрузке заказов для поставки {supply_id}\n\nОшибка: {str(e)}",
                    attachments=[builder.as_markup()],
                )
            except Exception:
                pass

    async def _handle_send_pdf(self, event: MessageCallback, supply_id: str, warehouse: str):
        chat_id = self._get_chat_id(event)
        try:
            await self._edit_or_send(event, f"📦 Поставка: {supply_id}\n\n⏳ Генерация PDF файла...")

            supply_handler = self._get_supply_handler_for_warehouse(warehouse)
            if not supply_handler:
                builder = self._build_keyboard([
                    [{"text": "◀️ Назад", "payload": f"back_to_supplies_{warehouse}"}]
                ])
                await self.bot.send_message(
                    chat_id=chat_id,
                    text="❌ Ошибка: обработчик не найден",
                    attachments=[builder.as_markup()],
                )
                return

            order_ids = supply_handler.fetch_order_ids_for_supply(supply_id)
            if not order_ids:
                builder = self._build_keyboard([
                    [{"text": "◀️ Назад", "payload": f"back_to_supplies_{warehouse}"}]
                ])
                await self.bot.send_message(
                    chat_id=chat_id,
                    text="✅ В этой поставке нет заказов.",
                    attachments=[builder.as_markup()],
                )
                return

            date_from = datetime.now(timezone.utc) - timedelta(days=30)
            date_from_ts = int(date_from.timestamp())
            orders_map = supply_handler._fetch_orders_by_ids(order_ids, date_from_ts)

            if not orders_map:
                builder = self._build_keyboard([
                    [{"text": "◀️ Назад", "payload": f"back_to_supplies_{warehouse}"}]
                ])
                await self.bot.send_message(
                    chat_id=chat_id,
                    text="❌ Не удалось загрузить детали заказов.",
                    attachments=[builder.as_markup()],
                )
                return

            api_key = self._get_api_key_for_warehouse(warehouse)
            wb_api = WildberriesAPI(api_key) if api_key else None

            all_stickers = {}
            if wb_api:
                all_order_ids = list(orders_map.keys())
                batch_size = 100
                for i in range(0, len(all_order_ids), batch_size):
                    batch = all_order_ids[i:i + batch_size]
                    try:
                        batch_stickers = wb_api.get_stickers(batch)
                        all_stickers.update(batch_stickers)
                    except Exception as e:
                        logger.warning(f"Error fetching stickers for batch: {e}")

            tasks = []
            for order_id, order_data in orders_map.items():
                article = order_data.get("article", "")
                sku = order_data.get("skus", [""])[0] if order_data.get("skus") else ""
                product_info = self.sheets_handler.get_product_from_sheet(article)
                photo_url = product_info.get("photo_url") if product_info else None
                product_name = product_info.get("title", "") if product_info else ""
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

            if tasks:
                tasks.sort(key=lambda t: extract_article_number(t.get("article", "") or ""))

            if not tasks:
                builder = self._build_keyboard([
                    [{"text": "◀️ Назад", "payload": f"back_to_supplies_{warehouse}"}]
                ])
                await self.bot.send_message(
                    chat_id=chat_id,
                    text="❌ Нет данных для генерации PDF.",
                    attachments=[builder.as_markup()],
                )
                return

            try:
                self.sheets_handler.write_tasks_to_pdf_sheet(tasks)
            except Exception as e:
                logger.warning(f"Error writing to TasksForPDF sheet: {e}")

            pdf_generator = PDFGenerator()
            temp_dir = tempfile.mkdtemp()
            pdf_path = os.path.join(temp_dir, f"orders_{supply_id}.pdf")

            success = pdf_generator.generate_pdf_from_tasks(
                tasks=tasks,
                output_path=pdf_path,
                title=f"Заказы из поставки {supply_id}",
            )

            if not success or not os.path.exists(pdf_path):
                builder = self._build_keyboard([
                    [{"text": "◀️ Назад", "payload": f"back_to_supplies_{warehouse}"}]
                ])
                await self.bot.send_message(
                    chat_id=chat_id,
                    text="❌ Ошибка при генерации PDF файла.",
                    attachments=[builder.as_markup()],
                )
                return

            try:
                await self.bot.send_message(
                    chat_id=chat_id,
                    text=f"📄 PDF файл с заказами из поставки {supply_id}\n\nКоличество заказов: {len(tasks)}",
                    attachments=[InputMedia(path=pdf_path)],
                )

                builder = self._build_keyboard([
                    [{"text": "◀️ Назад к поставкам", "payload": f"back_to_supplies_{warehouse}"}]
                ])
                await self.bot.send_message(
                    chat_id=chat_id,
                    text=f"📦 Поставка: {supply_id}\n\n✅ PDF файл успешно отправлен!\n"
                         f"Количество заказов: {len(tasks)}",
                    attachments=[builder.as_markup()],
                )
            except Exception as e:
                logger.error(f"Error sending PDF file: {e}")
                builder = self._build_keyboard([
                    [{"text": "◀️ Назад", "payload": f"back_to_supplies_{warehouse}"}]
                ])
                await self.bot.send_message(
                    chat_id=chat_id,
                    text=f"❌ Ошибка при отправке PDF файла: {str(e)}",
                    attachments=[builder.as_markup()],
                )
            finally:
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
            builder = self._build_keyboard([
                [{"text": "◀️ Назад", "payload": f"back_to_supplies_{warehouse}"}]
            ])
            try:
                await self.bot.send_message(
                    chat_id=chat_id,
                    text=f"❌ Ошибка при генерации PDF для поставки {supply_id}\n\nОшибка: {str(e)}",
                    attachments=[builder.as_markup()],
                )
            except Exception:
                pass

    async def _handle_send_stickers_pdf(self, event: MessageCallback, supply_id: str, warehouse: str):
        """Handle sending PDF with sticker barcode images sorted by article/shelf."""
        chat_id = self._get_chat_id(event)
        try:
            await self._edit_or_send(event, f"📦 Поставка: {supply_id}\n\n⏳ Генерация PDF со стикерами...")

            supply_handler = self._get_supply_handler_for_warehouse(warehouse)
            if not supply_handler:
                builder = self._build_keyboard([
                    [{"text": "◀️ Назад", "payload": f"back_to_supplies_{warehouse}"}]
                ])
                await self.bot.send_message(
                    chat_id=chat_id,
                    text="❌ Ошибка: обработчик не найден",
                    attachments=[builder.as_markup()],
                )
                return

            order_ids = supply_handler.fetch_order_ids_for_supply(supply_id)
            if not order_ids:
                builder = self._build_keyboard([
                    [{"text": "◀️ Назад", "payload": f"back_to_supplies_{warehouse}"}]
                ])
                await self.bot.send_message(
                    chat_id=chat_id,
                    text="✅ В этой поставке нет заказов.",
                    attachments=[builder.as_markup()],
                )
                return

            date_from = datetime.now(timezone.utc) - timedelta(days=30)
            date_from_ts = int(date_from.timestamp())
            orders_map = supply_handler._fetch_orders_by_ids(order_ids, date_from_ts)

            if not orders_map:
                builder = self._build_keyboard([
                    [{"text": "◀️ Назад", "payload": f"back_to_supplies_{warehouse}"}]
                ])
                await self.bot.send_message(
                    chat_id=chat_id,
                    text="❌ Не удалось загрузить детали заказов.",
                    attachments=[builder.as_markup()],
                )
                return

            api_key = self._get_api_key_for_warehouse(warehouse)
            wb_api = WildberriesAPI(api_key) if api_key else None

            if not wb_api:
                builder = self._build_keyboard([
                    [{"text": "◀️ Назад", "payload": f"back_to_supplies_{warehouse}"}]
                ])
                await self.bot.send_message(
                    chat_id=chat_id,
                    text="❌ Ошибка: не найден API ключ для склада.",
                    attachments=[builder.as_markup()],
                )
                return

            all_order_ids = list(orders_map.keys())
            sticker_images = {}
            batch_size = 100
            for i in range(0, len(all_order_ids), batch_size):
                batch = all_order_ids[i:i + batch_size]
                try:
                    batch_images = wb_api.get_sticker_images(batch)
                    sticker_images.update(batch_images)
                except Exception as e:
                    logger.warning(f"Error fetching sticker images for batch: {e}")

            if not sticker_images:
                builder = self._build_keyboard([
                    [{"text": "◀️ Назад", "payload": f"back_to_supplies_{warehouse}"}]
                ])
                await self.bot.send_message(
                    chat_id=chat_id,
                    text="❌ Не удалось получить стикеры для заказов.",
                    attachments=[builder.as_markup()],
                )
                return

            sticker_data = []
            for order_id, order_data in orders_map.items():
                if order_id not in sticker_images:
                    continue
                article = order_data.get("article", "")
                sku = order_data.get("skus", [""])[0] if order_data.get("skus") else ""
                sticker_data.append({
                    "order_id": order_id,
                    "article": article or sku or "",
                    "sticker_image_bytes": sticker_images[order_id],
                })

            sticker_data.sort(key=lambda x: extract_article_number(x.get("article", "")))

            if not sticker_data:
                builder = self._build_keyboard([
                    [{"text": "◀️ Назад", "payload": f"back_to_supplies_{warehouse}"}]
                ])
                await self.bot.send_message(
                    chat_id=chat_id,
                    text="❌ Нет стикеров для генерации PDF.",
                    attachments=[builder.as_markup()],
                )
                return

            pdf_generator = PDFGenerator()
            temp_dir = tempfile.mkdtemp()
            pdf_path = os.path.join(temp_dir, f"stickers_{supply_id}.pdf")

            success = pdf_generator.generate_stickers_pdf(
                sticker_data=sticker_data,
                output_path=pdf_path,
                title=f"Стикеры поставки {supply_id}",
            )

            if not success or not os.path.exists(pdf_path):
                builder = self._build_keyboard([
                    [{"text": "◀️ Назад", "payload": f"back_to_supplies_{warehouse}"}]
                ])
                await self.bot.send_message(
                    chat_id=chat_id,
                    text="❌ Ошибка при генерации PDF со стикерами.",
                    attachments=[builder.as_markup()],
                )
                return

            try:
                await self.bot.send_message(
                    chat_id=chat_id,
                    text=f"🏷️ PDF со стикерами поставки {supply_id}\n\nКоличество стикеров: {len(sticker_data)}",
                    attachments=[InputMedia(path=pdf_path)],
                )
                builder = self._build_keyboard([
                    [{"text": "◀️ Назад к поставкам", "payload": f"back_to_supplies_{warehouse}"}]
                ])
                await self.bot.send_message(
                    chat_id=chat_id,
                    text=f"📦 Поставка: {supply_id}\n\n✅ Стикеры PDF успешно отправлены!\n"
                         f"Количество стикеров: {len(sticker_data)}",
                    attachments=[builder.as_markup()],
                )
            except Exception as e:
                logger.error(f"Error sending stickers PDF: {e}")
                builder = self._build_keyboard([
                    [{"text": "◀️ Назад", "payload": f"back_to_supplies_{warehouse}"}]
                ])
                await self.bot.send_message(
                    chat_id=chat_id,
                    text=f"❌ Ошибка при отправке PDF со стикерами: {str(e)}",
                    attachments=[builder.as_markup()],
                )
            finally:
                try:
                    if os.path.exists(pdf_path):
                        os.remove(pdf_path)
                    if os.path.exists(temp_dir):
                        os.rmdir(temp_dir)
                except Exception:
                    pass
                pdf_generator.cleanup()

        except Exception as e:
            logger.error(f"Error generating stickers PDF for supply {supply_id}: {e}")
            builder = self._build_keyboard([
                [{"text": "◀️ Назад", "payload": f"back_to_supplies_{warehouse}"}]
            ])
            try:
                await self.bot.send_message(
                    chat_id=chat_id,
                    text=f"❌ Ошибка при генерации стикеров для поставки {supply_id}\n\nОшибка: {str(e)}",
                    attachments=[builder.as_markup()],
                )
            except Exception:
                pass

    async def _handle_order_selection(self, event: MessageCallback, order_id: str):
        chat_id = self._get_chat_id(event)
        try:
            task = self.sheets_handler.get_task_by_order_id(order_id)
            if not task:
                await self.bot.send_message(
                    chat_id=chat_id,
                    text="Заказ не найден",
                )
                return

            warehouse = self._get_warehouse_for_order(order_id)

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

            rows = []
            if task.get('status', 'new') == 'new':
                rows.append([{"text": "✅ Отметить как выполненный", "payload": f"complete_{order_id}"}])
            if warehouse:
                rows.append([{"text": "◀️ Назад к списку", "payload": f"back_to_warehouse_{warehouse}"}])
            else:
                rows.append([{"text": "◀️ Назад", "payload": "back_to_start"}])
            builder = self._build_keyboard(rows)

            attachments = [builder.as_markup()]
            photo_url = task.get('photo_url', '').strip()
            if photo_url:
                img = await self._image_bytes_from_url(photo_url)
                if img:
                    attachments.append(
                        InputMediaBuffer(img, filename="photo.jpg")
                    )

            await self.bot.send_message(
                chat_id=chat_id,
                text=message_text,
                attachments=attachments,
            )

        except Exception as e:
            logger.error(f"Error showing order details: {e}")
            await self.bot.send_message(
                chat_id=chat_id,
                text="Ошибка при загрузке деталей заказа",
            )

    async def _handle_order_complete(self, event: MessageCallback, order_id: str):
        chat_id = self._get_chat_id(event)
        try:
            success = self.sheets_handler.update_order_status(order_id, "completed")
            if success:
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

                    warehouse = self._get_warehouse_for_order(order_id)
                    rows = []
                    if warehouse:
                        rows.append([{"text": "◀️ Назад к списку", "payload": f"back_to_warehouse_{warehouse}"}])
                    else:
                        rows.append([{"text": "◀️ Назад", "payload": "back_to_start"}])
                    builder = self._build_keyboard(rows)

                    await self._edit_or_send(event, message_text, builder)
                else:
                    await self._edit_or_send(event, "✅ Заказ отмечен как выполненный!")
            else:
                await self.bot.send_message(
                    chat_id=chat_id,
                    text="❌ Ошибка при обновлении статуса",
                )
        except Exception as e:
            logger.error(f"Error marking order as complete: {e}")
            await self.bot.send_message(
                chat_id=chat_id,
                text="❌ Ошибка при обновлении статуса",
            )

    async def _handle_view_all_orders(self, event: MessageCallback):
        try:
            tasks = self.sheets_handler.get_tasks_from_sheet(
                warehouse=None,
                limit=50,
                status_filter="new"
            )

            if not tasks:
                all_tasks = self.sheets_handler.get_tasks_from_sheet(
                    warehouse=None,
                    limit=50,
                    status_filter=None
                )

                if all_tasks:
                    rows = []
                    for i in range(0, min(len(all_tasks), 20), 2):
                        row = []
                        for task in all_tasks[i:i+2]:
                            oid = task['order_id']
                            icon = "🟢" if task.get('status', 'new') == 'new' else "✅"
                            row.append({"text": f"{icon} {oid}", "payload": f"order_{oid}"})
                        rows.append(row)
                    rows.append([{"text": "◀️ Назад", "payload": "back_to_start"}])
                    builder = self._build_keyboard(rows)

                    completed_count = sum(1 for t in all_tasks if t.get('status', 'new') != 'new')
                    new_count = len(all_tasks) - completed_count

                    await self._edit_or_send(
                        event,
                        "📋 Все заказы\n\n"
                        f"✅ Нет незавершенных заказов.\n"
                        f"📦 Всего заказов: {len(all_tasks)} "
                        f"(🟢 новых: {new_count}, ✅ завершенных: {completed_count})\n\n"
                        "Выберите заказ для просмотра:",
                        builder,
                    )
                else:
                    builder = self._build_keyboard([
                        [{"text": "◀️ Назад", "payload": "back_to_start"}]
                    ])
                    await self._edit_or_send(
                        event,
                        "📋 Все заказы\n\n✅ Нет заказов.\n\n"
                        "Бот будет автоматически отправлять вам уведомления о новых заказах.",
                        builder,
                    )
                return

            rows = []
            for i in range(0, len(tasks), 2):
                row = []
                for task in tasks[i:i+2]:
                    oid = task['order_id']
                    icon = "🟢" if task.get('status', 'new') == 'new' else "✅"
                    row.append({"text": f"{icon} {oid}", "payload": f"order_{oid}"})
                rows.append(row)
            rows.append([{"text": "◀️ Назад", "payload": "back_to_start"}])
            builder = self._build_keyboard(rows)

            await self._edit_or_send(
                event,
                f"📋 Все заказы\n\n📦 Найдено незавершенных: {len(tasks)}\n\n"
                "Выберите заказ для просмотра деталей:",
                builder,
            )

        except Exception as e:
            logger.error(f"Error showing all orders: {e}")
            builder = self._build_keyboard([
                [{"text": "◀️ Назад", "payload": "back_to_start"}]
            ])
            await self._edit_or_send(event, "❌ Ошибка при загрузке заказов", builder)
