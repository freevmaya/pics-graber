# ============================================================
# FILE: bot_telebot.py
# TYPE: .PY
# ============================================================

"""Telegram bot using pyTelegramBotAPI."""

import telebot
from telebot import types
import logging
from typing import Optional, Dict, List
from pathlib import Path
import time
from datetime import datetime

from config import Config
from database import DatabaseManager
from pinterest_downloader import PinterestDownloader

# Setup logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

class PinterestBot:
    """Main bot class using pyTelegramBotAPI."""
    
    # Constants
    CALLBACK_NEXT = "next"
    CALLBACK_STOP = "stop"
    CALLBACK_NEW_SEARCH = "new_search"
    
    def __init__(self):
        """Initialize bot components."""
        self.config = Config()
        self.db = DatabaseManager()
        self.downloader = PinterestDownloader()
        self.batch_size = Config.IMAGES_PER_BATCH
        self.bot = telebot.TeleBot(Config.BOT_TOKEN)
        
        # Check pinterest-dl
        if not PinterestDownloader.check_pinterest_dl():
            logger.warning("pinterest-dl not found. Please install it: pip install pinterest-dl")
        
        # Register handlers
        self.register_handlers()
    
    def register_handlers(self):
        """Register message and callback handlers."""
        
        @self.bot.message_handler(commands=['start'])
        def start_command(message):
            user = message.from_user
            self.db.register_user(
                user_id=user.id,
                username=user.username,
                first_name=user.first_name,
                last_name=user.last_name
            )
            
            welcome_text = (
                f"👋 *Welcome, {user.first_name}!*\n\n"
                "I can help you find and download images from Pinterest.\n\n"
                "📝 *How to use:*\n"
                "• Send me any search query (e.g., 'cats', 'beautiful landscapes')\n"
                f"• I'll show you {self.batch_size} images at a time\n"
                "• Use the buttons to see more or start a new search\n\n"
                "🔍 *Try it now:* Send me a search term!"
            )
            
            self.bot.reply_to(message, welcome_text, parse_mode='Markdown')
        
        @self.bot.message_handler(commands=['help'])
        def help_command(message):
            help_text = (
                "🤖 *Pinterest Image Bot Help*\n\n"
                "*Commands:*\n"
                "/start - Start the bot\n"
                "/help - Show this help\n"
                "/new - Start a new search\n"
                "/stop - Stop current search\n\n"
                "*How to search:*\n"
                "Simply type what you want to find!\n"
                "Examples: 'sunset beach', 'cute puppies', 'modern architecture'\n\n"
                "*Features:*\n"
                f"• Shows {self.batch_size} images per batch\n"
                "• Caches results for faster access\n"
                "• Continue or stop anytime"
            )
            
            self.bot.reply_to(message, help_text, parse_mode='Markdown')
        
        @self.bot.message_handler(commands=['new'])
        def new_command(message):
            user_id = message.from_user.id
            self.db.reset_user_session(user_id)
            
            self.bot.reply_to(
                message,
                "🆕 *Starting new search*\nSend me what you'd like to find!",
                parse_mode='Markdown'
            )
        
        @self.bot.message_handler(commands=['stop'])
        def stop_command(message):
            user_id = message.from_user.id
            self.db.reset_user_session(user_id)
            
            self.bot.reply_to(
                message,
                "⏹️ *Search stopped*\nSend a new query to start again!",
                parse_mode='Markdown'
            )
        
        @self.bot.message_handler(func=lambda message: True)
        def handle_message(message):
            user = message.from_user
            query = message.text.strip()
            
            if not query:
                self.bot.reply_to(message, "Please send a non-empty search query.")
                return
            
            # Register/update user
            self.db.register_user(
                user_id=user.id,
                username=user.username,
                first_name=user.first_name,
                last_name=user.last_name
            )
            
            # Send initial status
            status_msg = self.bot.reply_to(
                message,
                f"🔍 *Searching for:* {query}\n⏳ Please wait...",
                parse_mode='Markdown'
            )
            
            # Process search
            self.process_search(message, query, status_msg)
        
        @self.bot.callback_query_handler(func=lambda call: True)
        def handle_callback(call):
            user_id = call.from_user.id
            callback_data = call.data
            
            if callback_data == self.CALLBACK_STOP:
                self.db.reset_user_session(user_id)
                self.bot.edit_message_text(
                    chat_id=user_id,
                    message_id=call.message.message_id,
                    text="⏹️ *Search stopped*\nUse /new to start another search!",
                    parse_mode='Markdown'
                )
                
            elif callback_data == self.CALLBACK_NEW_SEARCH:
                self.db.reset_user_session(user_id)
                self.bot.edit_message_text(
                    chat_id=user_id,
                    message_id=call.message.message_id,
                    text="🆕 *Ready for new search*\nSend me what you'd like to find!",
                    parse_mode='Markdown'
                )
                
            elif callback_data == self.CALLBACK_NEXT:
                session = self.db.get_user_session(user_id)
                
                if not session or not session.get('current_search_cache_id'):
                    self.bot.edit_message_text(
                        chat_id=user_id,
                        message_id=call.message.message_id,
                        text="⚠️ *Session expired*\nPlease start a new search.",
                        parse_mode='Markdown'
                    )
                    return
                
                # Get next batch
                next_images = self.db.get_unsent_images(
                    session['current_search_cache_id'],
                    self.batch_size,
                    session['current_offset']
                )
                
                if not next_images:
                    self.bot.edit_message_text(
                        chat_id=user_id,
                        message_id=call.message.message_id,
                        text="✨ *No more images*\nUse /new to start another search!",
                        parse_mode='Markdown'
                    )
                    return
                
                # Update offset
                new_offset = session['current_offset'] + len(next_images)
                self.db.update_user_session(
                    user_id=user_id,
                    offset=new_offset
                )
                
                # Calculate batches
                current_batch = (new_offset - len(next_images)) // self.batch_size + 1
                total_batches = (session['total_images'] + self.batch_size - 1) // self.batch_size
                
                # Delete callback message
                try:
                    self.bot.delete_message(user_id, call.message.message_id)
                except:
                    pass
                
                # Send next batch
                self.send_image_batch(
                    user_id,
                    next_images,
                    current_batch,
                    total_batches,
                    session['current_search_cache_id']
                )
    
    def process_search(self, message, query, status_msg):
        """Process search query."""
        user = message.from_user
        
        # Check cache
        cached_search = self.db.get_cached_search(user.id, query)
        search_cache_id = None
        images = []
        
        if cached_search:
            search_cache_id = cached_search['id']
            logger.info(f"Found cached search for user {user.id}: {query}")
            
            images = self.db.get_unsent_images(
                search_cache_id,
                self.batch_size,
                0
            )
        
        # If no cache or no images, download new ones
        if not images:
            try:
                self.bot.edit_message_text(
                    chat_id=user.id,
                    message_id=status_msg.message_id,
                    text=f"🔍 *Searching for:* {query}\n📥 Downloading images...",
                    parse_mode='Markdown'
                )
            except:
                pass
            
            downloaded = self.downloader.download_images(
                query,
                Config.MAX_IMAGES_PER_REQUEST
            )
            
            if not downloaded:
                try:
                    self.bot.edit_message_text(
                        chat_id=user.id,
                        message_id=status_msg.message_id,
                        text="❌ *No images found*\nPlease try a different search term.",
                        parse_mode='Markdown'
                    )
                except:
                    self.bot.reply_to(
                        message,
                        "❌ *No images found*\nPlease try a different search term.",
                        parse_mode='Markdown'
                    )
                return
            
            if not cached_search:
                normalized = self.db.normalize_query(query)
                query_md5 = self.db.get_query_md5(query)
                search_cache_id = self.db.create_search_cache(
                    user.id, query, normalized, query_md5
                )
            
            if search_cache_id:
                saved = self.db.save_images_to_cache(search_cache_id, downloaded)
                logger.info(f"Saved {saved} images to cache for search {search_cache_id}")
                images = self.db.get_unsent_images(search_cache_id, self.batch_size, 0)
        
        if not images:
            try:
                self.bot.edit_message_text(
                    chat_id=user.id,
                    message_id=status_msg.message_id,
                    text="❌ *No images available*\nPlease try again later.",
                    parse_mode='Markdown'
                )
            except:
                self.bot.reply_to(
                    message,
                    "❌ *No images available*\nPlease try again later.",
                    parse_mode='Markdown'
                )
            return
        
        # Get total images count
        session = self.db.get_user_session(user.id)
        total_images = session['total_images'] if session else len(images)
        
        # Update user session
        self.db.update_user_session(
            user_id=user.id,
            search_cache_id=search_cache_id,
            offset=len(images),
            total_images=total_images,
            last_query=query,
            last_message_id=status_msg.message_id
        )
        
        # Delete status message
        try:
            self.bot.delete_message(user.id, status_msg.message_id)
        except:
            pass
        
        # Send images
        self.send_image_batch(
            user.id,
            images,
            current_batch=1,
            total_batches=(total_images + self.batch_size - 1) // self.batch_size,
            search_cache_id=search_cache_id
        )
    
    def send_image_batch(self, user_id, images, current_batch, total_batches, search_cache_id):
        """Send a batch of images to user."""
        if not images:
            self.bot.send_message(
                user_id,
                "✨ *No more images*\nUse /new to start another search!",
                parse_mode='Markdown'
            )
            return
        
        # Create keyboard
        keyboard = types.InlineKeyboardMarkup()
        
        session = self.db.get_user_session(user_id)
        if session and session['current_offset'] < session['total_images']:
            keyboard.add(types.InlineKeyboardButton(
                f"▶️ Next {self.batch_size}",
                callback_data=self.CALLBACK_NEXT
            ))
        
        keyboard.row(
            types.InlineKeyboardButton("⏹️ Stop", callback_data=self.CALLBACK_STOP),
            types.InlineKeyboardButton("🆕 New Search", callback_data=self.CALLBACK_NEW_SEARCH)
        )
        
        # Send batch info
        self.bot.send_message(
            user_id,
            f"📸 *Batch {current_batch} of {total_batches}*\nShowing {len(images)} images",
            parse_mode='Markdown'
        )
        
        # Send images
        image_ids = []
        for img in images:
            try:
                if img['local_path'] and Path(img['local_path']).exists():
                    with open(img['local_path'], 'rb') as photo:
                        self.bot.send_photo(
                            user_id,
                            photo,
                            caption=img.get('caption', '')[:200] if img.get('caption') else None
                        )
                        image_ids.append(img['id'])
                else:
                    self.bot.send_message(
                        user_id,
                        f"⚠️ Image file not found: {img.get('file_name', 'unknown')}"
                    )
                
                time.sleep(0.5)
                
            except Exception as e:
                logger.error(f"Error sending image: {e}")
                self.bot.send_message(
                    user_id,
                    f"⚠️ Failed to send image: {img.get('file_name', 'unknown')}"
                )
        
        # Mark images as sent
        if image_ids:
            self.db.mark_images_as_sent(image_ids)
        
        # Send navigation message
        nav_msg = (
            f"*What would you like to do?*\n\n"
            f"📊 Progress: {session['current_offset'] if session else len(images)}/{session['total_images'] if session else len(images)}"
        )
        
        self.bot.send_message(
            user_id,
            nav_msg,
            parse_mode='Markdown',
            reply_markup=keyboard
        )
    
    def run(self):
        """Run the bot."""
        logger.info("Starting Pinterest Bot...")
        print("\n" + "="*50)
        print("🤖 Pinterest Image Bot Started")
        print("="*50)
        print(f"Bot Token: {Config.BOT_TOKEN[:10]}...")
        print(f"Images per batch: {self.batch_size}")
        print(f"Max images per request: {Config.MAX_IMAGES_PER_REQUEST}")
        print("="*50 + "\n")
        
        self.bot.infinity_polling()
    
    def __del__(self):
        """Cleanup on deletion."""
        if hasattr(self, 'db'):
            self.db.close()