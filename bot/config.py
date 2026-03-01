"""Configuration management for the bot."""

import os
from dotenv import load_dotenv
from pathlib import Path

# Load environment variables
load_dotenv()

class Config:
    """Bot configuration class."""
    
    # Telegram
    BOT_TOKEN = os.getenv('BOT_TOKEN')
    if not BOT_TOKEN:
        raise ValueError("BOT_TOKEN must be set in .env file")
    
    # Database
    DB_CONFIG = {
        'host': os.getenv('DB_HOST', 'localhost'),
        'port': os.getenv('DB_PORT', '3306'),
        'database': os.getenv('DB_NAME', 'pinterest_bot_cache'),
        'user': os.getenv('DB_USER', 'root'),
        'password': os.getenv('DB_PASSWORD', ''),
        'charset': os.getenv('DB_CHARSET', 'utf8mb4'),
        'use_pure': True
    }
    
    # Bot settings
    IMAGES_PER_BATCH = int(os.getenv('IMAGES_PER_BATCH', '5'))
    MAX_IMAGES_PER_REQUEST = int(os.getenv('MAX_IMAGES_PER_REQUEST', '50'))
    DOWNLOAD_TIMEOUT = int(os.getenv('DOWNLOAD_TIMEOUT', '300'))
    TEMP_DOWNLOAD_DIR = os.getenv('TEMP_DOWNLOAD_DIR', 'temp_downloads')
    
    # Paths
    BASE_DIR = Path(__file__).parent
    DOWNLOAD_DIR = BASE_DIR / TEMP_DOWNLOAD_DIR