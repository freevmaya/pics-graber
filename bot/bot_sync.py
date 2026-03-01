# ============================================================
# FILE: bot_sync.py (FIXED)
# TYPE: .PY
# ============================================================

"""Main Telegram bot module."""

import logging
from typing import Optional, Dict, List
from pathlib import Path
import asyncio
from datetime import datetime

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes
)
from telegram.constants import ParseMode

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
    """Main bot class."""
    
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
        self.application = None
        
        # Check pinterest-dl
        if not PinterestDownloader.check_pinterest_dl():
            logger.warning("pinterest-dl not found. Please install it: pip install pinterest-dl")
    
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command."""
        user = update.effective_user
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
        
        await update.message.reply_text(
            welcome_text,
            parse_mode=ParseMode.MARKDOWN
        )
    
    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /help command."""
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
            "• Download buttons for each image\n"
            "• Continue or stop anytime"
        )
        
        await update.message.reply_text(
            help_text,
            parse_mode=ParseMode.MARKDOWN
        )
    
    async def new_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /new command - reset search."""
        user_id = update.effective_user.id
        self.db.reset_user_session(user_id)
        
        await update.message.reply_text(
            "🆕 *Starting new search*\n"
            "Send me what you'd like to find!",
            parse_mode=ParseMode.MARKDOWN
        )
    
    async def stop_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /stop command."""
        user_id = update.effective_user.id
        self.db.reset_user_session(user_id)
        
        await update.message.reply_text(
            "⏹️ *Search stopped*\n"
            "Send a new query to start again!",
            parse_mode=ParseMode.MARKDOWN
        )
    
    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle user messages (search queries)."""
        user = update.effective_user
        query = update.message.text.strip()
        
        if not query:
            await update.message.reply_text("Please send a non-empty search query.")
            return
        
        # Register/update user
        self.db.register_user(
            user_id=user.id,
            username=user.username,
            first_name=user.first_name,
            last_name=user.last_name
        )
        
        # Send initial status
        status_msg = await update.message.reply_text(
            f"🔍 *Searching for:* {query}\n"
            "⏳ Please wait...",
            parse_mode=ParseMode.MARKDOWN
        )
        
        # Check cache
        cached_search = self.db.get_cached_search(user.id, query)
        search_cache_id = None
        images = []
        
        if cached_search:
            search_cache_id = cached_search['id']
            logger.info(f"Found cached search for user {user.id}: {query}")
            
            # Get unsent images from cache
            images = self.db.get_unsent_images(
                search_cache_id,
                self.batch_size,
                0
            )
        
        # If no cache or no images, download new ones
        if not images:
            await status_msg.edit_text(
                f"🔍 *Searching for:* {query}\n"
                "📥 Downloading images...",
                parse_mode=ParseMode.MARKDOWN
            )
            
            # Download images
            downloaded = self.downloader.download_images(
                query,
                Config.MAX_IMAGES_PER_REQUEST
            )
            
            if not downloaded:
                await status_msg.edit_text(
                    "❌ *No images found*\n"
                    "Please try a different search term.",
                    parse_mode=ParseMode.MARKDOWN
                )
                return
            
            # Save to cache
            if not cached_search:
                normalized = self.db.normalize_query(query)
                query_md5 = self.db.get_query_md5(query)
                search_cache_id = self.db.create_search_cache(
                    user.id, query, normalized, query_md5
                )
            
            if search_cache_id:
                saved = self.db.save_images_to_cache(search_cache_id, downloaded)
                logger.info(f"Saved {saved} images to cache for search {search_cache_id}")
                
                # Get first batch
                images = self.db.get_unsent_images(search_cache_id, self.batch_size, 0)
        
        if not images:
            await status_msg.edit_text(
                "❌ *No images available*\n"
                "Please try again later.",
                parse_mode=ParseMode.MARKDOWN
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
        await status_msg.delete()
        
        # Send images
        await self.send_image_batch(
            update, context,
            images,
            current_batch=1,
            total_batches=(total_images + self.batch_size - 1) // self.batch_size,
            search_cache_id=search_cache_id
        )
    
    async def send_image_batch(self, update: Update, context: ContextTypes.DEFAULT_TYPE,
                               images: List[Dict], current_batch: int, total_batches: int,
                               search_cache_id: int):
        """Send a batch of images to user."""
        user_id = update.effective_user.id
        
        if not images:
            await context.bot.send_message(
                chat_id=user_id,
                text="✨ *No more images*\n"
                     "Use /new to start another search!",
                parse_mode=ParseMode.MARKDOWN
            )
            return
        
        # Create keyboard
        keyboard = []
        
        # Add navigation buttons if there are more images
        session = self.db.get_user_session(user_id)
        if session and session['current_offset'] < session['total_images']:
            keyboard.append([
                InlineKeyboardButton(
                    f"▶️ Next {self.batch_size}",
                    callback_data=self.CALLBACK_NEXT
                )
            ])
        
        # Always add stop and new search buttons
        keyboard.append([
            InlineKeyboardButton("⏹️ Stop", callback_data=self.CALLBACK_STOP),
            InlineKeyboardButton("🆕 New Search", callback_data=self.CALLBACK_NEW_SEARCH)
        ])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        # Send batch info
        await context.bot.send_message(
            chat_id=user_id,
            text=(
                f"📸 *Batch {current_batch} of {total_batches}*\n"
                f"Showing {len(images)} images"
            ),
            parse_mode=ParseMode.MARKDOWN
        )
        
        # Send images
        image_ids = []
        for img in images:
            try:
                # Send photo
                if img['local_path'] and Path(img['local_path']).exists():
                    with open(img['local_path'], 'rb') as photo:
                        sent = await context.bot.send_photo(
                            chat_id=user_id,
                            photo=photo,
                            caption=img.get('caption', '')[:200] if img.get('caption') else None
                        )
                        image_ids.append(img['id'])
                else:
                    # Fallback to URL if local file doesn't exist
                    await context.bot.send_message(
                        chat_id=user_id,
                        text=f"⚠️ Image file not found: {img.get('file_name', 'unknown')}"
                    )
                
                # Small delay to avoid flooding
                await asyncio.sleep(0.5)
                
            except Exception as e:
                logger.error(f"Error sending image: {e}")
                await context.bot.send_message(
                    chat_id=user_id,
                    text=f"⚠️ Failed to send image: {img.get('file_name', 'unknown')}"
                )
        
        # Mark images as sent
        if image_ids:
            self.db.mark_images_as_sent(image_ids)
        
        # Send navigation message
        nav_msg = (
            f"*What would you like to do?*\n\n"
            f"📊 Progress: {session['current_offset'] if session else len(images)}/{session['total_images'] if session else len(images)}"
        )
        
        await context.bot.send_message(
            chat_id=user_id,
            text=nav_msg,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=reply_markup
        )
    
    async def handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle callback queries from inline keyboards."""
        query = update.callback_query
        await query.answer()
        
        user_id = update.effective_user.id
        callback_data = query.data
        
        if callback_data == self.CALLBACK_STOP:
            # Stop current search
            self.db.reset_user_session(user_id)
            await query.edit_message_text(
                text="⏹️ *Search stopped*\n"
                     "Use /new to start another search!",
                parse_mode=ParseMode.MARKDOWN
            )
            
        elif callback_data == self.CALLBACK_NEW_SEARCH:
            # Start new search
            self.db.reset_user_session(user_id)
            await query.edit_message_text(
                text="🆕 *Ready for new search*\n"
                     "Send me what you'd like to find!",
                parse_mode=ParseMode.MARKDOWN
            )
            
        elif callback_data == self.CALLBACK_NEXT:
            # Get next batch
            session = self.db.get_user_session(user_id)
            
            if not session or not session.get('current_search_cache_id'):
                await query.edit_message_text(
                    text="⚠️ *Session expired*\n"
                         "Please start a new search.",
                    parse_mode=ParseMode.MARKDOWN
                )
                return
            
            # Get next batch of unsent images
            next_images = self.db.get_unsent_images(
                session['current_search_cache_id'],
                self.batch_size,
                session['current_offset']
            )
            
            if not next_images:
                await query.edit_message_text(
                    text="✨ *No more images*\n"
                         "Use /new to start another search!",
                    parse_mode=ParseMode.MARKDOWN
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
            
            # Send next batch
            await self.send_image_batch(
                update, context,
                next_images,
                current_batch=current_batch,
                total_batches=total_batches,
                search_cache_id=session['current_search_cache_id']
            )
    
    async def error_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle errors."""
        logger.error(f"Update {update} caused error {context.error}")
        
        try:
            if update and update.effective_message:
                await update.effective_message.reply_text(
                    "❌ *An error occurred*\n"
                    "Please try again later.",
                    parse_mode=ParseMode.MARKDOWN
                )
        except:
            pass
    
    def run(self):
        """Run the bot."""
        # Create application
        self.application = Application.builder().token(Config.BOT_TOKEN).build()
        
        # Add handlers
        self.application.add_handler(CommandHandler("start", self.start_command))
        self.application.add_handler(CommandHandler("help", self.help_command))
        self.application.add_handler(CommandHandler("new", self.new_command))
        self.application.add_handler(CommandHandler("stop", self.stop_command))
        self.application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message))
        self.application.add_handler(CallbackQueryHandler(self.handle_callback))
        self.application.add_error_handler(self.error_handler)
        
        # Start bot
        logger.info("Starting Pinterest Bot...")
        print("\n" + "="*50)
        print("🤖 Pinterest Image Bot Started")
        print("="*50)
        print(f"Bot Token: {Config.BOT_TOKEN[:10]}...")
        print(f"Images per batch: {self.batch_size}")
        print(f"Max images per request: {Config.MAX_IMAGES_PER_REQUEST}")
        print("="*50 + "\n")
        
        self.application.run_polling(allowed_updates=Update.ALL_TYPES)
    
    def __del__(self):
        """Cleanup on deletion."""
        if hasattr(self, 'db'):
            self.db.close()