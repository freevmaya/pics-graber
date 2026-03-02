# ============================================================
# FILE: localization.py (FIXED)
# TYPE: .PY
# ============================================================

"""Localization module for Pinterest Bot using pyTelegramBotAPI."""

import json
from pathlib import Path
from typing import Dict, Optional
import telebot
from telebot import types

class LocalizationManager:
    """Manages bot localization with JSON language files."""
    
    # Supported languages
    LANGUAGES = {
        'en': 'English',
        'ru': 'Русский',
        'es': 'Español',
        'zh': '中文'
    }
    
    # Default language
    DEFAULT_LANGUAGE = 'en'
    
    def __init__(self, locales_dir: str = "locales"):
        """Initialize localization manager."""
        self.locales_dir = Path(__file__).parent / locales_dir
        self.translations: Dict[str, Dict[str, str]] = {}
        self.user_languages: Dict[int, str] = {}  # Cache user language preferences
        self.load_translations()
        
        # Print loaded translations for debugging
        print("\n📚 Loaded translations:")
        for lang_code in self.translations:
            print(f"  {lang_code}: {len(self.translations[lang_code])} keys")
    
    def load_translations(self):
        """Load all translation JSON files."""
        if not self.locales_dir.exists():
            self.locales_dir.mkdir(exist_ok=True)
            print(f"✓ Created locales directory: {self.locales_dir}")
        
        # First load English as default
        en_path = self.locales_dir / "en.json"
        if en_path.exists():
            with open(en_path, 'r', encoding='utf-8') as f:
                self.translations['en'] = json.load(f)
            print(f"✓ Loaded translations for en")
        else:
            print(f"⚠️ English translation file not found: {en_path}")
            self.translations['en'] = self._create_default_translations()
        
        # Load other languages
        for lang_code in self.LANGUAGES.keys():
            if lang_code == 'en':
                continue
                
            file_path = self.locales_dir / f"{lang_code}.json"
            try:
                if file_path.exists():
                    with open(file_path, 'r', encoding='utf-8') as f:
                        self.translations[lang_code] = json.load(f)
                    print(f"✓ Loaded translations for {lang_code}")
                else:
                    print(f"⚠️ Translation file not found: {file_path}")
                    # Create empty dict, will fall back to English
                    self.translations[lang_code] = {}
            except Exception as e:
                print(f"✗ Error loading {lang_code}.json: {e}")
                self.translations[lang_code] = {}
    
    def _create_default_translations(self) -> Dict[str, str]:
        """Create minimal default translations if file is missing."""
        return {
            "language_name": "English",
            "welcome": "👋 <b>Welcome, {name}!</b>",
            "help": "🤖 <b>Help</b>",
            "language_prompt": "🌐 <b>Select language:</b>",
            "language_changed": "✅ <b>Language changed!</b>",
            "language_unsupported": "❌ Language not supported.",
            "searching": "🔍 <b>Searching:</b> {query}",
            "downloading": "📥 Downloading...",
            "no_images_found": "❌ No images found",
            "no_images_available": "❌ No images available",
            "no_more_images": "✨ No more images",
            "session_expired": "⚠️ Session expired",
            "batch_info": "📸 Batch {current} of {total}",
            "progress": "📊 Progress: {current}/{total}",
            "what_next": "<b>What would you like to do?</b>",
            "next": "▶️ Next {count}",
            "stop": "⏹️ Stop",
            "new_search": "🆕 New Search",
            "search_stopped": "⏹️ Search stopped",
            "ready_for_search": "🆕 Ready for new search",
            "error_occurred": "❌ Error occurred",
            "file_not_found": "⚠️ File not found: {filename}",
            "failed_to_send": "⚠️ Failed to send: {filename}",
            "empty_query": "Please enter a search query",
            "lang_en": "English",
            "lang_ru": "Russian",
            "lang_es": "Spanish",
            "lang_zh": "Chinese"
        }

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
            if hasattr(message, 'from_user') and message.from_user and not message.from_user.is_bot:
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
    
    def get_user_language(self, message) -> str:
        """
        Get user's preferred language.
        Detects from message and falls back to stored preference.
        """
        user_id = self._get_user_id_from_message(message)
        
        # Check if we already have language for this user
        if user_id in self.user_languages:
            return self.user_languages[user_id]
        
        # Try to detect from Telegram language code
        if message.from_user.language_code:
            lang_code = message.from_user.language_code.split('-')[0]
            if lang_code in self.LANGUAGES:
                self.user_languages[user_id] = lang_code
                return lang_code
        
        # Default to English
        self.user_languages[user_id] = self.DEFAULT_LANGUAGE
        return self.DEFAULT_LANGUAGE
    
    def set_user_language(self, user_id: int, lang_code: str) -> bool:
        """Set user's preferred language."""
        if lang_code in self.LANGUAGES:
            self.user_languages[user_id] = lang_code
            return True
        return False
    
    def get_text(self, key: str, message=None, user_id: int = None, **kwargs) -> str:
        """
        Get translated text for a key.
        Either provide message or user_id.
        """
        # Determine language
        if message:
            lang_code = self.get_user_language(message)
        elif user_id:
            lang_code = self.user_languages.get(user_id, self.DEFAULT_LANGUAGE)
        else:
            lang_code = self.DEFAULT_LANGUAGE
        
        # Get translation with fallback to English
        translation = self.translations.get(lang_code, {})
        text = translation.get(key)
        
        # If not found in selected language, try English
        if text is None:
            text = self.translations['en'].get(key)
            
        # If still not found, return the key itself
        if text is None:
            print(f"⚠️ Missing translation for key: '{key}' in language '{lang_code}'")
            return key
        
        # Format with kwargs
        if kwargs:
            try:
                text = text.format(**kwargs)
            except KeyError as e:
                print(f"⚠️ Missing format key {e} for '{key}'")
            except Exception as e:
                print(f"⚠️ Error formatting text '{key}': {e}")
        
        return text
    
    def get_language_keyboard(self, message):
        """Create inline keyboard for language selection."""
        current_lang = self.get_user_language(message)
        keyboard = types.InlineKeyboardMarkup()
        row = []
        
        for i, (lang_code, lang_name) in enumerate(self.LANGUAGES.items()):
            # Add indicator for current language
            display_name = f"{lang_name} {'✅' if lang_code == current_lang else ''}"
            row.append(types.InlineKeyboardButton(
                display_name,
                callback_data=f"lang_{lang_code}"
            ))
            
            # 2 buttons per row
            if len(row) == 2 or i == len(self.LANGUAGES) - 1:
                keyboard.row(*row)
                row = []
        
        return keyboard
    
    def get_language_name(self, lang_code: str, in_own_language: bool = True) -> str:
        """Get language name."""
        if in_own_language:
            # Return name in the language itself
            return self.LANGUAGES.get(lang_code, lang_code)
        else:
            # Return English name
            names = {
                'en': 'English',
                'ru': 'Russian',
                'es': 'Spanish',
                'zh': 'Chinese'
            }
            return names.get(lang_code, lang_code)