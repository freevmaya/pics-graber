# ============================================================
# FILE: main.py (FINAL)
# TYPE: .PY
#============================================================

"""Main entry point for Pinterest Telegram Bot."""

import sys
import os
import telebot
from pathlib import Path

# Add current directory to path
sys.path.insert(0, str(Path(__file__).parent))

# Используем telebot версию
from bot_telebot import PinterestBot
from config import Config

def check_requirements():
    """Check if all requirements are met."""
    # Check for pinterest-dl
    try:
        from pinterest_downloader import PinterestDownloader
        if not PinterestDownloader.check_pinterest_dl():
            print("⚠️  Warning: pinterest-dl not found. Install it with:")
            print("   pip install pinterest-dl")
    except:
        print("⚠️  Warning: Could not check pinterest-dl")
    
    # Create download directory
    Config.DOWNLOAD_DIR.mkdir(exist_ok=True)
    
    # Check database connection
    try:
        from database import DatabaseManager
        db = DatabaseManager()
        db.close()
        print("✓ Database connection successful")
    except Exception as e:
        print(f"✗ Database error: {e}")
        print("Please check your .env configuration")
        return False
    
    return True

def main():
    """Main function."""
    print("\n" + "="*50)
    print("PINTEREST TELEGRAM BOT")
    print("="*50)
    
    # Check if .env exists
    if not Path('.env').exists():
        print("✗ .env file not found!")
        print("\nPlease create .env file with the following content:")
        print("""
BOT_TOKEN=your_telegram_bot_token_here
DB_HOST=localhost
DB_PORT=3306
DB_NAME=pinterest_bot_cache
DB_USER=root
DB_PASSWORD=your_password_here
DB_CHARSET=utf8mb4
IMAGES_PER_BATCH=5
MAX_IMAGES_PER_REQUEST=50
DOWNLOAD_TIMEOUT=300
TEMP_DOWNLOAD_DIR=temp_downloads
        """)
        return
    
    # Check requirements
    if not check_requirements():
        print("\n✗ Requirements check failed. Please fix the issues above.")
        return
    
    try:
        # Create and run bot
        bot = PinterestBot(telebot.TeleBot(Config.BOT_TOKEN))
        bot.run()
    except KeyboardInterrupt:
        print("\n\n👋 Bot stopped by user")
    except Exception as e:
        print(f"\n❌ Fatal error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        print("\n" + "="*50)
        print("Bot shutdown complete")
        print("="*50)

if __name__ == "__main__":
    main()