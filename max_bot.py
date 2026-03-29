"""
Main MAX Bot for Wildberries DBS Orders
Uses maxapi library for MAX messenger integration
"""
import asyncio
import logging

from maxapi import Bot, Dispatcher
from maxapi.types import (
    BotStarted,
    MessageCreated,
    MessageCallback,
    Command,
    BotCommand,
)

# Fix maxapi library bug: ChatButton.chat_title is required, which causes
# Pydantic 2 union deserialization to crash when parsing callback buttons
# from API responses. Making it optional lets the union resolution work.
from maxapi.types.attachments.buttons.chat_button import ChatButton as _ChatButton
_ChatButton.model_fields["chat_title"].default = None
_ChatButton.model_rebuild(force=True)

from maxapi.types.attachments.attachment import ButtonsPayload as _BP
_BP.model_rebuild(force=True)

from maxapi.types.attachments.attachment import Attachment as _Att
_Att.model_rebuild(force=True)

from config import MAX_BOT_TOKEN, LOG_LEVEL, LOG_FILE
from sheets_handler import SheetsHandler
from max_handler import MaxHandler

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=getattr(logging, LOG_LEVEL.upper(), logging.INFO),
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler(),
    ],
)

logger = logging.getLogger(__name__)

bot = Bot(token=MAX_BOT_TOKEN)
dp = Dispatcher()

sheets_handler = SheetsHandler()
handler = MaxHandler(sheets_handler=sheets_handler, bot=bot)


@dp.bot_started()
async def on_bot_started(event: BotStarted):
    await handler.handle_bot_started(event)


@dp.message_created(Command('start'))
async def on_start_command(event: MessageCreated):
    await handler.handle_start_command(event)


@dp.message_created()
async def on_plain_text(event: MessageCreated):
    await handler.handle_plain_text(event)


@dp.message_callback()
async def on_callback(event: MessageCallback):
    await handler.handle_callback(event)


async def main():
    logger.info("Starting Wildberries DBS Orders MAX Bot...")
    try:
        await bot.set_my_commands(
            BotCommand(name='/start', description='Запустить бота'),
        )
    except Exception as e:
        logger.warning(f"Could not set bot commands: {e}")

    logger.info("Bot is running. Press Ctrl+C to stop.")
    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        raise
