"""
Test script to verify article number extraction and sorting
"""
import re

def extract_article_number(article: str) -> int:
    """
    Extract numeric value from article/Offer ID for sorting.
    
    Examples:
        "р20-п5-33" -> 20
        "р25-п5-33" -> 25
        "мд33-п2-30" -> 33
        
    Args:
        article: Article string (e.g., "р20-п5-33")
        
    Returns:
        Extracted number (1-99) or 999 if not found (for sorting)
    """
    if not article:
        return 999
    
    article = str(article).strip()
    
    # Strategy: Remove first 1-2 NON-DIGIT characters, then find first number
    # Try removing 2 non-digit chars first
    if len(article) >= 2 and not article[0].isdigit() and not article[1].isdigit():
        remaining = article[2:]
        if remaining and remaining[0].isdigit() and remaining[0] != '0':
            # Extract first number
            match = re.search(r'\d+', remaining)
            if match:
                number = int(match.group())
                if 1 <= number <= 99:
                    return number
    
    # Try removing 1 non-digit char
    if len(article) >= 1 and not article[0].isdigit():
        remaining = article[1:]
        if remaining and remaining[0].isdigit() and remaining[0] != '0':
            # Extract first number
            match = re.search(r'\d+', remaining)
            if match:
                number = int(match.group())
                if 1 <= number <= 99:
                    return number
    
    # If article starts with a digit, try to extract directly
    if article and article[0].isdigit() and article[0] != '0':
        match = re.search(r'\d+', article)
        if match:
            number = int(match.group())
            if 1 <= number <= 99:
                return number
    
    # If no valid number found, return 999 for sorting (will appear last)
    return 999


# Test cases
test_articles = [
    "р20-п5-33",
    "р25-п5-33",
    "р30-п5-33",
    "мд33-п2-30",
    "р1-п5-33",
    "р99-п5-33",
    "р100-п5-33",  # Should return 999 (over 99)
    "invalid",  # Should return 999
    "",  # Should return 999
]

print("Testing article number extraction:")
print("=" * 50)
for article in test_articles:
    number = extract_article_number(article)
    print(f"'{article}' -> {number}")

print("\n" + "=" * 50)
print("Testing sorting:")
print("=" * 50)

# Test sorting
test_orders = [
    {"article": "р30-п5-33", "order_id": "1"},
    {"article": "р20-п5-33", "order_id": "2"},
    {"article": "мд33-п2-30", "order_id": "3"},
    {"article": "р25-п5-33", "order_id": "4"},
    {"article": "р1-п5-33", "order_id": "5"},
]

sorted_orders = sorted(test_orders, key=lambda x: extract_article_number(x.get("article", "")))

print("Original order:")
for order in test_orders:
    print(f"  {order['article']} (order {order['order_id']})")

print("\nSorted order (ascending by number):")
for order in sorted_orders:
    number = extract_article_number(order['article'])
    print(f"  {order['article']} -> {number} (order {order['order_id']})")
