"""
Test script for Wildberries /api/v3/orders endpoint
Tests pagination and order fetching

Usage:
    python test_orders_api.py

API Documentation:
    https://marketplace-api.wildberries.ru/api/v3/orders
    
Parameters:
    - limit: 1-1000, number of orders per request
    - next: pagination token (0 for first request)
    - dateFrom: Unix timestamp (optional)
    - dateTo: Unix timestamp (optional)
"""
import requests
import time
from typing import List, Dict, Optional
from datetime import datetime, timedelta

# Configuration
API_KEY = "eyJhbGciOiJFUzI1NiIsImtpZCI6IjIwMjUwOTA0djEiLCJ0eXAiOiJKV1QifQ.eyJlbnQiOjEsImV4cCI6MTc3Mzg1Nzc0NSwiaWQiOiIwMTk5NTY1MC05NTc0LTdhZTgtOGU1OC03YjI4ZmVhMzM4N2IiLCJpaWQiOjEzODQwMjg5Mywib2lkIjozOTc2NDUwLCJzIjo1OCwic2lkIjoiNGIwZTUzYjctODMwYi00YjEyLTgwNzAtMDczZmQ0MTk0MTcxIiwidCI6ZmFsc2UsInVpZCI6MTM4NDAyODkzfQ.7oGm3nS0wqFFMfTr6BFC4v1DE38h3ksTEyyx-1Y_30DBWNW9O-apMn2K29I-QXVQefbRvqOTmbHx9LqNYEaFJA"
BASE_URL = "https://marketplace-api.wildberries.ru/api/v3/orders"


def fetch_orders(
    limit: int = 1000,
    next_token: int = 0,
    date_from: Optional[int] = None,
    date_to: Optional[int] = None,
    api_key: str = API_KEY,
) -> Dict:
    """
    Fetch orders from Wildberries API
    
    Args:
        limit: Maximum number of orders to return (1-1000)
        next_token: Pagination token (0 for first request)
        date_from: Start date as Unix timestamp (optional)
        date_to: End date as Unix timestamp (optional)
        api_key: API key for authentication
        
    Returns:
        Dictionary with 'orders' list and 'next' token
    """
    url = BASE_URL
    
    params = {
        "limit": limit,
        "next": next_token,
    }
    
    if date_from:
        params["dateFrom"] = date_from
    
    if date_to:
        params["dateTo"] = date_to
    
    headers = {
        "Authorization": api_key,
        "Content-Type": "application/json",
    }
    
    try:
        response = requests.get(url, params=params, headers=headers, timeout=30)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"Error fetching orders: {e}")
        if hasattr(e.response, 'text'):
            print(f"Response: {e.response.text}")
        return {}


def fetch_all_orders(
    limit: int = 1000,
    date_from: Optional[int] = None,
    date_to: Optional[int] = None,
    api_key: str = API_KEY,
    max_requests: int = 100,
) -> List[Dict]:
    """
    Fetch all orders using pagination
    
    Args:
        limit: Maximum number of orders per request (1-1000)
        date_from: Start date as Unix timestamp (optional)
        date_to: End date as Unix timestamp (optional)
        api_key: API key for authentication
        max_requests: Maximum number of requests to prevent infinite loops
        
    Returns:
        List of all order dictionaries
    """
    all_orders = []
    next_token = 0
    request_count = 0
    
    print(f"Starting to fetch orders (limit={limit} per request)...")
    
    while request_count < max_requests:
        print(f"\nRequest #{request_count + 1}: Fetching with next={next_token}")
        
        result = fetch_orders(
            limit=limit,
            next_token=next_token,
            date_from=date_from,
            date_to=date_to,
            api_key=api_key,
        )
        
        if not result:
            print("Failed to fetch orders, stopping")
            break
        
        orders = result.get("orders", [])
        next_token = result.get("next")
        
        print(f"  Received {len(orders)} orders")
        
        if orders:
            all_orders.extend(orders)
            print(f"  Total orders collected: {len(all_orders)}")
        else:
            print("  No more orders found")
            break
        
        # Check if we should continue pagination
        if not next_token or next_token == 0:
            print("  No next token, all orders fetched")
            break
        
        request_count += 1
        
        # Small delay to avoid rate limiting
        time.sleep(0.5)
    
    print(f"\n=== Finished fetching orders ===")
    print(f"Total orders collected: {len(all_orders)}")
    print(f"Total requests made: {request_count + 1}")
    
    return all_orders


def datetime_to_timestamp(dt: datetime) -> int:
    """Convert datetime to Unix timestamp"""
    return int(dt.timestamp())


def timestamp_to_datetime(ts: int) -> datetime:
    """Convert Unix timestamp to datetime"""
    return datetime.fromtimestamp(ts)


def main():
    """Main function to test the API"""
    
    print("=" * 60)
    print("Wildberries /api/v3/orders API Test")
    print("=" * 60)
    
    # Option 1: Fetch single page
    print("\n" + "=" * 60)
    print("Test 1: Fetch first page (limit=100, next=0)")
    print("=" * 60)
    
    result = fetch_orders(limit=100, next_token=0)
    
    if result:
        orders = result.get("orders", [])
        next_token = result.get("next")
        print(f"\nReceived {len(orders)} orders")
        print(f"Next token: {next_token}")
        
        if orders:
            print("\nFirst order sample:")
            first_order = orders[0]
            print(f"  Order ID: {first_order.get('id')}")
            print(f"  Article: {first_order.get('article')}")
            print(f"  Created: {first_order.get('createdAt')}")
            print(f"  Warehouse ID: {first_order.get('warehouseId')}")
            print(f"  Delivery Type: {first_order.get('deliveryType')}")
    
    # Option 2: Fetch with date range (last 7 days)
    print("\n" + "=" * 60)
    print("Test 2: Fetch orders from last 7 days")
    print("=" * 60)
    
    date_to = datetime.now()
    date_from = date_to - timedelta(days=7)
    
    date_from_ts = datetime_to_timestamp(date_from)
    date_to_ts = datetime_to_timestamp(date_to)
    
    print(f"Date range: {date_from.strftime('%Y-%m-%d')} to {date_to.strftime('%Y-%m-%d')}")
    print(f"Unix timestamps: {date_from_ts} to {date_to_ts}")
    
    result = fetch_orders(
        limit=100,
        next_token=0,
        date_from=date_from_ts,
        date_to=date_to_ts,
    )
    
    if result:
        orders = result.get("orders", [])
        print(f"\nReceived {len(orders)} orders in date range")
    
    # Option 3: Fetch all orders (with pagination)
    print("\n" + "=" * 60)
    print("Test 3: Fetch all orders with pagination")
    print("=" * 60)
    print("(This may take a while and make multiple requests)")
    
    # Uncomment to fetch all orders
    # all_orders = fetch_all_orders(limit=1000, max_requests=10)
    # if all_orders:
    #     print(f"\nSample order IDs: {[o.get('id') for o in all_orders[:5]]}")
    #     print(f"Total unique orders: {len(set(o.get('id') for o in all_orders))}")
    
    # Option 4: Test pagination manually
    print("\n" + "=" * 60)
    print("Test 4: Manual pagination example")
    print("=" * 60)
    
    next_token = 0
    for page in range(2):  # Fetch first 2 pages
        print(f"\nPage {page + 1}:")
        result = fetch_orders(limit=10, next_token=next_token)
        if result:
            orders = result.get("orders", [])
            next_token = result.get("next")
            print(f"  Orders: {len(orders)}")
            print(f"  Next token: {next_token}")
            if orders:
                print(f"  Order IDs: {[o.get('id') for o in orders]}")
        if not next_token:
            break
    
    print("\n" + "=" * 60)
    print("Test completed!")
    print("=" * 60)


if __name__ == "__main__":
    main()
