"""
Headers for image HTTP GET. Ozon CDN (cdn1.ozone.ru) often returns 403 without
Referer / a real browser User-Agent.
"""
from typing import Dict


def image_request_headers(url: str) -> Dict[str, str]:
    url_l = (url or "").lower()
    headers: Dict[str, str] = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/122.0.0.0 Safari/537.36"
        ),
        "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
        "Accept-Language": "ru-RU,ru;q=0.9,en-US,en;q=0.8",
    }
    if "ozon.ru" in url_l or "ozone.ru" in url_l:
        headers["Referer"] = "https://www.ozon.ru/"
    elif any(
        x in url_l
        for x in ("wildberries.ru", "wbcontent.net", "wbbasket.ru", "wb.ru")
    ):
        headers["Referer"] = "https://www.wildberries.ru/"
    return headers
