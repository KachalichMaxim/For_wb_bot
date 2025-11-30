"""
Wildberries API Client
Handles all API calls to Wildberries services
"""
import time
import logging
import requests
from typing import List, Dict, Optional, Tuple
from config import (
    WB_MARKETPLACE_API_BASE,
    WB_CONTENT_API_BASE,
    WB_API_RETRY_ATTEMPTS,
    WB_API_RETRY_DELAY,
    WB_API_RATE_LIMIT_DELAY,
)

logger = logging.getLogger(__name__)


class WildberriesAPI:
    """Client for Wildberries API operations"""

    def __init__(self, api_key: str):
        """
        Initialize Wildberries API client
        
        Args:
            api_key: Wildberries API key for authentication
        """
        self.api_key = api_key
        self.marketplace_session = requests.Session()
        self.content_session = requests.Session()
        
        # Set headers for marketplace API
        self.marketplace_session.headers.update({
            "Authorization": api_key,
            "Content-Type": "application/json",
        })
        
        # Set headers for content API
        self.content_session.headers.update({
            "Authorization": api_key,
            "Content-Type": "application/json",
        })
        
        # Product cache: maps article (vendorCode) to product data
        self.product_cache: Dict[str, Dict] = {}
        self.cache_loaded = False

    def _handle_rate_limit(self, response: requests.Response) -> bool:
        """
        Handle rate limit responses
        
        Args:
            response: HTTP response object
            
        Returns:
            True if rate limited, False otherwise
        """
        if response.status_code == 429:
            logger.warning(f"Rate limit exceeded. Waiting {WB_API_RATE_LIMIT_DELAY} seconds...")
            time.sleep(WB_API_RATE_LIMIT_DELAY)
            return True
        return False

    def _make_request(
        self,
        session: requests.Session,
        method: str,
        url: str,
        data: Optional[Dict] = None,
        params: Optional[Dict] = None,
        max_retries: int = WB_API_RETRY_ATTEMPTS,
    ) -> Optional[requests.Response]:
        """
        Make HTTP request with retry logic and rate limit handling
        
        Args:
            session: Requests session object
            method: HTTP method (GET, POST, etc.)
            url: Request URL
            data: Request payload (for POST requests)
            params: Query parameters (for GET requests)
            max_retries: Maximum number of retry attempts
            
        Returns:
            Response object or None if all retries failed
        """
        for attempt in range(max_retries):
            try:
                if method.upper() == "GET":
                    response = session.get(url, params=params, timeout=30)
                elif method.upper() == "POST":
                    response = session.post(url, json=data, params=params, timeout=30)
                else:
                    logger.error(f"Unsupported HTTP method: {method}")
                    return None

                # Handle rate limiting
                if self._handle_rate_limit(response):
                    continue  # Retry after rate limit delay

                # Handle successful response
                if response.status_code == 200:
                    return response

                # Handle other errors
                if response.status_code == 401:
                    logger.error("Authentication failed. Invalid API key.")
                    return None
                elif response.status_code == 403:
                    logger.error("Access forbidden. Check API key permissions.")
                    return None
                else:
                    logger.warning(
                        f"API request failed with status {response.status_code}. "
                        f"Attempt {attempt + 1}/{max_retries}"
                    )
                    if attempt < max_retries - 1:
                        time.sleep(WB_API_RETRY_DELAY * (attempt + 1))  # Exponential backoff
                        continue

            except requests.exceptions.RequestException as e:
                logger.error(f"Request error on attempt {attempt + 1}/{max_retries}: {e}")
                if attempt < max_retries - 1:
                    time.sleep(WB_API_RETRY_DELAY * (attempt + 1))
                    continue

        logger.error(f"All {max_retries} attempts failed for {url}")
        return None

    def get_new_orders(self) -> List[Dict]:
        """
        Fetch new orders from Wildberries API (both DBS and FBS)
        
        Returns:
            List of order dictionaries or empty list on error
        """
        url = f"{WB_MARKETPLACE_API_BASE}/api/v3/orders/new"
        logger.info("Fetching new orders...")
        
        response = self._make_request(self.marketplace_session, "GET", url)
        
        if not response:
            logger.error("Failed to fetch new orders")
            return []
        
        try:
            data = response.json()
            orders = data.get("orders", [])
            logger.info(f"Successfully fetched {len(orders)} new orders")
            return orders
        except Exception as e:
            logger.error(f"Error parsing orders response: {e}")
            return []

    def get_stickers(
        self,
        order_ids: List[int],
        sticker_type: str = "svg",
        width: int = 58,
        height: int = 40,
    ) -> Dict[int, str]:
        """
        Fetch stickers for given order IDs
        
        Args:
            order_ids: List of order IDs to get stickers for
            sticker_type: Type of sticker (svg, zplv, zplh, png)
            width: Sticker width
            height: Sticker height
            
        Returns:
            Dictionary mapping order_id to sticker string (partA + partB)
        """
        if not order_ids:
            return {}
        
        url = f"{WB_MARKETPLACE_API_BASE}/api/v3/orders/stickers"
        params = {
            "type": sticker_type,
            "width": width,
            "height": height,
        }
        data = {"orders": order_ids}
        
        logger.info(f"Fetching stickers for {len(order_ids)} orders...")
        
        response = self._make_request(
            self.marketplace_session, "POST", url, data=data, params=params
        )
        
        if not response:
            logger.error("Failed to fetch stickers")
            return {}
        
        try:
            data = response.json()
            stickers_data = data.get("stickers", [])
            
            if not stickers_data:
                logger.warning(
                    f"No stickers returned for orders {order_ids}. "
                    "Orders may need to be confirmed first."
                )
                return {}
            
            result = {}
            for sticker in stickers_data:
                order_id = sticker.get("orderId")
                part_a = sticker.get("partA", "")
                part_b = sticker.get("partB", "")
                sticker_str = f"{part_a} {part_b}".strip()
                if sticker_str:
                    result[order_id] = sticker_str
            
            logger.info(f"Successfully fetched {len(result)} stickers")
            return result
        except Exception as e:
            logger.error(f"Error parsing stickers response: {e}")
            return {}

    def get_product_cards(
        self,
        nm_ids: Optional[List[int]] = None,
        articles: Optional[List[str]] = None,
        cursor: Optional[Dict] = None,
        max_pages: int = 10,
    ) -> Tuple[Dict[str, Dict], Optional[Dict]]:
        """
        Fetch product cards from Wildberries Content API
        Can search by nmId, article (vendorCode), or both
        
        Args:
            nm_ids: Optional list of product IDs (nmId)
            articles: Optional list of articles (vendorCode)
            cursor: Cursor for pagination (None for first request)
            max_pages: Maximum number of pages to fetch
            
        Returns:
            Tuple of (product_dict, next_cursor) where:
            - product_dict maps identifier (nmId or article) to product data
            - next_cursor is cursor for next page or None
        """
        url = f"{WB_CONTENT_API_BASE}/content/v2/get/cards/list"
        
        result = {}
        current_cursor = cursor
        pages_fetched = 0
        
        # Track what we're looking for
        looking_for_nm_ids = set(nm_ids) if nm_ids else set()
        looking_for_articles = set(str(a).strip().lower() for a in articles) if articles else set()
        
        while pages_fetched < max_pages:
            # Prepare request payload
            settings = {
                "cursor": current_cursor if current_cursor else {"limit": 100},
                "filter": {"withPhoto": -1},
            }
            
            data = {"settings": settings}
            
            logger.debug(f"Fetching product cards page {pages_fetched + 1}...")
            
            response = self._make_request(self.content_session, "POST", url, data=data)
            
            if not response:
                logger.error("Failed to fetch product cards")
                break
            
            try:
                response_data = response.json()
                cards = response_data.get("cards", [])
                next_cursor = response_data.get("cursor")
                
                if not cards:
                    logger.debug("No more cards to fetch")
                    break
                
                # Process cards
                for card in cards:
                    card_nm_id = card.get("nmID")
                    card_vendor_code = str(card.get("vendorCode", "")).strip().lower()
                    
                    # Extract photo URLs and product name
                    photos = card.get("photos", [])
                    photo_url = None
                    if photos and len(photos) > 0:
                        # Prefer big image, fallback to first available
                        photo_url = (
                            photos[0].get("big") or
                            photos[0].get("c516x688") or
                            photos[0].get("c246x328") or
                            photos[0].get("square")
                        )
                    
                    product_data = {
                        "title": card.get("title", ""),
                        "photo_url": photo_url,
                        "article": card.get("vendorCode", ""),
                        "nm_id": card_nm_id,
                    }
                    
                    # Match by nmId
                    if card_nm_id and card_nm_id in looking_for_nm_ids:
                        result[str(card_nm_id)] = product_data
                        looking_for_nm_ids.discard(card_nm_id)
                    
                    # Match by article (vendorCode)
                    if card_vendor_code and card_vendor_code in looking_for_articles:
                        result[card_vendor_code] = product_data
                        looking_for_articles.discard(card_vendor_code)
                
                # Check if we found everything
                if not looking_for_nm_ids and not looking_for_articles:
                    logger.debug("Found all requested products")
                    break
                
                # Check if there's a next page
                if not next_cursor:
                    logger.debug("No more pages available")
                    break
                
                current_cursor = next_cursor
                pages_fetched += 1
                
            except Exception as e:
                logger.error(f"Error parsing product cards response: {e}")
                break
        
        logger.info(
            f"Fetched {len(result)} product cards from {pages_fetched + 1} pages"
        )
        return result, current_cursor

    def get_product_by_nm_id(self, nm_id: int) -> Optional[Dict]:
        """
        Fetch a single product card by nmId
        
        Args:
            nm_id: Product ID (nmId)
            
        Returns:
            Product dictionary with title, photo_url, article or None on error
        """
        products, _ = self.get_product_cards(nm_ids=[nm_id])
        return products.get(str(nm_id))

    def load_product_cache(self, max_pages: int = 50) -> Dict[str, Dict]:
        """
        Load all products into cache, indexed by article (vendorCode)
        
        Args:
            max_pages: Maximum number of pages to fetch (default 50)
            
        Returns:
            Dictionary mapping article (vendorCode) to product data
        """
        if self.cache_loaded:
            logger.debug("Product cache already loaded")
            return self.product_cache
        
        logger.info("Loading product list into cache...")
        url = f"{WB_CONTENT_API_BASE}/content/v2/get/cards/list"
        
        current_cursor = None
        pages_fetched = 0
        total_products = 0
        
        while pages_fetched < max_pages:
            settings = {
                "cursor": current_cursor if current_cursor else {"limit": 100},
                "filter": {"withPhoto": -1},
            }
            
            data = {"settings": settings}
            
            logger.debug(f"Fetching product cards page {pages_fetched + 1}...")
            
            response = self._make_request(self.content_session, "POST", url, data=data)
            
            if not response:
                logger.error(f"Failed to fetch product cards at page {pages_fetched + 1}")
                break
            
            try:
                response_data = response.json()
                cards = response_data.get("cards", [])
                next_cursor = response_data.get("cursor")
                
                if not cards:
                    logger.debug("No more cards to fetch")
                    break
                
                # Process and cache all cards
                for card in cards:
                    card_vendor_code = str(card.get("vendorCode", "")).strip()
                    if not card_vendor_code:
                        continue
                    
                    # Extract photo URLs
                    photos = card.get("photos", [])
                    photo_url = None
                    if photos and len(photos) > 0:
                        photo_url = (
                            photos[0].get("big") or
                            photos[0].get("c516x688") or
                            photos[0].get("c246x328") or
                            photos[0].get("square")
                        )
                    
                    product_data = {
                        "title": card.get("title", ""),
                        "photo_url": photo_url,
                        "article": card_vendor_code,
                        "nm_id": card.get("nmID"),
                    }
                    
                    # Cache by article (case-insensitive)
                    self.product_cache[card_vendor_code.lower()] = product_data
                    total_products += 1
                
                logger.debug(f"Loaded {len(cards)} products from page {pages_fetched + 1}")
                
                # Check if there's a next page
                if not next_cursor:
                    logger.debug("No more pages available")
                    break
                
                current_cursor = next_cursor
                pages_fetched += 1
                
            except Exception as e:
                logger.error(f"Error parsing product cards response: {e}")
                break
        
        self.cache_loaded = True
        logger.info(
            f"Product cache loaded: {total_products} products from {pages_fetched + 1} pages"
        )
        return self.product_cache

    def get_product_by_article(self, article: str, use_cache: bool = True) -> Optional[Dict]:
        """
        Fetch a single product card by article (vendorCode)
        
        Args:
            article: Seller article (vendorCode)
            use_cache: Whether to use cached products (default True)
            
        Returns:
            Product dictionary with title, photo_url, article or None on error
        """
        if not article:
            return None
        
        article_lower = str(article).strip().lower()
        
        # Try cache first
        if use_cache:
            if not self.cache_loaded:
                self.load_product_cache()
            
            cached_product = self.product_cache.get(article_lower)
            if cached_product:
                logger.debug(f"Found product in cache for article '{article}'")
                return cached_product
        
        # Fallback to API search
        logger.debug(f"Product not in cache, searching API for article '{article}'")
        products, _ = self.get_product_cards(articles=[article])
        result = products.get(article_lower)
        
        # Add to cache if found
        if result and use_cache:
            self.product_cache[article_lower] = result
        
        return result

