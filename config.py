"""
Configuration management for Wildberries Bot
"""
import os
from pathlib import Path
from dotenv import load_dotenv

# Base directory (project root — same folder as config.py)
BASE_DIR = Path(__file__).parent.resolve()

# Load .env from project root so MAX_BOT_TOKEN is found even if cwd differs (e.g. systemd, nohup)
load_dotenv(BASE_DIR / ".env")

# Telegram Bot Configuration (legacy, kept for backward compatibility)
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")

# MAX Bot Configuration
MAX_BOT_TOKEN = os.getenv("MAX_BOT_TOKEN")
if not MAX_BOT_TOKEN:
    raise ValueError("MAX_BOT_TOKEN environment variable is required")

# Google Sheets Configuration
GOOGLE_SHEETS_ID = os.getenv("GOOGLE_SHEETS_ID", "1HpvprSmjgjPwcwVmiYReWEEpvwZ_vcTGnEpErCaAmhI")
GOOGLE_SERVICE_ACCOUNT_JSON = os.getenv(
    "GOOGLE_SERVICE_ACCOUNT_JSON",
    str(BASE_DIR / "tonal-concord-464913-u3-2024741e839c.json")
)

# Sheet names
SHEET_WB = "WB"  # Sheet with cities, warehouses, and API keys
SHEET_ACCESS = "Access"  # Sheet with warehouse access permissions
SHEET_TASKS = "Tasks"  # Sheet for recording new orders
SHEET_PROCESSED_ORDERS = "ProcessedOrders"  # Sheet for tracking processed order IDs
SHEET_PRODUCTS = "Products"  # Sheet for storing product list with vendorCode and photo URL
SHEET_TASKS_FOR_PDF = "TasksForPDF"  # Sheet for PDF generation with columns: Изображение, № задания, Фото URL, Наименование, Артикул продавца, Стикер

# Wildberries API Configuration
WB_MARKETPLACE_API_BASE = "https://marketplace-api.wildberries.ru"
WB_CONTENT_API_BASE = "https://content-api.wildberries.ru"

# Polling interval (in seconds)
POLLING_INTERVAL = 300  # 5 minutes

# API Rate Limiting
WB_API_RETRY_ATTEMPTS = 3
WB_API_RETRY_DELAY = 2  # seconds
WB_API_RATE_LIMIT_DELAY = 60  # seconds for 429 responses

# Logging
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LOG_FILE = os.getenv("LOG_FILE", "bot.log")
