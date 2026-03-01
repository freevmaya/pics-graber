# ============================================================
# FILE: bot_telebot.py (COMPLETE - FIXED SESSION MANAGEMENT)
# TYPE: .PY
# ============================================================

"""Telegram bot using pyTelegramBotAPI with video support."""

import telebot
from telebot import types
import logging
from typing import Optional, Dict, List
from pathlib import Path
import time
from datetime import datetime
import html
import os

from config import Config
from database import DatabaseManager
from pinterest_downloader import PinterestDownloader
from localization import LocalizationManager

# Setup logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

class PinterestBot:
    """Main bot class with video support."""
    
    # Constants
    CALLBACK_NEXT = "next"
    CALLBACK_STOP = "stop"
    CALLBACK_NEW_SEARCH = "new_search"
    CALLBACK_LANGUAGE = "lang_"
    CALLBACK_MORE_INFO = "more_info_"
    
    # File size limits (Telegram limits)
    MAX_PHOTO_SIZE = 10 * 1024 * 1024  # 10 MB for photos
    MAX_VIDEO_SIZE = 50 * 1024 * 1024  # 50 MB for videos
    
    def __init__(self):
        """Initialize bot components."""
        self.config = Config()
        self.db = DatabaseManager()
        self.downloader = PinterestDownloader()
        self.localization = LocalizationManager()
        self.batch_size = Config.IMAGES_PER_BATCH
        self.bot = telebot.TeleBot(Config.BOT_TOKEN)
        
        # Check pinterest-dl
        if not PinterestDownloader.check_pinterest_dl():
            logger.warning("pinterest-dl not found. Please install it: pip install pinterest-dl")
        
        # Register handlers
        self.register_handlers()
    
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
    
    def register_handlers(self):
        """Register message and callback handlers."""
        
        @self.bot.message_handler(commands=['start'])
        def start_command(message):
            user = message.from_user
            self.db.register_user(
                user_id=user.id,
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
            user_id = message.from_user.id
            self.db.reset_user_session(user_id)
            
            self.bot.reply_to(
                message,
                self.get_text('ready_for_search', message),
                parse_mode='HTML'
            )
        
        @self.bot.message_handler(commands=['stop'])
        def stop_command(message):
            user_id = message.from_user.id
            self.db.reset_user_session(user_id)
            
            self.bot.reply_to(
                message,
                self.get_text('search_stopped', message),
                parse_mode='HTML'
            )
        
        @self.bot.message_handler(func=lambda message: True)
        def handle_message(message):
            user = message.from_user
            query = message.text.strip()
            
            if not query:
                self.bot.reply_to(
                    message,
                    self.get_text('empty_query', message)
                )
                return
            
            # Register/update user
            self.db.register_user(
                user_id=user.id,
                username=user.username,
                first_name=user.first_name,
                last_name=user.last_name,
                language_code=self.localization.get_user_language(message)
            )
            
            # Send initial status
            status_msg = self.bot.reply_to(
                message,
                self.get_text('searching', message, query=query),
                parse_mode='HTML'
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
                    text=self.get_text('search_stopped', call.message),
                    parse_mode='HTML'
                )
                
            elif callback_data == self.CALLBACK_NEW_SEARCH:
                self.db.reset_user_session(user_id)
                self.bot.edit_message_text(
                    chat_id=user_id,
                    message_id=call.message.message_id,
                    text=self.get_text('ready_for_search', call.message),
                    parse_mode='HTML'
                )
                
            elif callback_data == self.CALLBACK_NEXT:
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
                
                # Update offset (total_images remains the same!)
                new_offset = session['current_offset'] + len(next_items)
                self.db.update_user_session(
                    user_id=user_id,
                    offset=new_offset
                )
                
                # Calculate batches using original total_images
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
                    call.message  # Pass original message for localization
                )
            
            elif callback_data.startswith(self.CALLBACK_LANGUAGE):
                # Handle language selection
                lang_code = callback_data.replace(self.CALLBACK_LANGUAGE, '')
                
                if self.localization.set_user_language(user_id, lang_code):
                    # Update user's language in database
                    self.db.update_user_language(user_id, lang_code)
                    
                    # Get language name in the selected language
                    lang_name = self.localization.get_language_name(lang_code, in_own_language=True)
                    
                    self.bot.edit_message_text(
                        chat_id=user_id,
                        message_id=call.message.message_id,
                        text=self.get_text('language_changed', call.message, language=lang_name),
                        parse_mode='HTML'
                    )
                else:
                    self.bot.edit_message_text(
                        chat_id=user_id,
                        message_id=call.message.message_id,
                        text=self.get_text('language_unsupported', call.message),
                        parse_mode='HTML'
                    )
            
            elif callback_data.startswith(self.CALLBACK_MORE_INFO):
                # Handle more info request
                media_id = int(callback_data.replace(self.CALLBACK_MORE_INFO, ''))
                self.show_media_info(user_id, media_id, call.message)
    
    def process_search(self, message, query, status_msg):
        """Process search query and initialize session with FIXED total_images."""
        user = message.from_user
        
        # Check cache
        cached_search = self.db.get_cached_search(user.id, query)
        search_cache_id = None
        media_items = []
        
        if cached_search:
            search_cache_id = cached_search['id']
            logger.info(f"Found cached search for user {user.id}: {query}")
            
            # Get total count from database (fixed for this session)
            total_items = self.db.get_total_images_count(search_cache_id)
            
            # Get first batch
            media_items = self.db.get_unsent_images(
                search_cache_id,
                self.batch_size,
                0
            )
            
            # Initialize session with FIXED total_images
            self.db.update_user_session(
                user_id=user.id,
                search_cache_id=search_cache_id,
                offset=len(media_items),
                total_images=total_items,  # THIS NUMBER WON'T CHANGE DURING SESSION
                last_query=query,
                last_message_id=status_msg.message_id
            )
        
        # If no cache or no items, download new ones
        if not media_items:
            try:
                self.bot.edit_message_text(
                    chat_id=user.id,
                    message_id=status_msg.message_id,
                    text=self.get_text('downloading', message, query=query),
                    parse_mode='HTML'
                )
            except:
                pass
            
            # Download media (including videos)
            downloaded = self.downloader.download_images(
                query,
                Config.MAX_IMAGES_PER_REQUEST,
                include_videos=Config.INCLUDE_VIDEO
            )
            
            if not downloaded:
                try:
                    self.bot.edit_message_text(
                        chat_id=user.id,
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
                    user.id, query, normalized, query_md5
                )
            
            if search_cache_id:
                # Save downloaded items
                saved = self.db.save_images_to_cache(search_cache_id, downloaded)
                logger.info(f"Saved {saved} items to cache for search {search_cache_id}")
                
                # Get FINAL total count (fixed for this session)
                total_items = self.db.get_total_images_count(search_cache_id)
                
                # Update cache with final total
                self.db.update_search_cache_total(search_cache_id, total_items)
                
                # Get first batch
                media_items = self.db.get_unsent_images(search_cache_id, self.batch_size, 0)
                
                # Initialize session with FIXED total_images
                self.db.update_user_session(
                    user_id=user.id,
                    search_cache_id=search_cache_id,
                    offset=len(media_items),
                    total_images=total_items,  # THIS NUMBER WON'T CHANGE DURING SESSION
                    last_query=query,
                    last_message_id=status_msg.message_id
                )
        
        if not media_items:
            try:
                self.bot.edit_message_text(
                    chat_id=user.id,
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
            self.bot.delete_message(user.id, status_msg.message_id)
        except:
            pass
        
        # Get session (already has fixed total_images)
        session = self.db.get_user_session(user.id)
        
        # Send first batch
        self.send_media_batch(
            user.id,
            media_items,
            current_batch=1,
            total_batches=(session['total_images'] + self.batch_size - 1) // self.batch_size,
            search_cache_id=search_cache_id,
            message=message
        )
    
    def send_media_batch(self, user_id, media_items, current_batch, total_batches, 
                        search_cache_id, message=None):
        """Send a batch of media (images and videos) to user."""
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
        
        # Send media items
        sent_ids = []
        
        for item in media_items:
            try:
                # Determine which file to send (preview for images if available)
                file_to_send = None
                file_type = item.get('image_type', 'image')
                
                if file_type == 'image' and Config.PREVIEW_ENABLED and item.get('preview_path'):
                    # Send preview for images
                    preview_path = item['preview_path']
                    if Path(preview_path).exists():
                        file_to_send = preview_path
                        file_size = os.path.getsize(preview_path)
                        logger.info(f"Sending preview: {preview_path}")
                    else:
                        # Fallback to original if preview missing
                        file_to_send = item['local_path']
                        file_size = os.path.getsize(file_to_send) if file_to_send and Path(file_to_send).exists() else 0
                else:
                    # Send original for videos or when preview disabled
                    file_to_send = item['local_path']
                    file_size = os.path.getsize(file_to_send) if file_to_send and Path(file_to_send).exists() else 0
                
                if not file_to_send or not Path(file_to_send).exists():
                    self.bot.send_message(
                        user_id,
                        self.get_text('file_not_found', message, filename=item.get('file_name', 'unknown'))
                    )
                    continue
                
                # Get media type
                media_type = item.get('image_type', 'image')
                
                # Create caption with metadata
                caption_parts = []
                if item.get('caption'):
                    caption_parts.append(item['caption'][:100])
                
                if media_type == 'video':
                    # Add video info
                    info = []
                    if item.get('width') and item.get('height') and item['width'] > 0 and item['height'] > 0:
                        info.append(f"{item['width']}x{item['height']}")
                    if item.get('duration') and item['duration'] > 0:
                        info.append(self.format_duration(item['duration']))
                    if info:
                        caption_parts.append(f"📹 {' • '.join(info)}")
                elif media_type == 'image' and Config.PREVIEW_ENABLED and item.get('preview_path'):
                    # Add preview indicator to caption
                    if item.get('width') and item.get('height') and item['width'] > 0 and item['height'] > 0:
                        caption_parts.append(f"🖼️ {item['width']}x{item['height']}")
                    caption_parts.append("🔍 Preview")
                
                # Add file size
                if file_size > 0:
                    caption_parts.append(f"💾 {self.format_file_size(file_size)}")
                
                caption = ' | '.join(caption_parts) if caption_parts else None
                
                # Send based on type and size
                with open(file_to_send, 'rb') as media_file:
                    if media_type == 'video':
                        # Send as video
                        if file_size <= self.MAX_VIDEO_SIZE:
                            self.bot.send_video(
                                user_id,
                                media_file,
                                caption=caption,
                                width=item.get('width') if item.get('width') and item['width'] > 0 else None,
                                height=item.get('height') if item.get('height') and item['height'] > 0 else None,
                                duration=int(item.get('duration')) if item.get('duration') and item['duration'] > 0 else None,
                                supports_streaming=True
                            )
                        else:
                            # Video too large, send as document
                            self.bot.send_document(
                                user_id,
                                media_file,
                                caption=f"🎥 Video (large) - {caption}" if caption else "🎥 Video (large)",
                                visible_file_name=item['file_name']
                            )
                    else:
                        # Send as photo (using preview or original)
                        if file_size <= self.MAX_PHOTO_SIZE:
                            self.bot.send_photo(
                                user_id,
                                media_file,
                                caption=caption
                            )
                        else:
                            # Image too large, send as document
                            self.bot.send_document(
                                user_id,
                                media_file,
                                caption=f"🖼️ Image (large) - {caption}" if caption else "🖼️ Image (large)",
                                visible_file_name=item['file_name']
                            )
                
                sent_ids.append(item['id'])
                time.sleep(0.5)  # Delay to avoid flooding
                
            except Exception as e:
                logger.error(f"Error sending media: {e}")
                self.bot.send_message(
                    user_id,
                    self.get_text('failed_to_send', message, filename=item.get('file_name', 'unknown'))
                )
        
        # Mark successfully sent images
        if sent_ids:
            self.db.mark_images_as_sent(sent_ids)
        
        # Get updated session
        session = self.db.get_user_session(user_id)
        
        # Create navigation keyboard
        keyboard = types.InlineKeyboardMarkup()
        
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
        
        # Always add Stop and New Search buttons
        keyboard.add(
            types.InlineKeyboardButton(
                self.get_text('new_search', message),
                callback_data=self.CALLBACK_NEW_SEARCH
            )
        )
        
        # Send navigation message
        current = session['current_offset'] if session else len(media_items)
        total = session['total_images'] if session else len(media_items)
        
        progress_text = self.get_text('progress', message, current=current, total=total)
        
        # Add remaining count if there are more
        if session and current < total:
            remaining = total - current
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
        
        info_text = f"<b>Media Information:</b>\n"
        info_text += f"Type: {type_emoji} {'Video' if media_type == 'video' else 'Image'}\n"
        info_text += f"File: {media['file_name']}\n"
        info_text += f"Size: {self.format_file_size(media['file_size'])}\n"
        
        if media.get('width') and media.get('height') and media['width'] > 0 and media['height'] > 0:
            info_text += f"Resolution: {media['width']}x{media['height']}\n"
        
        if media_type == 'video' and media.get('duration') and media['duration'] > 0:
            info_text += f"Duration: {self.format_duration(media['duration'])}\n"
        
        if media.get('caption'):
            info_text += f"\nCaption: {media['caption'][:200]}"
        
        self.bot.send_message(
            user_id,
            info_text,
            parse_mode='HTML'
        )
    
    def run(self):
        """Run the bot."""
        logger.info("Starting Pinterest Bot with video support...")
        print("\n" + "="*50)
        print("🤖 Pinterest Image & Video Bot Started")
        print("="*50)
        print(f"Bot Token: {Config.BOT_TOKEN[:10]}...")
        print(f"Items per batch: {self.batch_size}")
        print(f"Supported languages: {', '.join(self.localization.LANGUAGES.values())}")
        if Config.INCLUDE_VIDEO:
            print(f"Video support: ✅ Enabled")
        print("="*50 + "\n")
        
        self.bot.infinity_polling()
    
    def __del__(self):
        """Cleanup on deletion."""
        if hasattr(self, 'db'):
            self.db.close()