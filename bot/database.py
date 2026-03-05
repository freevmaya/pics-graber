# ============================================================
# FILE: database.py (UPDATED WITH CONNECTION LOSS HANDLING)
# ============================================================

"""Database management module with language support and connection recovery."""

import mysql.connector
from mysql.connector import Error, InterfaceError, OperationalError
import json
import hashlib
import logging
from datetime import datetime
from typing import Optional, List, Dict, Any
from config import Config
import time

# Setup logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

class DatabaseManager:
    """Manages database operations for caching with connection recovery."""
    
    # Constants for connection retry
    MAX_RETRIES = 3
    RETRY_DELAY = 2  # seconds
    
    def __init__(self):
        """Initialize database connection."""
        self.config = Config.DB_CONFIG
        self.connection = None
        self.connect()
        self.create_tables()
    
    def connect(self, retry_count: int = 0) -> bool:
        """
        Establish database connection with retry logic.
        Returns True if connection successful, False otherwise.
        """
        try:
            if self.connection and self.connection.is_connected():
                # Test if connection is still alive
                cursor = self.connection.cursor()
                cursor.execute("SELECT 1")
                cursor.fetchone()
                cursor.close()
                return True
            
            # Close existing connection if any
            if self.connection:
                try:
                    self.connection.close()
                except:
                    pass
            
            # Attempt new connection
            self.connection = mysql.connector.connect(**self.config)
            logger.info("✓ Connected to MySQL database")
            return True
            
        except (Error, InterfaceError, OperationalError) as e:
            logger.error(f"Database connection error: {e}")
            
            if retry_count < self.MAX_RETRIES:
                retry_count += 1
                logger.info(f"Retrying connection ({retry_count}/{self.MAX_RETRIES}) in {self.RETRY_DELAY} seconds...")
                time.sleep(self.RETRY_DELAY)
                return self.connect(retry_count)
            else:
                logger.error("Failed to connect to database after multiple attempts")
                self.connection = None
                return False
    
    def ensure_connection(self) -> bool:
        """
        Ensure database connection is alive.
        Reconnects if connection is lost.
        Returns True if connection is valid, False otherwise.
        """
        try:
            if not self.connection or not self.connection.is_connected():
                logger.warning("Database connection lost. Reconnecting...")
                return self.connect()
            
            # Test connection with simple query
            cursor = self.connection.cursor()
            cursor.execute("SELECT 1")
            cursor.fetchone()
            cursor.close()
            return True
            
        except (Error, InterfaceError, OperationalError) as e:
            logger.error(f"Connection check failed: {e}")
            return self.connect()
    
    def execute_with_reconnect(self, cursor_method, *args, **kwargs):
        """
        Execute database operation with automatic reconnection on failure.
        Returns cursor.execute result or raises exception if all retries fail.
        """
        for attempt in range(self.MAX_RETRIES + 1):
            try:
                # Ensure connection is alive
                if not self.ensure_connection():
                    raise Exception("No database connection available")
                
                # Execute the operation
                cursor = self.connection.cursor(**kwargs.get('cursor_kwargs', {}))
                result = cursor_method(cursor, *args)
                
                # Commit if needed
                if kwargs.get('commit', False):
                    self.connection.commit()
                
                return result
                
            except (Error, InterfaceError, OperationalError) as e:
                logger.error(f"Database operation failed (attempt {attempt + 1}/{self.MAX_RETRIES + 1}): {e}")
                
                if attempt < self.MAX_RETRIES:
                    time.sleep(self.RETRY_DELAY)
                    # Force reconnection on next attempt
                    self.connection = None
                else:
                    raise e
            finally:
                try:
                    cursor.close()
                except:
                    pass
    
    def create_tables(self) -> None:
        """Create necessary tables if they don't exist."""
        def _create_tables(cursor):
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
                    original_query VARCHAR(255) NOT NULL,
                    normalized_query VARCHAR(255) NOT NULL,
                    query_md5 VARCHAR(32) NOT NULL,
                    search_params JSON,
                    total_images INT DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    INDEX idx_user_query (query_md5),
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
                    preview_path VARCHAR(500),
                    file_name VARCHAR(255),
                    file_size INT,
                    width INT,
                    height INT,
                    image_type VARCHAR(20) DEFAULT 'image',
                    caption TEXT,
                    downloaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    sent_at TIMESTAMP NULL,
                    FOREIGN KEY (search_cache_id) REFERENCES search_cache(id) ON DELETE CASCADE,
                    INDEX idx_search_cache (search_cache_id),
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
            
            logger.info("✓ Database tables created/verified")
            return True
        
        self.execute_with_reconnect(_create_tables, commit=True, cursor_kwargs={})
    
    def register_user(self, user_id: int, username: str = None, 
                     first_name: str = None, last_name: str = None,
                     language_code: str = 'en') -> None:
        """Register or update user in database."""
        def _register_user(cursor):
            cursor.execute("""
                INSERT INTO users (user_id, username, first_name, last_name, language_code)
                VALUES (%s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                username = VALUES(username),
                first_name = VALUES(first_name),
                last_name = VALUES(last_name),
                last_activity = CURRENT_TIMESTAMP
            """, (user_id, username, first_name, last_name, language_code))
            return True
        
        self.execute_with_reconnect(_register_user, commit=True, cursor_kwargs={})
    
    def update_user_language(self, user_id: int, language_code: str) -> None:
        """Update user's language preference."""
        def _update_user_language(cursor):
            cursor.execute("""
                UPDATE users 
                SET language_code = %s
                WHERE user_id = %s 
            """, (language_code, user_id))
            return True
        
        self.execute_with_reconnect(_update_user_language, commit=True, cursor_kwargs={})
    
    def get_user_language(self, user_id: int) -> str:
        """Get user's language preference."""
        def _get_user_language(cursor):
            cursor.execute("""
                SELECT language_code FROM users 
                WHERE user_id = %s
            """, (user_id,))
            result = cursor.fetchone()
            return result[0] if result else 'en'
        
        return self.execute_with_reconnect(_get_user_language, commit=False, cursor_kwargs={})
    
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
        
        def _get_cached_search(cursor):
            cursor.execute("""
                SELECT * FROM search_cache 
                WHERE query_md5 = %s 
                ORDER BY created_at DESC 
                LIMIT 1
            """, (query_md5,))
            
            result = cursor.fetchone()
            if result:
                # Convert tuple to dict with column names
                columns = [desc[0] for desc in cursor.description]
                return dict(zip(columns, result))
            return None
        
        return self.execute_with_reconnect(
            _get_cached_search, 
            commit=False, 
            cursor_kwargs={'dictionary': False}
        )
    
    def create_search_cache(self, user_id: int, original_query: str, 
                           normalized_query: str, query_md5: str, 
                           params: Dict = None) -> int:
        """Create new search cache entry."""
        def _create_search_cache(cursor):
            cursor.execute("""
                INSERT INTO search_cache (original_query, normalized_query, query_md5, search_params)
                VALUES (%s, %s, %s, %s)
            """, (original_query, normalized_query, query_md5, 
                  json.dumps(params, ensure_ascii=False) if params else None))
            return cursor.lastrowid
        
        return self.execute_with_reconnect(_create_search_cache, commit=True, cursor_kwargs={})

    
    
    def save_images_to_cache(self, search_cache_id: int, images: List[Dict]) -> int:
        """Save downloaded images to cache with preview paths."""
        cursor = self.connection.cursor()
        saved_count = 0
        
        for img in images:
            try:
                #logger.info(img)
                cursor.execute("""
                    INSERT INTO downloaded_images 
                    (search_cache_id, image_url, local_path, preview_path, file_name, file_size, 
                     width, height, image_type, caption)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                    local_path = VALUES(local_path),
                    preview_path = VALUES(preview_path),
                    file_size = VALUES(file_size),
                    width = VALUES(width),
                    height = VALUES(height),
                    caption = VALUES(caption)
                """, (
                    search_cache_id,
                    img.get('url', ''),
                    img.get('local_path'),
                    img.get('preview_path'),  # NEW: save preview path
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
        
        logger.info(f"Updated total_images for cache {search_cache_id} to {saved_count}")
        self.connection.commit()
        return saved_count
    
    def get_unsent_images(self, search_cache_id: int, limit: int, offset: int = 0) -> List[Dict]:
        """Get unsent images for pagination."""
        def _get_unsent_images(cursor):
            where = 'search_cache_id = %s'
            if not Config.INCLUDE_VIDEO:
                where += " AND image_type = 'image'"

            query = f"""
                SELECT * FROM downloaded_images 
                WHERE {where}
                ORDER BY id
                LIMIT %s OFFSET %s
            """
            logger.debug(f"get_unsent_images: {query}, {search_cache_id}, {limit}, {offset}")

            cursor.execute(query, (search_cache_id, limit, offset))
            
            results = []
            for row in cursor.fetchall():
                # Convert tuple to dict with column names
                columns = [desc[0] for desc in cursor.description]
                results.append(dict(zip(columns, row)))
            
            return results
        
        return self.execute_with_reconnect(
            _get_unsent_images, 
            commit=False, 
            cursor_kwargs={'dictionary': False}
        )
    
    def get_user_session(self, user_id: int) -> Optional[Dict]:
        """Get user session data."""
        def _get_user_session(cursor):
            cursor.execute("""
                SELECT * FROM user_sessions 
                WHERE user_id = %s
            """, (user_id,))
            
            result = cursor.fetchone()
            if result:
                columns = [desc[0] for desc in cursor.description]
                return dict(zip(columns, result))
            return None
        
        return self.execute_with_reconnect(
            _get_user_session, 
            commit=False, 
            cursor_kwargs={'dictionary': False}
        )
    
    def reset_user_session(self, user_id: int) -> None:
        """Reset user session."""
        def _reset_user_session(cursor):
            cursor.execute("""
                UPDATE user_sessions 
                SET current_offset = 0
                WHERE user_id = %s
            """, (user_id,))
            return True
        
        self.execute_with_reconnect(_reset_user_session, commit=True, cursor_kwargs={})
    
    def get_total_images_count(self, search_cache_id: int) -> int:
        """Get total number of images in cache."""
        def _get_total_images_count(cursor):
            where = 'search_cache_id = %s'
            if not Config.INCLUDE_VIDEO:
                where += " AND image_type = 'image'"

            cursor.execute(f"""
                SELECT COUNT(*) FROM downloaded_images 
                WHERE {where}
            """, (search_cache_id,))
            result = cursor.fetchone()
            return result[0] if result else 0
        
        return self.execute_with_reconnect(
            _get_total_images_count, 
            commit=False, 
            cursor_kwargs={}
        )
    
    def update_search_cache_total(self, search_cache_id: int, total: int) -> None:
        """Update total images count in search cache."""
        def _update_search_cache_total(cursor):
            cursor.execute("""
                UPDATE search_cache 
                SET total_images = %s
                WHERE id = %s
            """, (total, search_cache_id))
            return True
        
        self.execute_with_reconnect(_update_search_cache_total, commit=True, cursor_kwargs={})
    
    def update_user_session(self, user_id: int, search_cache_id: int = None,
                           offset: int = None, total_images: int = None,
                           last_query: str = None, last_message_id: int = None) -> None:
        """Update user session data."""
        def _update_user_session(cursor):
            # First check if session exists
            cursor.execute("SELECT user_id FROM user_sessions WHERE user_id = %s", (user_id,))
            exists = cursor.fetchone()
            
            if exists:
                # Update existing session
                update_parts = []
                params = []
                
                if search_cache_id is not None:
                    update_parts.append("current_search_cache_id = %s")
                    params.append(search_cache_id)
                
                if offset is not None:
                    update_parts.append("current_offset = %s")
                    params.append(offset)
                
                if total_images is not None:
                    update_parts.append("total_images = %s")
                    params.append(total_images)
                
                if last_query is not None:
                    update_parts.append("last_query = %s")
                    params.append(last_query)
                
                if last_message_id is not None:
                    update_parts.append("last_message_id = %s")
                    params.append(last_message_id)
                
                update_parts.append("updated_at = CURRENT_TIMESTAMP")
                
                if update_parts:
                    query = f"""
                        UPDATE user_sessions 
                        SET {', '.join(update_parts)}
                        WHERE user_id = %s
                    """
                    params.append(user_id)
                    cursor.execute(query, tuple(params))
            else:
                # Insert new session
                cursor.execute("""
                    INSERT INTO user_sessions 
                    (user_id, current_search_cache_id, current_offset, total_images, last_query, last_message_id)
                    VALUES (%s, %s, %s, %s, %s, %s)
                """, (user_id, search_cache_id, offset, total_images, last_query, last_message_id))
            
            return True
        
        self.execute_with_reconnect(_update_user_session, commit=True, cursor_kwargs={})
    
    def close(self):
        """Close database connection."""
        if self.connection and self.connection.is_connected():
            try:
                self.connection.close()
                logger.info("Database connection closed")
            except Exception as e:
                logger.error(f"Error closing database connection: {e}")