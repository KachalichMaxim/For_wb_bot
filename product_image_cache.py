"""
Local JPEG cache keyed by vendor article (Артикул продавца).
Used by max_handler and pdf_generator; filled by sync_product_images.py (cron).
"""
import hashlib
import logging
import re
from pathlib import Path
from typing import Optional

from config import PRODUCT_IMAGE_CACHE_DIR

logger = logging.getLogger(__name__)


def article_cache_stem(article: str) -> str:
    key = str(article or "").strip().lower()
    if not key:
        return "unknown"
    safe = re.sub(r"[^0-9a-zа-яё.\-_]+", "_", key, flags=re.IGNORECASE)
    safe = safe.strip("._")[:150]
    if not safe:
        return hashlib.sha256(key.encode("utf-8")).hexdigest()[:24]
    return safe


def cache_path_for_article(article: str) -> Path:
    return PRODUCT_IMAGE_CACHE_DIR / f"{article_cache_stem(article)}.jpg"


def read_cached_image(article: str) -> Optional[bytes]:
    p = cache_path_for_article(article)
    if not p.is_file():
        return None
    try:
        return p.read_bytes()
    except OSError as e:
        logger.warning("read_cached_image %s: %s", p, e)
        return None


def write_cached_image(article: str, data: bytes) -> bool:
    p = cache_path_for_article(article)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        return True
    except OSError as e:
        logger.warning("write_cached_image %s: %s", p, e)
        return False
