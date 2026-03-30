"""
Configuration management for Wildberries Bot
"""
import os
from pathlib import Path
from dotenv import load_dotenv

# Base directory (project root — same folder as config.py)
BASE_DIR = Path(__file__).parent.resolve()

# Load .env from project root (cwd-independent: systemd, nohup, etc.)
_ENV_FILE = BASE_DIR / ".env"
_DOTENV_LOADED = load_dotenv(_ENV_FILE)

# Telegram Bot Configuration (legacy, kept for backward compatibility)
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")

# MAX Bot Configuration
# Prefer .env. Fallback only on server if needed — do not commit a real token to git.
_MAX_BOT_TOKEN_FALLBACK = ""

MAX_BOT_TOKEN = (
    (os.getenv("MAX_BOT_TOKEN") or _MAX_BOT_TOKEN_FALLBACK or "").strip()
)
if not MAX_BOT_TOKEN:
    raise ValueError(
        "MAX_BOT_TOKEN is missing or empty. "
        f"Add to {_ENV_FILE}: MAX_BOT_TOKEN=<token>. "
        f"file_exists={_ENV_FILE.is_file()} dotenv_ok={_DOTENV_LOADED}. "
        "Or: export MAX_BOT_TOKEN=... before python3 max_bot.py"
    )

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

# Local product photo cache (see sync_product_images.py)
_product_img_cache = os.getenv("PRODUCT_IMAGE_CACHE_DIR", "").strip()
PRODUCT_IMAGE_CACHE_DIR = (
    Path(_product_img_cache).resolve()
    if _product_img_cache
    else (BASE_DIR / "data" / "product_images")
)
PRODUCT_IMAGE_HTTP_TIMEOUT = int(os.getenv("PRODUCT_IMAGE_HTTP_TIMEOUT", "90"))
PRODUCT_IMAGE_HTTP_RETRIES = int(os.getenv("PRODUCT_IMAGE_HTTP_RETRIES", "3"))
