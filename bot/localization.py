# ============================================================
# FILE: localization.py
# TYPE: .PY
# ============================================================

"""Localization module for Pinterest Bot."""

import json
import os
from pathlib import Path
from typing import Dict, Optional
from telegram import Update

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
    
    def load_translations(self):
        """Load all translation JSON files."""
        if not self.locales_dir.exists():
            self.locales_dir.mkdir(exist_ok=True)
            print(f"✓ Created locales directory: {self.locales_dir}")
        
        for lang_code in self.LANGUAGES.keys():
            file_path = self.locales_dir / f"{lang_code}.json"
            try:
                if file_path.exists():
                    with open(file_path, 'r', encoding='utf-8') as f:
                        self.translations[lang_code] = json.load(f)
                    print(f"✓ Loaded translations for {lang_code}")
                else:
                    print(f"⚠️ Translation file not found: {file_path}")
                    self.translations[lang_code] = self._create_default_translations(lang_code)
            except Exception as e:
                print(f"✗ Error loading {lang_code}.json: {e}")
                self.translations[lang_code] = self._create_default_translations(lang_code)
    
    def _create_default_translations(self, lang_code: str) -> Dict[str, str]:
        """Create default translations if file is missing."""
        # Return empty dict, will be populated with English defaults
        return {}
    
    def get_user_language(self, update: Update) -> str:
        """
        Get user's preferred language.
        Detects from Telegram language code and falls back to stored preference.
        """
        user_id = update.effective_user.id
        
        # Check if we already have language for this user
        if user_id in self.user_languages:
            return self.user_languages[user_id]
        
        # Try to detect from Telegram language code
        if update.effective_user.language_code:
            lang_code = update.effective_user.language_code.split('-')[0]
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
    
    def get_text(self, key: str, update: Update = None, user_id: int = None, **kwargs) -> str:
        """
        Get translated text for a key.
        Either provide update or user_id.
        """
        # Determine language
        if update:
            lang_code = self.get_user_language(update)
        elif user_id:
            lang_code = self.user_languages.get(user_id, self.DEFAULT_LANGUAGE)
        else:
            lang_code = self.DEFAULT_LANGUAGE
        
        # Get translation
        translation = self.translations.get(lang_code, {})
        text = translation.get(key, self.translations[self.DEFAULT_LANGUAGE].get(key, key))
        
        # Format with kwargs
        if kwargs:
            try:
                text = text.format(**kwargs)
            except KeyError as e:
                print(f"Warning: Missing format key {e} for '{key}'")
        
        return text
    
    def get_language_keyboard(self, update: Update):
        """Create inline keyboard for language selection."""
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
        
        current_lang = self.get_user_language(update)
        keyboard = []
        row = []
        
        for i, (lang_code, lang_name) in enumerate(self.LANGUAGES.items()):
            # Add indicator for current language
            display_name = f"{lang_name} {'✅' if lang_code == current_lang else ''}"
            row.append(InlineKeyboardButton(
                display_name,
                callback_data=f"lang_{lang_code}"
            ))
            
            # 2 buttons per row
            if len(row) == 2 or i == len(self.LANGUAGES) - 1:
                keyboard.append(row)
                row = []
        
        return InlineKeyboardMarkup(keyboard)
    
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