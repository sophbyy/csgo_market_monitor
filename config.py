# config.py
import os

# Rate limiting (be respectful to Steam servers)
REQUEST_DELAY = 3.0  # seconds between requests
MAX_WORKERS = 2

# Target criteria
MIN_STEAM_LEVEL = 0
MAX_STEAM_LEVEL = 10
MIN_CSGO_VALUE = 500

# Market settings
MARKET_CHECK_INTERVAL_HOURS = 6
MIN_TRADING_VOLUME = 5
MIN_ITEM_PRICE = 50

# Database settings
DATABASE_NAME = "steam_monitor.db"

# Logging
LOG_LEVEL = "INFO"
LOG_FILE = "steam_monitor.log"