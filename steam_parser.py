# steam_parser.py
import requests
from bs4 import BeautifulSoup
import json
import time
import re
import logging
from typing import Dict, Optional
from config import REQUEST_DELAY, MIN_STEAM_LEVEL, MAX_STEAM_LEVEL, MIN_CSGO_VALUE

logger = logging.getLogger(__name__)

class SteamProfileParser:
    def __init__(self, delay: float = REQUEST_DELAY):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept-Language': 'en-US,en;q=0.9',
        })
        self.delay = delay
        self.price_cache = {}
    
    def check_profile_criteria(self, profile_url: str) -> Optional[Dict]:
        """Check if profile meets our criteria: level 0-10 + CS:GO inventory > $500"""
        logger.info(f"🔍 Checking Steam profile: {profile_url}")
        
        try:
            # Get basic profile data
            profile_data = self.get_basic_profile_data(profile_url)
            if not profile_data:
                return None
            
            # Check level criteria
            level = profile_data.get('level', 0)
            if not (MIN_STEAM_LEVEL <= level <= MAX_STEAM_LEVEL):
                logger.debug(f"Level {level} outside range {MIN_STEAM_LEVEL}-{MAX_STEAM_LEVEL}")
                return {**profile_data, 'meets_criteria': False}
            
            # Check CS:GO inventory value
            csgo_value = self.get_csgo_inventory_value(profile_data['steam_id'])
            profile_data['csgo_value'] = csgo_value
            
            # Determine if meets criteria
            meets_criteria = csgo_value >= MIN_CSGO_VALUE
            profile_data['meets_criteria'] = meets_criteria
            
            if meets_criteria:
                logger.info(f"🎯 Target found: {profile_data['username']} - Level {level} - CS:GO ${csgo_value:.2f}")
            
            return profile_data
            
        except Exception as e:
            logger.error(f"Error checking profile {profile_url}: {e}")
            return None
    
    def get_basic_profile_data(self, profile_url: str) -> Optional[Dict]:
        """Get basic profile information"""
        try:
            time.sleep(self.delay)
            response = self.session.get(profile_url, timeout=30)
            if response.status_code != 200:
                return None
            
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Check if profile is private
            if self.is_profile_private(soup):
                return {
                    'steam_id': self.extract_steam_id(soup, profile_url),
                    'profile_url': profile_url,
                    'username': 'Private Profile',
                    'level': 0,
                    'activity_status': 'unknown',
                    'private_profile': True
                }
            
            steam_id = self.extract_steam_id(soup, profile_url)
            username = self.extract_username(soup)
            level = self.extract_level(soup)
            activity_status = self.determine_activity_status(soup)
            
            return {
                'steam_id': steam_id,
                'profile_url': profile_url,
                'username': username,
                'level': level,
                'activity_status': activity_status,
                'private_profile': False
            }
            
        except Exception as e:
            logger.error(f"Error getting basic profile data: {e}")
            return None
    
    def get_csgo_inventory_value(self, steam_id: str) -> float:
        """Get CS:GO inventory value"""
        if steam_id == "Unknown":
            return 0.0
        
        inventory_url = f"https://steamcommunity.com/inventory/{steam_id}/730/2?l=english&count=5000"
        
        try:
            time.sleep(self.delay)
            response = self.session.get(inventory_url, timeout=30)
            if response.status_code != 200:
                return 0.0
            
            inventory_data = response.json()
            if not inventory_data or 'assets' not in inventory_data:
                return 0.0
            
            assets = inventory_data.get('assets', [])
            descriptions = {desc['classid']: desc for desc in inventory_data.get('descriptions', [])}
            
            total_value = 0.0
            valuable_items = []
            
            for asset in assets:
                item_value = self.get_csgo_item_value(asset, descriptions)
                if item_value > 0:
                    total_value += item_value
                    # Track valuable items for logging
                    if item_value > 10:
                        class_id = asset.get('classid')
                        if class_id in descriptions:
                            item_name = descriptions[class_id].get('market_hash_name', 'Unknown')
                            valuable_items.append((item_name, item_value))
            
            # Log valuable items
            if valuable_items:
                logger.debug(f"Found {len(valuable_items)} valuable items totaling ${total_value:.2f}")
                for item_name, value in valuable_items[:3]:  # Show top 3
                    logger.debug(f"  - {item_name}: ${value:.2f}")
            
            return total_value
            
        except Exception as e:
            logger.error(f"Error getting CS:GO inventory for {steam_id}: {e}")
            return 0.0
    
    def get_csgo_item_value(self, asset: Dict, descriptions: Dict) -> float:
        """Get value of a CS:GO item"""
        class_id = asset.get('classid')
        if not class_id or class_id not in descriptions:
            return 0.0
        
        description = descriptions[class_id]
        if not description.get('marketable'):
            return 0.0
        
        market_hash_name = description.get('market_hash_name')
        if not market_hash_name:
            return 0.0
        
        # Check cache
        if market_hash_name in self.price_cache:
            return self.price_cache[market_hash_name]
        
        # Get market price
        price = self.get_market_price(market_hash_name)
        if price:
            self.price_cache[market_hash_name] = price
        
        return price or 0.0
    
    def get_market_price(self, market_hash_name: str) -> float:
        """Get market price for an item"""
        encoded_name = requests.utils.quote(market_hash_name)
        url = f"https://steamcommunity.com/market/priceoverview/?appid=730&currency=1&market_hash_name={encoded_name}"
        
        try:
            time.sleep(self.delay)
            response = self.session.get(url, timeout=30)
            if response.status_code != 200:
                return 0.0
            
            price_data = response.json()
            if price_data.get('success'):
                price_str = price_data.get('lowest_price') or price_data.get('median_price')
                if price_str:
                    price_clean = re.sub(r'[^\d.]', '', price_str)
                    return float(price_clean)
        except Exception as e:
            logger.debug(f"Error getting price for {market_hash_name}: {e}")
        
        return 0.0
    
    def extract_steam_id(self, soup: BeautifulSoup, url: str) -> str:
        """Extract SteamID from profile"""
        if '/profiles/' in url:
            steam_id = url.split('/profiles/')[1].split('/')[0]
            if steam_id.isdigit():
                return steam_id
        
        pattern = r'g_steamID = "(\d+)"'
        script = soup.find('script', string=re.compile(pattern))
        if script:
            match = re.search(pattern, script.string)
            if match:
                return match.group(1)
        
        return "Unknown"
    
    def extract_username(self, soup: BeautifulSoup) -> str:
        """Extract username from profile"""
        selectors = ['.actual_persona_name', '.persona_name', '.profile_header_name']
        for selector in selectors:
            element = soup.select_one(selector)
            if element and element.text.strip():
                return element.text.strip()
        return "Unknown"
    
    def extract_level(self, soup: BeautifulSoup) -> int:
        """Extract Steam level"""
        level_element = soup.select_one('.persona_level .friendPlayerLevelNum')
        if level_element:
            try:
                return int(level_element.text.strip())
            except ValueError:
                pass
        return 0
    
    def determine_activity_status(self, soup: BeautifulSoup) -> str:
        """Determine if user is active or inactive"""
        # Check for online status
        online_indicators = soup.select('.profile_in_game_header, .profile_in_game_name')
        if online_indicators:
            return "active"
        
        # Check last online time
        last_online_text = self.extract_last_online(soup)
        if any(x in last_online_text.lower() for x in ['now', 'min', 'hour', 'today']):
            return "active"
        
        return "inactive"
    
    def extract_last_online(self, soup: BeautifulSoup) -> str:
        """Extract last online time"""
        selectors = ['.profile_in_game_header', '.friendLastOnlineText', '.profile_in_game']
        for selector in selectors:
            element = soup.select_one(selector)
            if element:
                text = element.text.strip()
                if text and ('online' in text.lower() or 'offline' in text.lower()):
                    return text
        return "Unknown"
    
    def is_profile_private(self, soup: BeautifulSoup) -> bool:
        """Check if profile is private"""
        private_indicators = ['.profile_private_info', '.profile_private_message']
        for indicator in private_indicators:
            if soup.select_one(indicator):
                return True
        return False