# market_monitor.py
import requests
import json
import time
import random
import sqlite3
import logging
from typing import Dict, List, Optional
from datetime import datetime
from steam_parser import SteamProfileParser
from config import *

logger = logging.getLogger(__name__)

class MarketCSGOMonitor:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept': 'application/json, text/plain, */*',
        })
        self.steam_parser = SteamProfileParser()
        self.init_database()
    
    def init_database(self):
        """Initialize SQLite database for storing profiles"""
        self.conn = sqlite3.connect(DATABASE_NAME)
        self.cursor = self.conn.cursor()
        
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS target_profiles (
                steam_id TEXT PRIMARY KEY,
                username TEXT,
                level INTEGER,
                csgo_value REAL,
                activity_status TEXT,
                profile_url TEXT,
                market_volume INTEGER,
                avg_item_price REAL,
                last_checked TIMESTAMP,
                discovered TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        self.conn.commit()
        logger.info("Database initialized")
    
    def discover_from_market(self, max_pages: int = 10):
        """Discover profiles from market data"""
        logger.info("🚀 Starting market-based discovery...")
        
        # Simulate market data (since market.csgo.com API might require authentication)
        simulated_sellers = self.get_simulated_market_data()
        targets_found = 0
        
        for seller in simulated_sellers:
            try:
                logger.info(f"🔍 Checking: {seller['username']}")
                
                profile_data = self.steam_parser.check_profile_criteria(seller['profile_url'])
                
                if profile_data and profile_data['meets_criteria']:
                    self.save_target_profile(profile_data, seller)
                    targets_found += 1
                    logger.info(f"✅ TARGET FOUND: {profile_data['username']}")
                
                time.sleep(REQUEST_DELAY)
                
            except Exception as e:
                logger.error(f"Error checking seller: {e}")
        
        logger.info(f"✅ Market discovery completed. Found {targets_found} targets.")
        return targets_found
    
    def get_simulated_market_data(self) -> List[Dict]:
        """Simulate market data since real API might need authentication"""
        # In a real implementation, you'd call market.csgo.com API here
        # For now, we'll use simulated data with some example profiles
        
        simulated_sellers = [
            {
                'username': 'CSGO_Trader_1',
                'profile_url': 'https://steamcommunity.com/profiles/76561197960287930',
                'market_volume': 45,
                'avg_item_price': 125.50
            },
            {
                'username': 'Skin_Collector', 
                'profile_url': 'https://steamcommunity.com/id/skincollector',
                'market_volume': 89,
                'avg_item_price': 78.30
            },
            {
                'username': 'Trade_Account_7',
                'profile_url': 'https://steamcommunity.com/profiles/76561197960287931',
                'market_volume': 23,
                'avg_item_price': 210.75
            }
        ]
        
        # Add some randomly generated profiles for variety
        for i in range(10):
            simulated_sellers.append({
                'username': f'Trader_{random.randint(1000, 9999)}',
                'profile_url': f'https://steamcommunity.com/profiles/7656119{random.randint(800000000, 999999999)}',
                'market_volume': random.randint(5, 100),
                'avg_item_price': random.uniform(10, 300)
            })
        
        return simulated_sellers
    
    def discover_from_manual_list(self, profile_list: List[str]):
        """Discover from a manual list of profiles"""
        logger.info(f"🔍 Checking {len(profile_list)} manual profiles...")
        targets_found = 0
        
        for profile_url in profile_list:
            try:
                profile_data = self.steam_parser.check_profile_criteria(profile_url)
                
                if profile_data and profile_data['meets_criteria']:
                    self.save_target_profile(profile_data, {'market_volume': 0, 'avg_item_price': 0})
                    targets_found += 1
                    logger.info(f"✅ TARGET FOUND: {profile_data['username']}")
                
                time.sleep(REQUEST_DELAY)
                
            except Exception as e:
                logger.error(f"Error checking {profile_url}: {e}")
        
        return targets_found
    
    def save_target_profile(self, profile_data: Dict, market_data: Dict):
        """Save target profile to database"""
        try:
            self.cursor.execute('''
                INSERT OR REPLACE INTO target_profiles 
                (steam_id, username, level, csgo_value, activity_status, profile_url, 
                 market_volume, avg_item_price, last_checked)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ''', (
                profile_data['steam_id'],
                profile_data['username'],
                profile_data['level'],
                profile_data['csgo_value'],
                profile_data['activity_status'],
                profile_data['profile_url'],
                market_data.get('market_volume', 0),
                market_data.get('avg_item_price', 0)
            ))
            self.conn.commit()
            logger.debug(f"Saved profile: {profile_data['username']}")
            
        except Exception as e:
            logger.error(f"Error saving profile: {e}")
    
    def generate_report(self):
        """Generate report of found targets"""
        self.cursor.execute('''
            SELECT username, level, csgo_value, activity_status, profile_url, market_volume, avg_item_price
            FROM target_profiles 
            WHERE csgo_value >= ? AND level BETWEEN ? AND ?
            ORDER BY csgo_value DESC
        ''', (MIN_CSGO_VALUE, MIN_STEAM_LEVEL, MAX_STEAM_LEVEL))
        
        targets = self.cursor.fetchall()
        
        print("\n" + "=" * 80)
        print("🎯 STEAM PROFILE DISCOVERY REPORT")
        print("=" * 80)
        print(f"Total targets found: {len(targets)}")
        print(f"Criteria: Level {MIN_STEAM_LEVEL}-{MAX_STEAM_LEVEL} + CS:GO Inventory > ${MIN_CSGO_VALUE}")
        print("=" * 80)
        
        for i, target in enumerate(targets, 1):
            username, level, csgo_value, activity, profile_url, volume, avg_price = target
            print(f"{i}. {username}")
            print(f"   Level: {level} | CS:GO Value: ${csgo_value:.2f} | Status: {activity}")
            print(f"   Market Volume: {volume} trades | Avg Item Price: ${avg_price:.2f}")
            print(f"   Profile: {profile_url}")
            print()
        
        # Save to file
        self.save_detailed_report(targets)
        return len(targets)
    
    def save_detailed_report(self, targets):
        """Save detailed report to file"""
        with open("steam_targets_report.txt", "w", encoding="utf-8") as f:
            f.write("STEAM PROFILE TARGETS REPORT\n")
            f.write("=" * 60 + "\n")
            f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"Total Targets: {len(targets)}\n")
            f.write(f"Criteria: Level {MIN_STEAM_LEVEL}-{MAX_STEAM_LEVEL} + CS:GO Inventory > ${MIN_CSGO_VALUE}\n")
            f.write("=" * 60 + "\n\n")
            
            for i, target in enumerate(targets, 1):
                username, level, csgo_value, activity, profile_url, volume, avg_price = target
                f.write(f"🎯 TARGET #{i}\n")
                f.write(f"Username: {username}\n")
                f.write(f"Level: {level}\n")
                f.write(f"CS:GO Inventory Value: ${csgo_value:.2f}\n")
                f.write(f"Activity Status: {activity}\n")
                f.write(f"Market Volume: {volume} trades\n")
                f.write(f"Average Item Price: ${avg_price:.2f}\n")
                f.write(f"Steam Profile: {profile_url}\n")
                f.write("-" * 50 + "\n")
        
        print(f"📄 Full report saved to 'steam_targets_report.txt'")