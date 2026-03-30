#!/usr/bin/env python3
"""
Download product photos from the Products sheet («Фото») into a local cache
keyed by «Артикул продавца». The bot reads these files first (Ozon timeouts).

Cron example (daily 03:30):

  30 3 * * * cd /app/WB_tg_bot_supplies && \\
    ./venv/bin/python3 sync_product_images.py >>/var/log/sync_img.log 2>&1

Uses same env as the bot: GOOGLE_SHEETS_ID, GOOGLE_SERVICE_ACCOUNT_JSON,
optional PRODUCT_IMAGE_CACHE_DIR.
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from typing import Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from config import LOG_FILE, LOG_LEVEL, PRODUCT_IMAGE_CACHE_DIR
from image_download_headers import image_request_headers
from product_image_cache import cache_path_for_article, write_cached_image
from sheets_handler import SheetsHandler

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=getattr(logging, LOG_LEVEL.upper(), logging.INFO),
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger(__name__)


def _session() -> requests.Session:
    s = requests.Session()
    retries = Retry(
        total=5,
        backoff_factor=2,
        status_forcelist=(502, 503, 504),
        allowed_methods=("GET", "HEAD"),
    )
    adapter = HTTPAdapter(max_retries=retries)
    s.mount("https://", adapter)
    s.mount("http://", adapter)
    return s


def _download(
    session: requests.Session, url: str, connect_s: int, read_s: int
) -> Optional[bytes]:
    try:
        r = session.get(
            url,
            timeout=(connect_s, read_s),
            headers=image_request_headers(url),
        )
        if r.status_code == 200 and r.content:
            return r.content
        logger.warning("HTTP %s for %s", r.status_code, url[:120])
    except requests.RequestException as e:
        logger.warning("download failed %s: %s", url[:120], e)
    return None


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Sync Products «Фото» URLs to local JPEG cache.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        metavar="N",
        help=(
            "Backward-compatible alias for --max-attempts. "
            "Process at most N candidate rows (0 = no limit)."
        ),
    )
    parser.add_argument(
        "--target-success",
        type=int,
        default=0,
        metavar="N",
        help="Stop after saving N images (0 = no target).",
    )
    parser.add_argument(
        "--max-attempts",
        type=int,
        default=0,
        metavar="N",
        help="Process at most N candidate rows (0 = no limit).",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-download even if file exists and is fresh.",
    )
    parser.add_argument(
        "--max-age-days",
        type=int,
        default=7,
        metavar="N",
        help=(
            "Skip files newer than N days (unless --force). Default: 7. "
            "Use 0 to refresh all existing files."
        ),
    )
    parser.add_argument(
        "--connect-timeout",
        type=int,
        default=20,
        help="Connect timeout seconds (default 20).",
    )
    parser.add_argument(
        "--read-timeout",
        type=int,
        default=120,
        help="Read timeout seconds (default 120).",
    )
    parser.add_argument(
        "--pause",
        type=float,
        default=0.2,
        help="Seconds to sleep between downloads (default 0.2).",
    )
    args = parser.parse_args()

    PRODUCT_IMAGE_CACHE_DIR.mkdir(parents=True, exist_ok=True)

    sheets = SheetsHandler()
    products = sheets.spreadsheet.worksheet("Products")
    records = products.get_all_records()

    now = time.time()
    max_age = max(0, args.max_age_days) * 86400

    session = _session()
    ok = skip = fail = 0

    attempts = 0
    for rec in records:
        article = str(rec.get("Артикул продавца", "")).strip()
        url = str(rec.get("Фото", "")).strip()
        if not article or not url:
            continue

        # limits (limit is kept for backward compatibility)
        max_attempts = args.max_attempts or args.limit
        if max_attempts and attempts >= max_attempts:
            break

        path = cache_path_for_article(article)
        if path.is_file() and not args.force:
            age_s = now - path.stat().st_mtime
            if args.max_age_days > 0 and age_s < max_age:
                skip += 1
                continue

        attempts += 1
        data = _download(session, url, args.connect_timeout, args.read_timeout)
        if data and write_cached_image(article, data):
            ok += 1
            logger.info("saved %s -> %s", article, str(path))
            if args.target_success and ok >= args.target_success:
                break
        else:
            fail += 1
            logger.warning("failed %s (%s)", article, url[:160])

        if args.pause > 0:
            time.sleep(args.pause)

    logger.info(
        "sync_product_images: written=%s skipped=%s failed=%s",
        ok,
        skip,
        fail,
    )
    if args.target_success:
        return 0 if ok >= args.target_success else 1
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
