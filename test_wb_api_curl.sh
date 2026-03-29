#!/bin/bash
# Test WB Supplies API with curl
# Usage: ./test_wb_api_curl.sh [API_KEY]
# If API_KEY not provided - extracts from Google Sheets via Python

set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if [ -n "$1" ]; then
    API_KEY="$1"
    echo "Using provided API key (first 50 chars): ${API_KEY:0:50}..."
else
    echo "Extracting API keys from Google Sheets..."
    API_KEYS=$(python3 -c "
from sheets_handler import SheetsHandler
sh = SheetsHandler()
for w in sh.get_warehouse_api_keys():
    print(f\"{w['warehouse']}|{w['api_key']}\")
" 2>/dev/null)
    
    if [ -z "$API_KEYS" ]; then
        echo "ERROR: Could not load API keys from Sheets"
        exit 1
    fi
    
    echo ""
    echo "$API_KEYS" | while IFS='|' read -r warehouse key; do
        echo "=========================================="
        echo "Testing warehouse: $warehouse"
        echo "=========================================="
        echo "curl -s -w '\nHTTP_CODE:%{http_code} TIME:%{time_total}s\n' --connect-timeout 10 --max-time 35 \\"
        echo "  -H 'Authorization: <key>' -H 'Content-Type: application/json' \\"
        echo "  'https://marketplace-api.wildberries.ru/api/v3/supplies?limit=100&next=0'"
        echo ""
        
        RESPONSE=$(curl -s -w "\n---META---\nHTTP_CODE:%{http_code}\nTIME:%{time_total}s\n" \
            --connect-timeout 10 --max-time 35 \
            -H "Authorization: $key" \
            -H "Content-Type: application/json" \
            "https://marketplace-api.wildberries.ru/api/v3/supplies?limit=100&next=0")
        
        echo "$RESPONSE" | head -20
        echo ""
        if echo "$RESPONSE" | grep -q '"unauthorized"'; then
            echo "❌ 401 Unauthorized - token expired or invalid"
            echo "   Update at: https://seller.wildberries.ru/supplier-settings/access-to-api"
        elif echo "$RESPONSE" | grep -q 'HTTP_CODE:200'; then
            echo "✅ 200 OK - API working"
        elif echo "$RESPONSE" | grep -q 'timed out'; then
            echo "⏱️  Timeout - API slow or blocked from this network"
        fi
        echo ""
    done
    exit 0
fi

echo ""
echo "Testing supplies API..."
echo "URL: https://marketplace-api.wildberries.ru/api/v3/supplies?limit=100&next=0"
echo ""

RESPONSE=$(curl -s -w "\n---META---\nHTTP_CODE:%{http_code}\nTIME:%{time_total}s\n" \
    --connect-timeout 10 --max-time 35 \
    -H "Authorization: $API_KEY" \
    -H "Content-Type: application/json" \
    "https://marketplace-api.wildberries.ru/api/v3/supplies?limit=100&next=0")

echo "$RESPONSE"
echo ""

if echo "$RESPONSE" | grep -q '"detail": "access token expired"'; then
    echo "❌ Token EXPIRED - regenerate at https://seller.wildberries.ru/supplier-settings/access-to-api"
elif echo "$RESPONSE" | grep -q 'HTTP_CODE:200'; then
    echo "✅ Success"
fi
