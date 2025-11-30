# Telegram Bot for Wildberries DBS Orders

A Python Telegram bot that monitors Wildberries DBS orders, enriches them with sticker and photo data, records to Google Sheets, and sends notifications to authorized Telegram users.

## Features

- Polls Wildberries DBS API every 5 minutes for new orders
- Fetches order stickers and product photos
- Records orders to Google Sheets
- Sends formatted notifications to Telegram users based on warehouse access
- Tracks processed orders to avoid duplicates
- Handles API rate limits and errors gracefully

## Prerequisites

- Python 3.8+
- Telegram Bot Token (obtain from [@BotFather](https://t.me/BotFather))
- Google Service Account credentials JSON file
- Access to the configured Google Sheet

## Installation

1. Clone or download this repository

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Copy `.env.example` to `.env` and configure:
```bash
cp .env.example .env
```

4. Edit `.env` file with your configuration:
```
TELEGRAM_BOT_TOKEN=your_telegram_bot_token_here
GOOGLE_SHEETS_ID=your_google_sheet_id
GOOGLE_SERVICE_ACCOUNT_JSON=path_to_service_account.json
```

5. Ensure your Google Service Account has access to the Google Sheet

## Google Sheets Setup

The bot expects the following sheets in your Google Spreadsheet:

1. **WB** sheet: Contains cities, warehouse names, and API keys
   - Columns: Город | Название склада | API_KEY

2. **Access** sheet: Contains warehouse access permissions
   - Columns: Название склада | Chat_id

3. **Tasks** sheet: Will be created automatically for recording orders
   - Columns: № задания | Фото | Наименование | Артикул продавца | Стикер | Статус | Дата обработки

4. **ProcessedOrders** sheet: Will be created automatically for tracking processed order IDs
   - Columns: Order ID | Warehouse | API Key | Processed Date

## Running the Bot

### Development

```bash
python telegram_bot.py
```

### Docker

Build the Docker image:
```bash
docker build -t wb-telegram-bot .
```

Run the container:
```bash
docker run -d \
  --name wb-bot \
  --env-file .env \
  -v $(pwd)/tonal-concord-464913-u3-2024741e839c.json:/app/tonal-concord-464913-u3-2024741e839c.json:ro \
  wb-telegram-bot
```

## Usage

1. Start the bot
2. The bot will automatically poll Wildberries API every 5 minutes
3. When new orders are detected:
   - Order data is fetched (sticker, photo, name)
   - Data is recorded to Google Sheets
   - Notifications are sent to authorized Telegram users

## Project Structure

```
.
├── telegram_bot.py          # Main entry point
├── wb_api.py                # Wildberries API client
├── sheets_handler.py        # Google Sheets operations
├── telegram_handler.py      # Telegram bot logic
├── config.py                # Configuration management
├── order_tracker.py         # Processed orders tracking
├── requirements.txt         # Python dependencies
├── .env.example            # Environment variables template
├── README.md               # This file
└── tonal-concord-464913-u3-2024741e839c.json  # Google Service Account credentials
```

## Logging

Logs are written to `bot.log` by default. Set `LOG_LEVEL` in `.env` to control verbosity (DEBUG, INFO, WARNING, ERROR).

## Error Handling

The bot handles:
- API rate limits (429 responses) with exponential backoff
- Network errors with retry logic
- Missing data (incomplete orders are marked in Google Sheets)
- Photo fetch failures (automatic retry from product list)

## License

MIT

