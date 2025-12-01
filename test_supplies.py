"""
Test script to check if there are incomplete supplies available
Tests with both 7 days and 365 days to compare results
"""
import logging
import sys
from datetime import datetime, timedelta, timezone
from sheets_handler import SheetsHandler
from supply_orders import SupplyOrdersHandler

# Configure logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
    handlers=[
        logging.StreamHandler(sys.stdout),
    ],
)

logger = logging.getLogger(__name__)


def test_supplies():
    """Test fetching supplies with different max_age_days values"""
    try:
        # Initialize sheets handler
        sheets_handler = SheetsHandler()
        
        # Get all warehouses
        warehouses = sheets_handler.get_warehouse_api_keys()
        
        if not warehouses:
            logger.error("No warehouses found in Google Sheets")
            return
        
        logger.info(f"Found {len(warehouses)} warehouse(s)")
        print("\n" + "="*60)
        print("TESTING SUPPLIES AVAILABILITY")
        print("="*60 + "\n")
        
        for warehouse_info in warehouses:
            warehouse = warehouse_info["warehouse"]
            api_key = warehouse_info["api_key"]
            city = warehouse_info.get("city", "N/A")
            
            print(f"📦 Warehouse: {warehouse} (City: {city})")
            print("-" * 60)
            
            # Create supply handler
            supply_handler = SupplyOrdersHandler(
                api_key=api_key,
                sheets_handler=sheets_handler
            )
            
            # Test with 7 days
            print("\n🔍 Testing with 7 days limit:")
            supplies_7 = supply_handler.fetch_all_incomplete_supplies(max_age_days=7)
            print(f"   Found {len(supplies_7)} incomplete supplies")
            
            if supplies_7:
                print(f"   First supply: {supplies_7[0].get('name', 'N/A')}")
                created_at = supplies_7[0].get('createdAt', '')
                if created_at:
                    try:
                        created_dt = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                        days_ago = (datetime.now(timezone.utc) - created_dt).days
                        print(f"   Created: {created_dt.strftime('%Y-%m-%d %H:%M:%S')} ({days_ago} days ago)")
                    except:
                        print(f"   Created: {created_at}")
            
            # Test with 365 days
            print("\n🔍 Testing with 365 days limit:")
            supplies_365 = supply_handler.fetch_all_incomplete_supplies(max_age_days=365)
            print(f"   Found {len(supplies_365)} incomplete supplies")
            
            if supplies_365:
                print(f"   First supply: {supplies_365[0].get('name', 'N/A')}")
                created_at = supplies_365[0].get('createdAt', '')
                if created_at:
                    try:
                        created_dt = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                        days_ago = (datetime.now(timezone.utc) - created_dt).days
                        print(f"   Created: {created_dt.strftime('%Y-%m-%d %H:%M:%S')} ({days_ago} days ago)")
                    except:
                        print(f"   Created: {created_at}")
                
                # Show all supplies with dates
                print(f"\n   All incomplete supplies ({len(supplies_365)} total):")
                for idx, supply in enumerate(supplies_365[:10], 1):  # Show first 10
                    name = supply.get('name', 'N/A')
                    status = supply.get('status', 'N/A')
                    created_at = supply.get('createdAt', '')
                    if created_at:
                        try:
                            created_dt = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                            days_ago = (datetime.now(timezone.utc) - created_dt).days
                            date_str = f"{created_dt.strftime('%Y-%m-%d')} ({days_ago}d ago)"
                        except:
                            date_str = created_at
                    else:
                        date_str = "N/A"
                    print(f"   {idx}. {name} - Status: {status} - Created: {date_str}")
                
                if len(supplies_365) > 10:
                    print(f"   ... and {len(supplies_365) - 10} more supplies")
            else:
                print("   ⚠️  No incomplete supplies found even with 365 days limit!")
            
            print("\n" + "="*60 + "\n")
        
        print("✅ Test completed!")
        
    except Exception as e:
        logger.error(f"Error testing supplies: {e}", exc_info=True)
        print(f"\n❌ Error: {e}")


if __name__ == "__main__":
    test_supplies()

