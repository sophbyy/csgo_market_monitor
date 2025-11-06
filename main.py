# main.py
import logging
import time
from market_monitor import MarketCSGOMonitor
from config import *

# Setup logging
logging.basicConfig(
    level=LOG_LEVEL,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)

def main():
    print("🎯 Steam Profile Monitor")
    print("=" * 50)
    print(f"Target Criteria:")
    print(f"- Steam Level: {MIN_STEAM_LEVEL} to {MAX_STEAM_LEVEL}")
    print(f"- CS:GO Inventory Value: > ${MIN_CSGO_VALUE}")
    print(f"- Activity Status: Active/Inactive")
    print("=" * 50)
    print()
    
    monitor = MarketCSGOMonitor()
    
    while True:
        print("\nChoose an option:")
        print("1. Discover from market data")
        print("2. Check specific profiles")
        print("3. Generate report")
        print("4. Exit")
        
        choice = input("\nEnter your choice (1-4): ").strip()
        
        if choice == "1":
            print("\n🚀 Starting market discovery...")
            pages = input("How many market pages to check? (default 10): ").strip()
            pages = int(pages) if pages.isdigit() else 10
            
            targets_found = monitor.discover_from_market(max_pages=pages)
            print(f"✅ Found {targets_found} new targets!")
            
        elif choice == "2":
            print("\n📝 Enter profile URLs (one per line, empty line to finish):")
            profiles = []
            while True:
                url = input().strip()
                if not url:
                    break
                if url.startswith('https://steamcommunity.com/'):
                    profiles.append(url)
                else:
                    print("❌ Invalid Steam profile URL")
            
            if profiles:
                targets_found = monitor.discover_from_manual_list(profiles)
                print(f"✅ Found {targets_found} targets from your list!")
            else:
                print("❌ No valid profiles provided")
                
        elif choice == "3":
            target_count = monitor.generate_report()
            print(f"📊 Report generated with {target_count} targets")
            
        elif choice == "4":
            print("👋 Goodbye!")
            break
            
        else:
            print("❌ Invalid choice, please try again")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n👋 Program stopped by user")
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        print(f"❌ An error occurred: {e}")