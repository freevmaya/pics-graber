# ============================================================
# FILE: database.py (UPDATED)
# TYPE: .PY
# ============================================================

"""Database management module with language support."""

import mysql.connector
from mysql.connector import Error
import json
import hashlib
from datetime import datetime
from typing import Optional, List, Dict, Any
from config import Config

class DatabaseManager:
    """Manages database operations for caching."""
    
    def __init__(self):
        """Initialize database connection."""
        self.config = Config.DB_CONFIG
        self.connection = None
        self.connect()
        self.create_tables()
    
    def connect(self) -> None:
        """Establish database connection."""
        try:
            self.connection = mysql.connector.connect(**self.config)
            print("✓ Connected to MySQL database")
        except Error as e:
            print(f"✗ Database connection error: {e}")
            raise
    
    def create_tables(self) -> None:
        """Create necessary tables if they don't exist."""
        cursor = self.connection.cursor()
        
        # Users table with language preference
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY,
                username VARCHAR(255),
                first_name VARCHAR(255),
                last_name VARCHAR(255),
                language_code VARCHAR(10) DEFAULT 'en',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_activity TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                INDEX idx_last_activity (last_activity),
                INDEX idx_language (language_code)
            ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
        """)
        
        # Search queries cache
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS search_cache (
                id INT AUTO_INCREMENT PRIMARY KEY,
                user_id BIGINT NOT NULL,
                original_query VARCHAR(255) NOT NULL,
                normalized_query VARCHAR(255) NOT NULL,
                query_md5 VARCHAR(32) NOT NULL,
                search_params JSON,
                total_images INT DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
                INDEX idx_user_query (user_id, query_md5),
                INDEX idx_created (created_at)
            ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
        """)
        
        # Downloaded images cache
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS downloaded_images (
                id INT AUTO_INCREMENT PRIMARY KEY,
                search_cache_id INT NOT NULL,
                image_url VARCHAR(1000) NOT NULL,
                local_path VARCHAR(500),
                file_name VARCHAR(255),
                file_size INT,
                width INT,
                height INT,
                image_type VARCHAR(20) DEFAULT 'image',
                caption TEXT,
                downloaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_sent BOOLEAN DEFAULT FALSE,
                sent_at TIMESTAMP NULL,
                FOREIGN KEY (search_cache_id) REFERENCES search_cache(id) ON DELETE CASCADE,
                INDEX idx_search_cache (search_cache_id),
                INDEX idx_is_sent (is_sent),
                UNIQUE KEY unique_image_per_search (search_cache_id, image_url(255))
            ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
        """)
        
        # User sessions for pagination
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_sessions (
                user_id BIGINT PRIMARY KEY,
                current_search_cache_id INT,
                current_offset INT DEFAULT 0,
                total_images INT DEFAULT 0,
                last_query VARCHAR(255),
                last_message_id INT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
                FOREIGN KEY (current_search_cache_id) REFERENCES search_cache(id) ON DELETE SET NULL,
                INDEX idx_updated (updated_at)
            ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
        """)
        
        self.connection.commit()
        print("✓ Database tables created/verified")
    
    def register_user(self, user_id: int, username: str = None, 
                     first_name: str = None, last_name: str = None,
                     language_code: str = 'en') -> None:
        """Register or update user in database."""
        cursor = self.connection.cursor()
        cursor.execute("""
            INSERT INTO users (user_id, username, first_name, last_name, language_code)
            VALUES (%s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
            username = VALUES(username),
            first_name = VALUES(first_name),
            last_name = VALUES(last_name),
            last_activity = CURRENT_TIMESTAMP
        """, (user_id, username, first_name, last_name, language_code))
        self.connection.commit()
    
    def update_user_language(self, user_id: int, language_code: str) -> None:
        """Update user's language preference."""
        cursor = self.connection.cursor()
        cursor.execute("""
            UPDATE users 
            SET language_code = %s
            WHERE user_id = %s
        """, (language_code, user_id))
        self.connection.commit()
    
    def get_user_language(self, user_id: int) -> str:
        """Get user's language preference."""
        cursor = self.connection.cursor(dictionary=True)
        cursor.execute("""
            SELECT language_code FROM users 
            WHERE user_id = %s
        """, (user_id,))
        result = cursor.fetchone()
        return result['language_code'] if result else 'en'
    
    def normalize_query(self, query: str) -> str:
        """Normalize search query."""
        import re
        normalized = query.lower()
        normalized = re.sub(r'[^\w\s]', ' ', normalized)
        normalized = re.sub(r'\s+', ' ', normalized)
        return normalized.strip()
    
    def get_query_md5(self, query: str) -> str:
        """Get MD5 hash of normalized query."""
        normalized = self.normalize_query(query)
        return hashlib.md5(normalized.encode('utf-8')).hexdigest()
    
    def get_cached_search(self, user_id: int, query: str) -> Optional[Dict[str, Any]]:
        """Get cached search for user and query."""
        query_md5 = self.get_query_md5(query)
        cursor = self.connection.cursor(dictionary=True)
        
        cursor.execute("""
            SELECT * FROM search_cache 
            WHERE user_id = %s AND query_md5 = %s
            ORDER BY created_at DESC
            LIMIT 1
        """, (user_id, query_md5))
        
        return cursor.fetchone()
    
    def create_search_cache(self, user_id: int, original_query: str, 
                           normalized_query: str, query_md5: str, 
                           params: Dict = None) -> int:
        """Create new search cache entry."""
        cursor = self.connection.cursor()
        cursor.execute("""
            INSERT INTO search_cache (user_id, original_query, normalized_query, query_md5, search_params)
            VALUES (%s, %s, %s, %s, %s)
        """, (user_id, original_query, normalized_query, query_md5, 
              json.dumps(params, ensure_ascii=False) if params else None))
        self.connection.commit()
        return cursor.lastrowid
    
    def save_images_to_cache(self, search_cache_id: int, images: List[Dict]) -> int:
        """Save downloaded images to cache."""
        cursor = self.connection.cursor()
        saved_count = 0
        
        for img in images:
            try:
                cursor.execute("""
                    INSERT INTO downloaded_images 
                    (search_cache_id, image_url, local_path, file_name, file_size, 
                     width, height, image_type, caption)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                    local_path = VALUES(local_path),
                    file_size = VALUES(file_size),
                    width = VALUES(width),
                    height = VALUES(height),
                    caption = VALUES(caption)
                """, (
                    search_cache_id,
                    img.get('url', ''),
                    img.get('local_path'),
                    img.get('file_name'),
                    img.get('file_size'),
                    img.get('width'),
                    img.get('height'),
                    img.get('type', 'image'),
                    img.get('caption')
                ))
                saved_count += 1
            except Error as e:
                print(f"Error saving image: {e}")
                continue
        
        # Update total images count
        cursor.execute("""
            UPDATE search_cache 
            SET total_images = (
                SELECT COUNT(*) FROM downloaded_images 
                WHERE search_cache_id = %s
            )
            WHERE id = %s
        """, (search_cache_id, search_cache_id))
        
        self.connection.commit()
        return saved_count
    
    def get_unsent_images(self, search_cache_id: int, limit: int, offset: int = 0) -> List[Dict]:
        """Get unsent images for pagination."""
        cursor = self.connection.cursor(dictionary=True)
        cursor.execute("""
            SELECT * FROM downloaded_images 
            WHERE search_cache_id = %s AND is_sent = FALSE
            ORDER BY id
            LIMIT %s OFFSET %s
        """, (search_cache_id, limit, offset))
        return cursor.fetchall()
    
    def mark_images_as_sent(self, image_ids: List[int]) -> None:
        """Mark images as sent."""
        if not image_ids:
            return
        
        cursor = self.connection.cursor()
        format_strings = ','.join(['%s'] * len(image_ids))
        cursor.execute(f"""
            UPDATE downloaded_images 
            SET is_sent = TRUE, sent_at = CURRENT_TIMESTAMP
            WHERE id IN ({format_strings})
        """, tuple(image_ids))
        self.connection.commit()
    
    def get_user_session(self, user_id: int) -> Optional[Dict]:
        """Get user session data."""
        cursor = self.connection.cursor(dictionary=True)
        cursor.execute("""
            SELECT * FROM user_sessions 
            WHERE user_id = %s
        """, (user_id,))
        return cursor.fetchone()
    
    def update_user_session(self, user_id: int, search_cache_id: int = None,
                           offset: int = 0, total_images: int = 0,
                           last_query: str = None, last_message_id: int = None) -> None:
        """Update user session data."""
        cursor = self.connection.cursor()
        cursor.execute("""
            INSERT INTO user_sessions 
            (user_id, current_search_cache_id, current_offset, total_images, last_query, last_message_id)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
            current_search_cache_id = VALUES(current_search_cache_id),
            current_offset = VALUES(current_offset),
            total_images = VALUES(total_images),
            last_query = VALUES(last_query),
            last_message_id = VALUES(last_message_id),
            updated_at = CURRENT_TIMESTAMP
        """, (user_id, search_cache_id, offset, total_images, last_query, last_message_id))
        self.connection.commit()
    
    def reset_user_session(self, user_id: int) -> None:
        """Reset user session."""
        cursor = self.connection.cursor()
        cursor.execute("""
            UPDATE user_sessions 
            SET current_offset = 0
            WHERE user_id = %s
        """, (user_id,))
        self.connection.commit()
    
    def close(self):
        """Close database connection."""
        if self.connection and self.connection.is_connected():
            self.connection.close()