# ============================================================
# FILE: bot_telebot.py (FIXED - ALL URLS GO TO GALLERY-DL)
# ============================================================

"""Telegram bot using pyTelegramBotAPI with video support, action buttons and URL downloads."""

import telebot
from telebot import types
import logging
from typing import Optional, Dict, List, Any
from pathlib import Path
import time
from datetime import datetime
import html
import os
import re

from config import Config
from database import DatabaseManager
from pinterest_downloader import PinterestDownloader
from gallery_dl_downloader import GalleryDLDownloader
from localization import LocalizationManager

# Setup logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)


def get_last_n_parts(path, n=2):
    path_obj = Path(path)
    parts = path_obj.parts[-n:]
    return str(Path(*parts))

class PinterestBot:
    """Main bot class with video support and action buttons."""
    
    # Constants
    CALLBACK_NEXT = "next"
    CALLBACK_STOP = "stop"
    CALLBACK_NEW_SEARCH = "new_search"
    CALLBACK_LANGUAGE = "lang_"
    CALLBACK_MORE_INFO = "more_info_"
    
    # File size limits (Telegram limits)
    MAX_PHOTO_SIZE = 10 * 1024 * 1024  # 10 MB for photos
    MAX_VIDEO_SIZE = 50 * 1024 * 1024  # 50 MB for videos
    
    # URL pattern for detection
    URL_PATTERN = re.compile(
        r'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\\(\\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+'
    )
    
    def __init__(self, bot):
        """Initialize bot components."""
        self.config = Config()
        self.db = DatabaseManager()
        self.pinterest_downloader = PinterestDownloader()  # Only for search queries
        self.gallery_downloader = GalleryDLDownloader()    # For all URLs
        self.localization = LocalizationManager()
        self.batch_size = Config.IMAGES_PER_BATCH
        self.bot = bot
        self._message_store = {}  # Store for message tracking
        
        # Check pinterest-dl
        if not PinterestDownloader.check_pinterest_dl():
            logger.warning("pinterest-dl not found. Please install it: pip install pinterest-dl")
        
        # Check gallery-dl
        if not self.gallery_downloader._check_gallery_dl():
            logger.warning("gallery-dl not found. Please install it: pip install gallery-dl")
        
        # Register handlers
        self.register_handlers()
    
    def _get_user_id_from_message(self, message) -> Optional[int]:
        """
        Extract user ID from various message/callback structures.
        Works with:
        - Regular messages (message.from_user)
        - Callback queries (message.from_user or message.message.chat)
        - Channel posts (message.sender_chat)
        - Messages from bot (fallback to chat ID)
        """
        try:
            # Try to get from from_user first (most common case)
            if hasattr(message, 'from_user') and message.from_user:
                return message.from_user.id
            
            # Try callback query structure
            if hasattr(message, 'message') and message.message:
                if hasattr(message.message, 'from_user') and message.message.from_user:
                    return message.message.from_user.id
                if hasattr(message.message, 'chat') and message.message.chat:
                    return message.message.chat.id
            
            # Try to get chat ID (for messages without user)
            if hasattr(message, 'chat') and message.chat:
                return message.chat.id
            
            # Try to get from message.chat for callback queries
            if hasattr(message, 'message') and hasattr(message.message, 'chat'):
                return message.message.chat.id
            
            # Try sender_chat (for channel posts)
            if hasattr(message, 'sender_chat') and message.sender_chat:
                return message.sender_chat.id
            
            # Last resort: try to get any ID attribute
            for attr in ['user_id', 'id', 'chat_id']:
                if hasattr(message, attr):
                    return getattr(message, attr)
            
            logger.error(f"Could not extract user ID from message: {type(message)}")
            return None
            
        except Exception as e:
            logger.error(f"Error extracting user ID: {e}")
            return None
    
    def get_text(self, key: str, message, **kwargs) -> str:
        """Helper to get localized text."""
        text = self.localization.get_text(key, message, **kwargs)
        return text
    
    def format_file_size(self, size_bytes: int) -> str:
        """Format file size for display."""
        if not size_bytes:
            return "?"
        if size_bytes < 1024:
            return f"{size_bytes} B"
        elif size_bytes < 1024 * 1024:
            return f"{size_bytes / 1024:.1f} KB"
        elif size_bytes < 1024 * 1024 * 1024:
            return f"{size_bytes / (1024 * 1024):.1f} MB"
        else:
            return f"{size_bytes / (1024 * 1024 * 1024):.1f} GB"
    
    def format_duration(self, seconds: float) -> str:
        """Format duration for display."""
        if not seconds or seconds <= 0:
            return "?"
        
        minutes = int(seconds // 60)
        seconds = int(seconds % 60)
        return f"{minutes}:{seconds:02d}"
    
    def is_url(self, text: str) -> bool:
        """Check if text is a URL."""
        return bool(self.URL_PATTERN.match(text.strip()))
    
    def store_message_info(self, user_id: int, image_message_id: int, media_id: int, file_path: str):
        """Store message information for later reference."""
        key = f"{user_id}_{image_message_id}"
        self._message_store[key] = {
            'media_id': media_id,
            'file_path': file_path,
            'user_id': user_id,
            'image_message_id': image_message_id
        }
        logger.info(f"Stored message info for user {user_id}, image {image_message_id}")

    def get_message_info(self, user_id: int, image_message_id: int) -> Optional[Dict]:
        """Get stored message information."""
        key = f"{user_id}_{image_message_id}"
        info = self._message_store.get(key)
        
        if info:
            logger.info(f"Found message info for user {user_id}, image {image_message_id}")
        else:
            logger.info(f"No message info found for user {user_id}, image {image_message_id}")
        
        return info
    
    def register_handlers(self):
        """Register message and callback handlers."""
        
        @self.bot.message_handler(commands=['start'])
        def start_command(message):
            user = message.from_user
            user_id = self._get_user_id_from_message(message)
            
            self.db.register_user(
                user_id=user_id,
                username=user.username,
                first_name=user.first_name,
                last_name=user.last_name,
                language_code=user.language_code or 'en'
            )
            
            welcome_text = self.get_text(
                'welcome', message,
                name=user.first_name,
                batch_size=self.batch_size
            )
            
            self.bot.reply_to(message, welcome_text, parse_mode='HTML')
        
        @self.bot.message_handler(commands=['help'])
        def help_command(message):
            help_text = self.get_text(
                'help', message,
                batch_size=self.batch_size
            )
            
            self.bot.reply_to(message, help_text, parse_mode='HTML')
        
        @self.bot.message_handler(commands=['language'])
        def language_command(message):
            """Handle language change command."""
            keyboard = self.localization.get_language_keyboard(message)
            
            self.bot.reply_to(
                message,
                self.get_text('language_prompt', message),
                parse_mode='HTML',
                reply_markup=keyboard
            )
        
        @self.bot.message_handler(commands=['new'])
        def new_command(message):
            user_id = self._get_user_id_from_message(message)
            self.db.reset_user_session(user_id)
            
            self.bot.reply_to(
                message,
                self.get_text('ready_for_search', message),
                parse_mode='HTML'
            )
        
        @self.bot.message_handler(commands=['stop'])
        def stop_command(message):
            user_id = self._get_user_id_from_message(message)
            self.db.reset_user_session(user_id)
            
            self.bot.reply_to(
                message,
                self.get_text('search_stopped', message),
                parse_mode='HTML'
            )
        
        @self.bot.message_handler(func=lambda message: True)
        def handle_message(message):
            user = message.from_user
            user_id = self._get_user_id_from_message(message)
            text = message.text.strip()
            
            if not text:
                self.bot.reply_to(
                    message,
                    self.get_text('empty_query', message)
                )
                return
            
            # Register/update user
            self.db.register_user(
                user_id=user_id,
                username=user.username,
                first_name=user.first_name,
                last_name=user.last_name,
                language_code=self.localization.get_user_language(message)
            )
            
            # Check if it's a URL
            if self.is_url(text):
                self.handle_url(message, text)
            else:
                # Regular search query
                self.process_search(message, text)
        
        @self.bot.callback_query_handler(func=lambda call: True)
        def handle_callback(call):
            """Handle all callback queries including new action buttons."""
            user_id = self._get_user_id_from_message(call)
            callback_data = call.data
            
            # Handle media action buttons
            if callback_data.startswith("download_"):
                # Download button pressed
                media_id = int(callback_data.replace("download_", ""))
                self.handle_download(user_id, media_id, call)
                
            elif callback_data.startswith("share_"):
                # Share button pressed
                media_id = int(callback_data.replace("share_", ""))
                self.handle_share(user_id, media_id, call)
                
            elif callback_data.startswith("remove_"):
                # Remove button pressed
                media_id = int(callback_data.replace("remove_", ""))
                self.handle_remove(user_id, media_id, call)
            
            # Handle existing navigation buttons
            elif callback_data == self.CALLBACK_STOP:
                self.db.reset_user_session(user_id)
                try:
                    self.bot.edit_message_text(
                        chat_id=user_id,
                        message_id=call.message.message_id,
                        text=self.get_text('search_stopped', call.message),
                        parse_mode='HTML'
                    )
                except:
                    self.bot.send_message(
                        user_id,
                        self.get_text('search_stopped', call.message),
                        parse_mode='HTML'
                    )
                
            elif callback_data == self.CALLBACK_NEW_SEARCH:
                self.db.reset_user_session(user_id)
                try:
                    self.bot.edit_message_text(
                        chat_id=user_id,
                        message_id=call.message.message_id,
                        text=self.get_text('ready_for_search', call.message),
                        parse_mode='HTML'
                    )
                except:
                    self.bot.send_message(
                        user_id,
                        self.get_text('ready_for_search', call.message),
                        parse_mode='HTML'
                    )
                
            elif callback_data == self.CALLBACK_NEXT:
                # Handle next batch
                self.handle_next_batch(call)
            
            # Handle language selection
            elif callback_data.startswith(self.CALLBACK_LANGUAGE):
                lang_code = callback_data.replace(self.CALLBACK_LANGUAGE, '')
                self.handle_language_selection(call, user_id, lang_code)
            
            elif callback_data.startswith(self.CALLBACK_MORE_INFO):
                # Handle more info request
                media_id = int(callback_data.replace(self.CALLBACK_MORE_INFO, ''))
                self.show_media_info(user_id, media_id, call.message)
    
    def handle_download(self, user_id: int, media_id: int, call):
        """Handle download button - send original file."""
        try:
            # Get media info from database
            cursor = self.db.connection.cursor(dictionary=True)
            cursor.execute("""
                SELECT * FROM downloaded_images WHERE id = %s
            """, (media_id,))
            media = cursor.fetchone()
            
            if not media or not media.get('local_path') or not Path(media['local_path']).exists():
                self.bot.answer_callback_query(
                    call.id,
                    text=self.get_text('file_not_found_server', call.message),
                    show_alert=True
                )
                return
            
            # Send original file
            file_path = media['local_path']
            file_name = media['file_name']
            file_type = media.get('image_type', 'image')
            
            with open(file_path, 'rb') as f:
                if file_type == 'video':
                    self.bot.send_video(
                        user_id,
                        f,
                        caption=self.get_text('downloaded_file', call.message, filename=file_name),
                        parse_mode='HTML'
                    )
                else:
                    self.bot.send_document(
                        user_id,
                        f,
                        caption=self.get_text('downloaded_file', call.message, filename=file_name),
                        visible_file_name=file_name,
                        parse_mode='HTML'
                    )
            
            # Acknowledge callback
            self.bot.answer_callback_query(
                call.id,
                text=self.get_text('file_sent', call.message),
                show_alert=False
            )
            
        except Exception as e:
            logger.error(f"Error downloading file {media_id}: {e}")
            self.bot.answer_callback_query(
                call.id,
                text=self.get_text('error_downloading', call.message),
                show_alert=True
            )
    
    def handle_share(self, user_id: int, media_id: int, call):
        """Handle share button - allows sharing original file."""
        try:
            # Get media info from database
            cursor = self.db.connection.cursor(dictionary=True)
            cursor.execute("""
                SELECT * FROM downloaded_images WHERE id = %s
            """, (media_id,))
            media = cursor.fetchone()
            
            if not media or not media.get('local_path') or not Path(media['local_path']).exists():
                self.bot.answer_callback_query(
                    call.id,
                    text=self.get_text('file_not_found_server', call.message),
                    show_alert=True
                )
                return
            
            file_name = media['file_name']
            
            # Create share keyboard
            share_keyboard = types.InlineKeyboardMarkup()
            
            # This will open the chat selector and insert the text into input field
            share_button = types.InlineKeyboardButton(
                self.get_text('choose_chat_button', call.message),
                switch_inline_query=self.get_text('share_inline_text', call.message, filename=file_name)
            )
            share_keyboard.add(share_button)
            
            # Send instructions
            self.bot.send_message(
                user_id,
                self.get_text('share_instructions', call.message, filename=file_name),
                parse_mode='HTML',
                reply_markup=share_keyboard
            )
            
            # Acknowledge callback
            self.bot.answer_callback_query(
                call.id,
                text=self.get_text('select_chat', call.message),
                show_alert=False
            )
            
        except Exception as e:
            logger.error(f"Error sharing file {media_id}: {e}")
            self.bot.answer_callback_query(
                call.id,
                text=self.get_text('error_sharing', call.message),
                show_alert=True
            )
    
    def handle_remove(self, user_id: int, media_id: int, call):
        """Handle remove button - delete the message with image and action buttons."""
        try:
            # Get the message that contains the action buttons
            action_message_id = call.message.message_id
            
            # Delete action buttons message
            self.bot.delete_message(user_id, action_message_id)
            
            # Try to delete the image message (previous message)
            try:
                self.bot.delete_message(user_id, action_message_id - 1)
            except Exception as e:
                logger.info(f"Could not delete image message: {e}")
            
            # Acknowledge callback
            self.bot.answer_callback_query(
                call.id,
                text=self.get_text('message_deleted', call.message),
                show_alert=False
            )
            
        except Exception as e:
            logger.error(f"Error removing message: {e}")
            self.bot.answer_callback_query(
                call.id,
                text=self.get_text('error_deleting', call.message),
                show_alert=True
            )
    
    def handle_next_batch(self, call):
        """Handle next batch button."""
        user_id = self._get_user_id_from_message(call)
        session = self.db.get_user_session(user_id)
        
        if not session or not session.get('current_search_cache_id'):
            self.bot.edit_message_text(
                chat_id=user_id,
                message_id=call.message.message_id,
                text=self.get_text('session_expired', call.message),
                parse_mode='HTML'
            )
            return
        
        # Get next batch of unsent images
        next_items = self.db.get_unsent_images(
            session['current_search_cache_id'],
            self.batch_size,
            session['current_offset']
        )
        
        if not next_items:
            self.bot.edit_message_text(
                chat_id=user_id,
                message_id=call.message.message_id,
                text=self.get_text('no_more_images', call.message),
                parse_mode='HTML'
            )
            return
        
        # Update offset
        new_offset = session['current_offset'] + len(next_items)
        self.db.update_user_session(
            user_id=user_id,
            offset=new_offset
        )
        
        # Calculate batches
        current_batch = (new_offset - len(next_items)) // self.batch_size + 1
        total_batches = (session['total_images'] + self.batch_size - 1) // self.batch_size
        
        # Delete callback message
        try:
            self.bot.delete_message(user_id, call.message.message_id)
        except:
            pass
        
        # Send next batch
        self.send_media_batch(
            user_id,
            next_items,
            current_batch,
            total_batches,
            session['current_search_cache_id'],
            call.message
        )
    
    def handle_language_selection(self, call, user_id: int, lang_code: str):
        """Handle language selection."""
        if self.localization.set_user_language(user_id, lang_code):
            # Update user's language in database
            self.db.update_user_language(user_id, lang_code)
            
            # Get language name in the selected language
            lang_name = self.localization.get_language_name(lang_code, in_own_language=True)
            
            try:
                self.bot.edit_message_text(
                    chat_id=user_id,
                    message_id=call.message.message_id,
                    text=self.get_text('language_changed', call.message, language=lang_name),
                    parse_mode='HTML'
                )
            except:
                self.bot.send_message(
                    user_id,
                    self.get_text('language_changed', call.message, language=lang_name),
                    parse_mode='HTML'
                )
        else:
            try:
                self.bot.edit_message_text(
                    chat_id=user_id,
                    message_id=call.message.message_id,
                    text=self.get_text('language_unsupported', call.message),
                    parse_mode='HTML'
                )
            except:
                self.bot.send_message(
                    user_id,
                    self.get_text('language_unsupported', call.message),
                    parse_mode='HTML'
                )
    
    def handle_url(self, message, url: str):
        """Handle URL input - uses gallery-dl for ALL URLs."""
        user_id = self._get_user_id_from_message(message)
        
        # Send initial status
        status_msg = self.bot.reply_to(
            message,
            self.get_text('processing_url', message, url=url),
            parse_mode='HTML'
        )
        
        # Check cache first
        cached_search = self.db.get_cached_search(user_id, url)
        search_cache_id = None
        media_items = []
        
        if cached_search:
            search_cache_id = cached_search['id']
            logger.info(f"Found cached URL for user {user_id}: {url}")
            
            # Get total count from database
            total_items = self.db.get_total_images_count(search_cache_id)
            
            # Get first batch
            media_items = self.db.get_unsent_images(
                search_cache_id,
                self.batch_size,
                0
            )
            
            # Initialize session
            self.db.update_user_session(
                user_id=user_id,
                search_cache_id=search_cache_id,
                offset=len(media_items),
                total_images=total_items,
                last_query=url,
                last_message_id=status_msg.message_id
            )
        
        # If no cache or no items, download new ones
        if not media_items:
            try:
                self.bot.edit_message_text(
                    chat_id=user_id,
                    message_id=status_msg.message_id,
                    text=self.get_text('downloading_url', message, url=url),
                    parse_mode='HTML'
                )
            except:
                pass
            
            # Use gallery-dl for ALL URLs (including Pinterest)
            downloaded = self.gallery_downloader.download_from_url(url, Config.MAX_IMAGES_PER_REQUEST)

            if downloaded:
                logger.info(f"Downloaded {len(downloaded)} items")
                for item in downloaded:
                    logger.info(f"Item: {item.get('file_name')} - path exists: {Path(item.get('local_path', '')).exists()}")
            else:
                logger.warning("No items downloaded")
            
            if not downloaded:
                try:
                    self.bot.edit_message_text(
                        chat_id=user_id,
                        message_id=status_msg.message_id,
                        text=self.get_text('no_media_from_url', message),
                        parse_mode='HTML'
                    )
                except:
                    self.bot.reply_to(
                        message,
                        self.get_text('no_media_from_url', message),
                        parse_mode='HTML'
                    )
                return
            
            # Create cache entry if needed
            if not cached_search:
                normalized = self.db.normalize_query(url)
                query_md5 = self.db.get_query_md5(url)
                search_cache_id = self.db.create_search_cache(
                    user_id, url, normalized, query_md5
                )
            
            if search_cache_id:
                # Save downloaded items
                saved = self.db.save_images_to_cache(search_cache_id, downloaded)
                logger.info(f"Saved {saved} items to cache for URL {search_cache_id}")
                
                # Get final total count
                total_items = self.db.get_total_images_count(search_cache_id)
                
                # Update cache with final total
                self.db.update_search_cache_total(search_cache_id, total_items)
                
                # Get first batch
                media_items = self.db.get_unsent_images(search_cache_id, self.batch_size, 0)
                
                # Initialize session
                self.db.update_user_session(
                    user_id=user_id,
                    search_cache_id=search_cache_id,
                    offset=len(media_items),
                    total_images=total_items,
                    last_query=url,
                    last_message_id=status_msg.message_id
                )
        
        if not media_items:
            try:
                self.bot.edit_message_text(
                    chat_id=user_id,
                    message_id=status_msg.message_id,
                    text=self.get_text('no_media_available', message),
                    parse_mode='HTML'
                )
            except:
                self.bot.reply_to(
                    message,
                    self.get_text('no_media_available', message),
                    parse_mode='HTML'
                )
            return
        
        # Delete status message
        try:
            self.bot.delete_message(user_id, status_msg.message_id)
        except:
            pass
        
        # Get session
        session = self.db.get_user_session(user_id)
        
        # Send first batch
        self.send_media_batch(
            user_id,
            media_items,
            current_batch=1,
            total_batches=(session['total_images'] + self.batch_size - 1) // self.batch_size,
            search_cache_id=search_cache_id,
            message=message
        )
    
    def process_search(self, message, query):
        """Process search query - uses pinterest-dl for text searches."""
        user = message.from_user
        user_id = self._get_user_id_from_message(message)
        
        # Send initial status
        status_msg = self.bot.reply_to(
            message,
            self.get_text('searching', message, query=query),
            parse_mode='HTML'
        )
        
        # Check cache
        cached_search = self.db.get_cached_search(user_id, query)
        search_cache_id = None
        media_items = []
        
        if cached_search:
            search_cache_id = cached_search['id']
            logger.info(f"Found cached search for user {user_id}: {query}")
            
            # Get total count from database
            total_items = self.db.get_total_images_count(search_cache_id)
            
            # Get first batch
            media_items = self.db.get_unsent_images(
                search_cache_id,
                self.batch_size,
                0
            )
            
            # Initialize session
            self.db.update_user_session(
                user_id=user_id,
                search_cache_id=search_cache_id,
                offset=len(media_items),
                total_images=total_items,
                last_query=query,
                last_message_id=status_msg.message_id
            )
        
        # If no cache or no items, download new ones
        if not media_items:
            try:
                self.bot.edit_message_text(
                    chat_id=user_id,
                    message_id=status_msg.message_id,
                    text=self.get_text('downloading', message, query=query),
                    parse_mode='HTML'
                )
            except:
                pass
            
            # Use pinterest-dl for search queries
            downloaded = self.pinterest_downloader.download_images(
                query,
                Config.MAX_IMAGES_PER_REQUEST,
                include_videos=Config.INCLUDE_VIDEO
            )
            
            if not downloaded:
                try:
                    self.bot.edit_message_text(
                        chat_id=user_id,
                        message_id=status_msg.message_id,
                        text=self.get_text('no_images_found', message),
                        parse_mode='HTML'
                    )
                except:
                    self.bot.reply_to(
                        message,
                        self.get_text('no_images_found', message),
                        parse_mode='HTML'
                    )
                return
            
            # Create cache entry if needed
            if not cached_search:
                normalized = self.db.normalize_query(query)
                query_md5 = self.db.get_query_md5(query)
                search_cache_id = self.db.create_search_cache(
                    user_id, query, normalized, query_md5
                )
            
            if search_cache_id:
                # Save downloaded items
                saved = self.db.save_images_to_cache(search_cache_id, downloaded)
                logger.info(f"Saved {saved} items to cache for search {search_cache_id}")
                
                # Get final total count
                total_items = self.db.get_total_images_count(search_cache_id)
                
                # Update cache with final total
                self.db.update_search_cache_total(search_cache_id, total_items)
                
                # Get first batch
                media_items = self.db.get_unsent_images(search_cache_id, self.batch_size, 0)
                
                # Initialize session
                self.db.update_user_session(
                    user_id=user_id,
                    search_cache_id=search_cache_id,
                    offset=len(media_items),
                    total_images=total_items,
                    last_query=query,
                    last_message_id=status_msg.message_id
                )
        
        if not media_items:
            try:
                self.bot.edit_message_text(
                    chat_id=user_id,
                    message_id=status_msg.message_id,
                    text=self.get_text('no_images_available', message),
                    parse_mode='HTML'
                )
            except:
                self.bot.reply_to(
                    message,
                    self.get_text('no_images_available', message),
                    parse_mode='HTML'
                )
            return
        
        # Delete status message
        try:
            self.bot.delete_message(user_id, status_msg.message_id)
        except:
            pass
        
        # Get session
        session = self.db.get_user_session(user_id)
        
        # Send first batch
        self.send_media_batch(
            user_id,
            media_items,
            current_batch=1,
            total_batches=(session['total_images'] + self.batch_size - 1) // self.batch_size,
            search_cache_id=search_cache_id,
            message=message
        )
    
    def send_media_batch(self, user_id, media_items, current_batch, total_batches, 
                    search_cache_id, message=None):
        """Send a batch of media (images and videos) to user with action buttons."""
        if not media_items:
            self.bot.send_message(
                user_id,
                self.get_text('no_more_images', message, user_id=user_id),
                parse_mode='HTML'
            )
            return
        
        # Create temporary message for localization if needed
        if message is None:
            class TempMessage:
                def __init__(self, user_id):
                    self.from_user = type('obj', (object,), {'id': user_id, 'language_code': None})
            message = TempMessage(user_id)
        
        # Send batch info
        self.bot.send_message(
            user_id,
            self.get_text(
                'batch_info', message,
                current=current_batch,
                total=total_batches,
                count=len(media_items)
            ),
            parse_mode='HTML'
        )
        
        for item in media_items:
            video_sent = False
            max_attempts = 2
            
            for attempt in range(max_attempts):
                try:
                    # Determine which file to send (preview for display)
                    file_type = item.get('image_type', 'image')
                    
                    # For display, use preview if available (to save bandwidth)
                    display_file = None
                    if file_type == 'image' and Config.PREVIEW_ENABLED and item.get('preview_path'):
                        preview_path = item['preview_path']
                        if Path(preview_path).exists():
                            display_file = preview_path
                            logger.info(f"Sending preview: {preview_path}")
                    
                    # Fallback to original if preview missing or not available
                    if not display_file:
                        display_file = item['local_path']
                    
                    # Get original file path for download/share
                    original_file = item['local_path']
                    file_name = item['file_name']
                    
                    if not display_file or not Path(display_file).exists():
                        # If file not found, send download link
                        base_url = os.getenv('BASE_URL', 'http://localhost:8000')
                        download_link = f"{base_url}/download/{item['id']}/{file_name}"
                        
                        self.bot.send_message(
                            user_id,
                            self.get_text('file_not_found_with_link', message, 
                                         filename=file_name, link=download_link),
                            parse_mode='HTML'
                        )
                        break
                    
                    # Get file size for caption
                    file_size = os.path.getsize(display_file) if Path(display_file).exists() else 0
                    
                    # Create caption with metadata
                    caption_parts = []
                    if item.get('caption'):
                        caption_parts.append(item['caption'][:100])
                    
                    if file_type == 'video':
                        # Add video info
                        info = []
                        if item.get('width') and item.get('height') and item['width'] > 0 and item['height'] > 0:
                            info.append(f"{item['width']}x{item['height']}")
                        if item.get('duration') and item['duration'] > 0:
                            info.append(self.format_duration(item['duration']))
                        if info:
                            caption_parts.append(f"📹 {' • '.join(info)}")
                    elif file_type == 'image':
                        # Add image info
                        if item.get('width') and item.get('height') and item['width'] > 0 and item['height'] > 0:
                            caption_parts.append(f"🖼️ {item['width']}x{item['height']}")
                        if display_file != original_file:
                            caption_parts.append("🔍 Preview")
                    
                    # Add file size
                    if file_size > 0:
                        caption_parts.append(f"💾 {self.format_file_size(file_size)}")
                    
                    caption = ' | '.join(caption_parts) if caption_parts else None
                    
                    # Create action buttons for this specific media
                    media_id = item['id']
                    
                    # Create inline keyboard with action buttons
                    action_keyboard = types.InlineKeyboardMarkup(row_width=3)
                    
                    # Download button - sends the original file
                    download_btn = types.InlineKeyboardButton(
                        self.get_text('download_button', message),
                        callback_data=f"download_{media_id}"
                    )
                    
                    # Share button - shares the original file
                    share_btn = types.InlineKeyboardButton(
                        self.get_text('share_button', message),
                        callback_data=f"share_{media_id}"
                    )
                    
                    # Remove button - deletes this message
                    remove_btn = types.InlineKeyboardButton(
                        self.get_text('remove_button', message),
                        callback_data=f"remove_{media_id}"
                    )
                    
                    # Add buttons to keyboard (all in one row)
                    action_keyboard.add(download_btn, share_btn, remove_btn)
                    
                    # Send the media based on type
                    if file_type == 'video':
                        try:
                            # First verify the file is readable
                            if not os.access(display_file, os.R_OK):
                                logger.error(f"Video file not readable: {display_file}")
                                raise IOError(f"File not readable: {display_file}")
                            
                            # Log file details for debugging
                            logger.info(f"Attempting to send video: {display_file}, size: {file_size} bytes")
                            
                            # Open file and send with increased timeout
                            with open(display_file, 'rb') as media_file:
                                # Read a small chunk to verify file is OK
                                media_file.read(1)
                                media_file.seek(0)
                                
                                sent_msg = self.bot.send_video(
                                    user_id,
                                    media_file,
                                    width=item.get('width') if item.get('width') and item['width'] > 0 else None,
                                    height=item.get('height') if item.get('height') and item['height'] > 0 else None,
                                    duration=int(item.get('duration')) if item.get('duration') and item['duration'] > 0 else None,
                                    supports_streaming=True,
                                    caption=caption,
                                    reply_markup=action_keyboard,
                                    timeout=60  # Increase timeout
                                )
                            
                            video_sent = True
                            logger.info(f"Successfully sent video: {display_file}")
                            
                        except Exception as e:
                            logger.error(f"Error sending video (attempt {attempt + 1}/{max_attempts}): {e}")
                            
                            if attempt == max_attempts - 1:  # Last attempt
                                # Try to send as document instead
                                try:
                                    logger.info(f"Attempting to send as document instead: {display_file}")
                                    with open(display_file, 'rb') as media_file:
                                        sent_msg = self.bot.send_document(
                                            user_id,
                                            media_file,
                                            visible_file_name=file_name,
                                            caption=f"🎥 Video (send as file):\n{caption}" if caption else "🎥 Video",
                                            reply_markup=action_keyboard,
                                            timeout=60
                                        )
                                    video_sent = True
                                    logger.info(f"Successfully sent video as document: {display_file}")
                                except Exception as doc_error:
                                    logger.error(f"Error sending as document: {doc_error}")
                                    # Send just the link as last resort
                                    base_url = os.getenv('BASE_URL', 'http://localhost:8000')
                                    download_link = f"{base_url}/download/{item['id']}/{file_name}"
                                    self.bot.send_message(
                                        user_id,
                                        self.get_text('failed_to_send_with_link', message, 
                                                     filename=file_name, link=download_link),
                                        parse_mode='HTML'
                                    )
                            else:
                                # Wait before retry
                                time.sleep(2)
                                continue
                        
                    else:
                        # Send as photo
                        with open(display_file, 'rb') as media_file:
                            sent_msg = self.bot.send_photo(
                                user_id,
                                media_file,
                                caption=caption,
                                reply_markup=action_keyboard,
                                timeout=30
                            )
                        video_sent = True
                    
                    if video_sent:
                        # Store message info for later reference (for remove button)
                        self.store_message_info(user_id, sent_msg.message_id, media_id, original_file)
                        break  # Exit retry loop on success
                    
                except Exception as e:
                    logger.error(f"Error in send_media_batch: {e}")
                    if attempt == max_attempts - 1:
                        # Final attempt failed, send error message
                        base_url = os.getenv('BASE_URL', 'http://localhost:8000')
                        relative_path = get_last_n_parts(item.get('local_path', 'unknown'))
                        download_link = f"{base_url}/{relative_path}"
                        
                        self.bot.send_message(
                            user_id,
                            self.get_text('failed_to_send_with_link', message, 
                                         filename=file_name, link=download_link),
                            parse_mode='HTML'
                        )
                    else:
                        time.sleep(2)  # Wait before retry
            
            time.sleep(0.5)  # Delay between items to avoid flooding
        
        # Get updated session
        session = self.db.get_user_session(user_id)
        
        # Create navigation keyboard
        keyboard = types.InlineKeyboardMarkup()
        nav_msg = self.get_text('show_complete', message)
        
        # Calculate if there are more items to show
        if session:
            current_offset = session['current_offset']
            total_items = session['total_images']
            
            # Add Next button if there are more items
            if current_offset < total_items:
                remaining = total_items - current_offset
                next_count = min(self.batch_size, remaining)
                keyboard.add(types.InlineKeyboardButton(
                    self.get_text('next', message, count=next_count),
                    callback_data=self.CALLBACK_NEXT
                ))
                
                progress_text = self.get_text('progress', message, current=current_offset, total=total_items)
                progress_text += f"\n{self.get_text('more_available', message, count=remaining)}"
            
                nav_msg = (
                    f"{self.get_text('what_next', message)}\n\n"
                    f"{progress_text}"
                )
                
        self.bot.send_message(
            user_id,
            nav_msg,
            parse_mode='HTML',
            reply_markup=keyboard
        )
    
    def show_media_info(self, user_id: int, media_id: int, message):
        """Show detailed information about a media item."""
        # Get media info from database
        cursor = self.db.connection.cursor(dictionary=True)
        cursor.execute("""
            SELECT * FROM downloaded_images WHERE id = %s
        """, (media_id,))
        media = cursor.fetchone()
        
        if not media:
            self.bot.send_message(
                user_id,
                self.get_text('file_not_found', message, filename='unknown')
            )
            return
        
        media_type = media.get('image_type', 'image')
        type_emoji = '🎥' if media_type == 'video' else '🖼️'
        
        info_text = f"<b>{self.get_text('media_info_title', message)}</b>\n"
        info_text += f"{self.get_text('media_type_label', message)}: {type_emoji} {'Video' if media_type == 'video' else 'Image'}\n"
        info_text += f"{self.get_text('media_file_label', message)}: {media['file_name']}\n"
        info_text += f"{self.get_text('media_size_label', message)}: {self.format_file_size(media['file_size'])}\n"
        
        if media.get('width') and media.get('height') and media['width'] > 0 and media['height'] > 0:
            info_text += f"{self.get_text('media_resolution_label', message)}: {media['width']}x{media['height']}\n"
        
        if media_type == 'video' and media.get('duration') and media['duration'] > 0:
            info_text += f"{self.get_text('media_duration_label', message)}: {self.format_duration(media['duration'])}\n"
        
        if media.get('caption'):
            info_text += f"\n{self.get_text('media_caption_label', message)}: {media['caption'][:200]}"
        
        self.bot.send_message(
            user_id,
            info_text,
            parse_mode='HTML'
        )
    
    def run(self):
        """Run the bot."""
        logger.info("Starting Pinterest Bot with video support and URL downloads...")
        print("\n" + "="*50)
        print("🤖 Pinterest Image & Video Bot Started")
        print("="*50)
        print(f"Bot Token: {Config.BOT_TOKEN[:10]}...")
        print(f"Items per batch: {self.batch_size}")
        print(f"Supported languages: {', '.join(self.localization.LANGUAGES.values())}")
        if Config.INCLUDE_VIDEO:
            print(f"Video support: ✅ Enabled")
        print(f"URL support: ✅ Enabled (gallery-dl)")
        print("="*50 + "\n")
        
        # Cleanup old downloads periodically
        if hasattr(self, 'gallery_downloader'):
            self.gallery_downloader.cleanup_old_downloads()
        
        self.bot.infinity_polling()
    
    def __del__(self):
        """Cleanup on deletion."""
        if hasattr(self, 'db'):
            self.db.close()