#!/usr/bin/env python3
"""
Pinterest Downloader Wrapper - обертка для pinterest-dl с кешированием в MySQL
Использование: python pinterest-dl-wrapper.py search "котики" -o downloads --video
"""

import argparse
import os
import hashlib
import subprocess
import mysql.connector
from mysql.connector import Error
import json
import time
from datetime import datetime
import sys
from dotenv import load_dotenv
import pathlib
import re

# Загрузка переменных окружения из .env файла
load_dotenv()

class PinterestDLWrapper:
    def __init__(self, db_config=None):
        """
        Инициализация обертки
        """
        if db_config:
            self.db_config = db_config
        else:
            # Загрузка конфигурации из переменных окружения
            self.db_config = {
                'host': os.getenv('DB_HOST', 'localhost'),
                'port': os.getenv('DB_PORT', '3306'),
                'database': os.getenv('DB_NAME', 'pinterest_cache'),
                'user': os.getenv('DB_USER', 'root'),
                'password': os.getenv('DB_PASSWORD', ''),
                'charset': os.getenv('DB_CHARSET', 'utf8mb4'),
                'use_pure': True
            }
        
        self.connection = None
        self.connect_db()
        self.create_tables()
    
    def connect_db(self):
        """Подключение к MySQL"""
        try:
            self.connection = mysql.connector.connect(**self.db_config)
            print("✓ Подключено к MySQL")
        except Error as e:
            print(f"✗ Ошибка подключения к MySQL: {e}")
            print("Проверьте настройки в файле .env")
            sys.exit(1)
    
    def create_tables(self):
        """Создание необходимых таблиц"""
        cursor = self.connection.cursor()
        
        # Таблица для кеша запросов
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS search_cache (
                id INT AUTO_INCREMENT PRIMARY KEY,
                original_query VARCHAR(255) NOT NULL,
                normalized_query VARCHAR(255) NOT NULL,
                query_md5 VARCHAR(32) NOT NULL UNIQUE,
                search_params JSON,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                INDEX idx_query_md5 (query_md5),
                INDEX idx_created (created_at)
            ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
        """)
        
        # Таблица для скачанных файлов
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS downloaded_files (
                id INT AUTO_INCREMENT PRIMARY KEY,
                query_md5 VARCHAR(32) NOT NULL,
                file_path VARCHAR(500) NOT NULL,
                file_name VARCHAR(255),
                file_size INT,
                file_type VARCHAR(20),
                downloaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                INDEX idx_query_md5 (query_md5),
                INDEX idx_file_path (file_path),
                CONSTRAINT unique_file_per_query UNIQUE KEY unique_file (query_md5, file_path)
            ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
        """)
        
        self.connection.commit()
        print("✓ Таблицы созданы/проверены")
    
    def normalize_query(self, query):
        """
        Нормализация запроса:
        - Приводим к нижнему регистру
        - Удаляем знаки препинания, скобки и спецсимволы
        - Оставляем только буквы, цифры и пробелы
        """
        # Приводим к нижнему регистру
        normalized = query.lower()
        
        # Удаляем все кроме букв, цифр и пробелов
        normalized = re.sub(r'[^\w\s]', ' ', normalized)
        
        # Заменяем множественные пробелы на один
        normalized = re.sub(r'\s+', ' ', normalized)
        
        # Убираем пробелы в начале и конце
        normalized = normalized.strip()
        
        return normalized
    
    def get_query_md5(self, query):
        """Получение MD5 хеша от нормализованного запроса"""
        normalized = self.normalize_query(query)
        return hashlib.md5(normalized.encode('utf-8')).hexdigest()
    
    def is_cached(self, query_md5):
        """Проверка, есть ли запрос в кеше"""
        cursor = self.connection.cursor(dictionary=True)
        
        cursor.execute("""
            SELECT * FROM search_cache 
            WHERE query_md5 = %s
        """, (query_md5,))
        
        return cursor.fetchone() is not None
    
    def get_cached_files(self, query_md5):
        """Получение списка файлов из кеша для запроса"""
        cursor = self.connection.cursor(dictionary=True)
        
        cursor.execute("""
            SELECT * FROM downloaded_files 
            WHERE query_md5 = %s
            ORDER BY downloaded_at DESC
        """, (query_md5,))
        
        return cursor.fetchall()
    
    def save_to_cache(self, query_md5, original_query, normalized_query, params):
        """Сохранение информации о запросе в кеш"""
        cursor = self.connection.cursor()
        
        cursor.execute("""
            INSERT INTO search_cache (original_query, normalized_query, query_md5, search_params)
            VALUES (%s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
            search_params = VALUES(search_params)
        """, (original_query, normalized_query, query_md5, json.dumps(params, ensure_ascii=False)))
        
        self.connection.commit()
    
    def save_downloaded_file(self, query_md5, file_path, file_type='image'):
        """Сохранение информации о скачанном файле"""
        try:
            # Получаем размер файла
            file_size = os.path.getsize(file_path) if os.path.exists(file_path) else 0
            file_name = os.path.basename(file_path)
            
            cursor = self.connection.cursor()
            
            cursor.execute("""
                INSERT INTO downloaded_files (query_md5, file_path, file_name, file_size, file_type)
                VALUES (%s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                file_size = VALUES(file_size),
                downloaded_at = CURRENT_TIMESTAMP
            """, (query_md5, file_path, file_name, file_size, file_type))
            
            self.connection.commit()
            return True
        except Exception as e:
            print(f"✗ Ошибка при сохранении в БД: {e}")
            return False
    
    def scan_download_directory(self, directory, query_md5):
        """Сканирование директории на наличие скачанных файлов"""
        downloaded_files = []
        
        if os.path.exists(directory):
            for root, dirs, files in os.walk(directory):
                for file in files:
                    # Проверяем расширения файлов
                    if file.lower().endswith(('.jpg', '.jpeg', '.png', '.gif', '.mp4', '.webm', '.mov')):
                        file_path = os.path.join(root, file)
                        file_type = 'video' if file.lower().endswith(('.mp4', '.webm', '.mov')) else 'image'
                        downloaded_files.append({
                            'path': file_path,
                            'type': file_type
                        })
        
        return downloaded_files
    
    def execute_pinterest_dl(self, query, output_dir, video_only=False):
        """
        Выполнение команды pinterest-dl
        """
        # Формируем команду
        cmd = ['pinterest-dl', 'search', f'"{query}"', '-o', output_dir]
        if video_only:
            cmd.append('--video')
        
        cmd_str = ' '.join(cmd)
        print(f"▶ Выполняю: {cmd_str}")
        
        try:
            # Выполняем команду
            result = subprocess.run(
                cmd_str,
                shell=True,
                capture_output=True,
                text=True,
                timeout=300  # 5 минут максимум
            )
            
            if result.returncode == 0:
                print("✓ Команда выполнена успешно")
                print(result.stdout)
                return True, result.stdout
            else:
                print(f"✗ Ошибка выполнения команды (код {result.returncode})")
                print(result.stderr)
                return False, result.stderr
                
        except subprocess.TimeoutExpired:
            print("✗ Превышено время выполнения команды")
            return False, "Timeout"
        except Exception as e:
            print(f"✗ Ошибка при выполнении команды: {e}")
            return False, str(e)
    
    def process_search(self, query, output_dir='downloads', video_only=False, force=False):
        """
        Обработка поискового запроса
        """
        # Получаем MD5 от нормализованного запроса
        normalized = self.normalize_query(query)
        query_md5 = self.get_query_md5(query)
        
        print(f"\n🔍 Запрос: '{query}'")
        print(f"📝 Нормализованный: '{normalized}'")
        print(f"🔑 MD5: {query_md5}")
        print(f"📁 Директория: {output_dir}")
        print("-" * 60)
        
        # Проверяем кеш
        if not force and self.is_cached(query_md5):
            print("📦 Запрос найден в кеше!")
            
            # Получаем список файлов из кеша
            cached_files = self.get_cached_files(query_md5)
            
            if cached_files:
                print(f"\n📊 Найдено {len(cached_files)} файлов в кеше:")
                for i, file in enumerate(cached_files, 1):
                    size_kb = file['file_size'] / 1024 if file['file_size'] else 0
                    print(f"  {i}. {file['file_name']} ({size_kb:.1f} KB) - {file['file_type']}")
                
                print("\n✓ Использованы данные из кеша")
                return cached_files
            else:
                print("⚠️ В кеше нет файлов для этого запроса")
        else:
            if force:
                print("⚠️ Принудительное обновление кеша")
        
        # Выполняем pinterest-dl
        print("\n🚀 Запускаем pinterest-dl...")
        success, output = self.execute_pinterest_dl(query, output_dir, video_only)
        
        if not success:
            print("✗ Не удалось выполнить pinterest-dl")
            return None
        
        # Даем время на завершение загрузки файлов
        print("\n⏳ Ожидаем завершения загрузки файлов...")
        time.sleep(3)
        
        # Сканируем директорию на наличие новых файлов
        print("🔍 Сканируем директорию загрузки...")
        downloaded_files = self.scan_download_directory(output_dir, query_md5)
        
        if downloaded_files:
            print(f"\n📥 Найдено {len(downloaded_files)} скачанных файлов:")
            
            # Сохраняем информацию о файлах в кеш
            saved_count = 0
            for file_info in downloaded_files:
                if self.save_downloaded_file(query_md5, file_info['path'], file_info['type']):
                    saved_count += 1
                print(f"  • {os.path.basename(file_info['path'])} ({file_info['type']})")
            
            print(f"\n✓ Сохранено {saved_count} файлов в кеш")
            
            # Сохраняем информацию о запросе
            params = {
                'original_query': query,
                'video_only': video_only,
                'output_dir': output_dir,
                'timestamp': datetime.now().isoformat()
            }
            self.save_to_cache(query_md5, query, normalized, params)
            
            return downloaded_files
        else:
            print("⚠️ Файлы не найдены в директории загрузки")
            return []

def create_env_file():
    """Создание примера .env файла"""
    env_content = """# Pinterest Downloader Wrapper Configuration
# MySQL Database Settings
DB_HOST=localhost
DB_PORT=3306
DB_NAME=pinterest_cache
DB_USER=root
DB_PASSWORD=your_password_here
DB_CHARSET=utf8mb4
"""
    
    env_path = pathlib.Path('.env')
    if not env_path.exists():
        with open(env_path, 'w', encoding='utf-8') as f:
            f.write(env_content)
        print("✓ Создан файл .env. Отредактируйте его и укажите настройки MySQL")
    else:
        print("✓ Файл .env уже существует")

def check_pinterest_dl():
    """Проверка наличия pinterest-dl"""
    try:
        result = subprocess.run(['pinterest-dl', '--help'], 
                              capture_output=True, 
                              text=True)
        if result.returncode == 0:
            print("✓ pinterest-dl найден")
            return True
        else:
            print("✗ pinterest-dl не найден")
            return False
    except FileNotFoundError:
        print("✗ pinterest-dl не установлен")
        return False

def main():
    parser = argparse.ArgumentParser(description='Обертка для pinterest-dl с кешированием в MySQL')
    subparsers = parser.add_subparsers(dest='command', help='Команды')
    
    # Команда search
    search_parser = subparsers.add_parser('search', help='Поиск и скачивание контента')
    search_parser.add_argument('query', help='Поисковый запрос')
    search_parser.add_argument('-o', '--output', default='downloads', help='Директория для скачивания')
    search_parser.add_argument('--video', action='store_true', help='Скачивать только видео')
    search_parser.add_argument('--force', action='store_true', help='Игнорировать кеш и скачать заново')
    
    # Команда для создания .env
    env_parser = subparsers.add_parser('init', help='Создать файл .env')
    
    # Команда для просмотра кеша
    cache_parser = subparsers.add_parser('show-cache', help='Показать содержимое кеша')
    cache_parser.add_argument('query', nargs='?', help='Показать кеш для конкретного запроса')
    
    # Команда для очистки кеша
    clear_parser = subparsers.add_parser('clear-cache', help='Очистить кеш')
    clear_parser.add_argument('--all', action='store_true', help='Очистить весь кеш')
    clear_parser.add_argument('--query', help='Очистить кеш для конкретного запроса')
    
    args = parser.parse_args()
    
    if args.command == 'init':
        create_env_file()
        print("\n📝 Инструкция:")
        print("1. Отредактируйте файл .env и укажите настройки MySQL")
        print("2. Создайте базу данных в MySQL: CREATE DATABASE pinterest_cache;")
        print("3. Убедитесь что pinterest-dl установлен: pip install pinterest-dl")
        print("4. Запустите поиск: python pinterest-dl-wrapper.py search 'котики' -o downloads")
        return
    
    if not args.command:
        parser.print_help()
        return
    
    # Проверяем наличие pinterest-dl
    if not check_pinterest_dl():
        print("\n❌ Установите pinterest-dl:")
        print("pip install pinterest-dl")
        return
    
    # Проверяем наличие .env файла
    if not os.path.exists('.env'):
        print("⚠️  Файл .env не найден. Создайте его с помощью команды:")
        print("   python pinterest-dl-wrapper.py init")
        return
    
    # Создаем обертку
    wrapper = PinterestDLWrapper()
    
    if args.command == 'show-cache':
        cursor = wrapper.connection.cursor(dictionary=True)
        
        if args.query:
            # Показываем кеш для конкретного запроса
            query_md5 = wrapper.get_query_md5(args.query)
            cursor.execute("""
                SELECT sc.*, COUNT(df.id) as files_count 
                FROM search_cache sc
                LEFT JOIN downloaded_files df ON sc.query_md5 = df.query_md5
                WHERE sc.query_md5 = %s
                GROUP BY sc.id
            """, (query_md5,))
            cache_entry = cursor.fetchone()
            
            if cache_entry:
                print(f"\n📦 Кеш для запроса: {cache_entry['original_query']}")
                print(f"📝 Нормализованный: {cache_entry['normalized_query']}")
                print(f"🔑 MD5: {cache_entry['query_md5']}")
                print(f"📅 Создан: {cache_entry['created_at']}")
                print(f"📊 Файлов в кеше: {cache_entry['files_count']}")
                
                # Показываем файлы
                cursor.execute("""
                    SELECT * FROM downloaded_files 
                    WHERE query_md5 = %s
                    ORDER BY downloaded_at DESC
                """, (query_md5,))
                files = cursor.fetchall()
                
                if files:
                    print("\n📁 Скачанные файлы:")
                    for i, f in enumerate(files, 1):
                        size_mb = f['file_size'] / (1024*1024) if f['file_size'] else 0
                        print(f"  {i}. {f['file_name']} ({size_mb:.2f} MB) - {f['downloaded_at']}")
            else:
                print(f"⚠️ Запрос '{args.query}' не найден в кеше")
        else:
            # Показываем все записи в кеше
            cursor.execute("""
                SELECT sc.*, COUNT(df.id) as files_count 
                FROM search_cache sc
                LEFT JOIN downloaded_files df ON sc.query_md5 = df.query_md5
                GROUP BY sc.id
                ORDER BY sc.created_at DESC
            """)
            cache_entries = cursor.fetchall()
            
            if cache_entries:
                print(f"\n📦 Всего записей в кеше: {len(cache_entries)}")
                for entry in cache_entries:
                    print(f"\n🔹 {entry['original_query']}")
                    print(f"   MD5: {entry['query_md5']}")
                    print(f"   Файлов: {entry['files_count']}")
                    print(f"   Дата: {entry['created_at']}")
            else:
                print("📭 Кеш пуст")
        
        return
    
    if args.command == 'clear-cache':
        cursor = wrapper.connection.cursor()
        
        if args.all:
            cursor.execute("DELETE FROM downloaded_files")
            cursor.execute("DELETE FROM search_cache")
            wrapper.connection.commit()
            print("✓ Весь кеш очищен")
        elif args.query:
            query_md5 = wrapper.get_query_md5(args.query)
            cursor.execute("DELETE FROM downloaded_files WHERE query_md5 = %s", (query_md5,))
            cursor.execute("DELETE FROM search_cache WHERE query_md5 = %s", (query_md5,))
            wrapper.connection.commit()
            print(f"✓ Кеш для запроса '{args.query}' очищен")
        else:
            print("⚠️ Укажите --all для очистки всего кеша или --query для конкретного запроса")
        
        return
    
    if args.command == 'search':
        # Обрабатываем поиск
        wrapper.process_search(
            query=args.query,
            output_dir=args.output,
            video_only=args.video,
            force=args.force
        )

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n⚠️  Прервано пользователем")
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ Ошибка: {e}")
        sys.exit(1)