#!/usr/bin/env python3
"""
Расширенная диагностика Pinterest API
"""

import requests
import json
import re
import gzip
import brotli
from urllib.parse import quote
import zlib

def decompress_content(response):
    """Декомпрессия содержимого ответа"""
    content_encoding = response.headers.get('Content-Encoding', '')
    content = response.content
    
    print(f"Content-Encoding: {content_encoding}")
    print(f"Content-Type: {response.headers.get('Content-Type', 'unknown')}")
    print(f"Content-Length: {len(content)} bytes")
    
    # Пробуем декомпрессию
    try:
        if 'gzip' in content_encoding:
            content = gzip.decompress(content)
            print("✓ GZIP decompressed successfully")
        elif 'br' in content_encoding or 'brotli' in content_encoding:
            content = brotli.decompress(content)
            print("✓ Brotli decompressed successfully")
        elif 'deflate' in content_encoding:
            content = zlib.decompress(content)
            print("✓ Deflate decompressed successfully")
    except Exception as e:
        print(f"✗ Decompression error: {e}")
    
    return content

def test_pinterest_search(query):
    print(f"\n{'='*60}")
    print(f"ТЕСТИРОВАНИЕ ПОИСКА PINTEREST: '{query}'")
    print(f"{'='*60}\n")
    
    # Формируем URL
    encoded_query = quote(query)
    url = f"https://www.pinterest.com/search/pins/?q={encoded_query}"
    
    # Заголовки как у реального браузера
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.9,ru;q=0.8',
        'Accept-Encoding': 'gzip, deflate, br',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
        'Sec-Fetch-Dest': 'document',
        'Sec-Fetch-Mode': 'navigate',
        'Sec-Fetch-Site': 'none',
        'Cache-Control': 'max-age=0',
    }
    
    # Сессия с cookies
    session = requests.Session()
    
    # Сначала заходим на главную для получения cookies
    print("1. Получаем cookies с главной страницы...")
    try:
        home_response = session.get('https://www.pinterest.com/', headers=headers, timeout=10)
        print(f"   Статус: {home_response.status_code}")
        print(f"   Cookies: {len(session.cookies)} получено")
    except Exception as e:
        print(f"   Ошибка: {e}")
    
    print(f"\n2. Выполняем поисковой запрос...")
    try:
        response = session.get(url, headers=headers, timeout=15, allow_redirects=True)
        print(f"   Статус: {response.status_code}")
        print(f"   URL после редиректов: {response.url}")
        
        if response.status_code == 200:
            # Декомпрессия
            content = decompress_content(response)
            
            # Пробуем декодировать как текст
            try:
                html = content.decode('utf-8')
                print(f"\n3. Анализ HTML (длина: {len(html)} символов)...")
                
                # Сохраняем HTML
                with open("pinterest_debug.html", "w", encoding="utf-8") as f:
                    f.write(html)
                print("   ✓ HTML сохранен в pinterest_debug.html")
                
                # Ищем JSON данные
                json_patterns = [
                    (r'<script id="__PWS_INITIAL_PROPS__" type="application/json">(.*?)</script>', 
                     "__PWS_INITIAL_PROPS__"),
                    (r'<script data-relay-response="true" type="application/json">(.*?)</script>',
                     "relay-response"),
                    (r'<script id="__PWS_DATA__" type="application/json">(.*?)</script>',
                     "__PWS_DATA__"),
                    (r'<script>window\.__PWS_DATA__\s*=\s*({.*?});?\s*</script>',
                     "window.__PWS_DATA__"),
                    (r'<script>window\.__INITIAL_STATE__\s*=\s*({.*?});?\s*</script>',
                     "__INITIAL_STATE__"),
                ]
                
                found_json = False
                for pattern, name in json_patterns:
                    matches = re.findall(pattern, html, re.DOTALL)
                    if matches:
                        print(f"\n   ✓ Найдены данные {name}: {len(matches)} блоков")
                        found_json = True
                        
                        # Сохраняем первый блок
                        try:
                            json_data = json.loads(matches[0])
                            with open(f"pinterest_{name}.json", "w", encoding="utf-8") as f:
                                json.dump(json_data, f, indent=2, ensure_ascii=False)
                            print(f"     Сохранено в pinterest_{name}.json")
                            
                            # Анализируем структуру
                            analyze_json_structure(json_data, name)
                            
                        except json.JSONDecodeError as e:
                            print(f"     ✗ Ошибка парсинга JSON: {e}")
                            # Сохраняем сырые данные
                            with open(f"pinterest_{name}_raw.json", "w", encoding="utf-8") as f:
                                f.write(matches[0][:1000])  # Первые 1000 символов
                
                if not found_json:
                    print("\n   ✗ JSON данные не найдены")
                    
                    # Ищем другие признаки
                    if 'pinterest' in html.lower():
                        print("   ✓ Страница содержит 'pinterest'")
                    
                    # Проверяем наличие пинов в HTML
                    pin_patterns = [
                        r'data-test-pin-id=["\'](\d+)',
                        r'class="[^"]*pin[^"]*"',
                        r'<div[^>]*data-test-id="pin"',
                    ]
                    
                    for pattern in pin_patterns:
                        pin_matches = re.findall(pattern, html, re.IGNORECASE)
                        if pin_matches:
                            print(f"   ✓ Найдены признаки пинов: {len(pin_matches)} совпадений")
                
                # Сохраняем заголовки ответа
                with open("response_headers.txt", "w", encoding="utf-8") as f:
                    for key, value in response.headers.items():
                        f.write(f"{key}: {value}\n")
                print("\n   ✓ Заголовки сохранены в response_headers.txt")
                
            except UnicodeDecodeError:
                print("\n   ✗ Не удалось декодировать как UTF-8, сохраняем как бинарный")
                with open("pinterest_debug.bin", "wb") as f:
                    f.write(content)
                
        else:
            print(f"\n   ✗ Ошибка: статус {response.status_code}")
            
    except Exception as e:
        print(f"\n   ✗ Ошибка запроса: {e}")
        import traceback
        traceback.print_exc()

def analyze_json_structure(data, name, depth=0, max_depth=3):
    """Анализ структуры JSON"""
    if depth == 0:
        print(f"\n   Анализ структуры {name}:")
    
    if depth > max_depth:
        return
    
    if isinstance(data, dict):
        keys = list(data.keys())
        if keys:
            print(f"{'  ' * depth}   Ключи: {keys[:10]}{'...' if len(keys) > 10 else ''}")
        
        # Ищем пины
        for key in keys:
            if 'pin' in key.lower():
                print(f"{'  ' * depth}   ✓ Найден ключ с 'pin': {key}")
            
            # Рекурсивно анализируем значения
            if isinstance(data[key], (dict, list)):
                analyze_json_structure(data[key], name, depth + 1, max_depth)
                
    elif isinstance(data, list) and depth < max_depth:
        print(f"{'  ' * depth}   Длина списка: {len(data)}")
        if data and len(data) > 0:
            analyze_json_structure(data[0], name, depth + 1, max_depth)

def test_alternative_apis():
    """Тестирование альтернативных API"""
    print(f"\n{'='*60}")
    print("ТЕСТИРОВАНИЕ АЛЬТЕРНАТИВНЫХ API")
    print(f"{'='*60}\n")
    
    # 1. Пробуем RSS feed
    print("1. RSS Feed:")
    rss_url = "https://www.pinterest.com/search/pins/?q=landscape&rs=typed&feed=yes"
    try:
        response = requests.get(rss_url, headers={'User-Agent': 'Mozilla/5.0'})
        print(f"   Статус: {response.status_code}")
        if 'xml' in response.headers.get('Content-Type', ''):
            print("   ✓ Похоже на RSS/XML")
    except Exception as e:
        print(f"   ✗ Ошибка: {e}")
    
    # 2. Пробуем мобильную версию
    print("\n2. Мобильная версия:")
    mobile_url = "https://mobile.pinterest.com/search/pins/?q=landscape"
    try:
        response = requests.get(mobile_url, headers={'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 14_0 like Mac OS X)'})
        print(f"   Статус: {response.status_code}")
    except Exception as e:
        print(f"   ✗ Ошибка: {e}")

def check_library_version():
    """Проверка версии библиотеки pinterest-dl"""
    print(f"\n{'='*60}")
    print("ПРОВЕРКА БИБЛИОТЕКИ pinterest-dl")
    print(f"{'='*60}\n")
    
    try:
        import pinterest_dl
        print(f"Версия: {getattr(pinterest_dl, '__version__', 'unknown')}")
        print(f"Путь: {pinterest_dl.__file__}")
        
        # Проверяем доступные классы
        from pinterest_dl import PinterestDL
        print(f"\nКласс PinterestDL:")
        methods = [m for m in dir(PinterestDL) if not m.startswith('_')]
        print(f"  Методы класса: {methods}")
        
        # Пробуем создать экземпляр
        p = PinterestDL()
        print(f"\nЭкземпляр PinterestDL:")
        instance_methods = [m for m in dir(p) if not m.startswith('_') and callable(getattr(p, m))]
        print(f"  Доступные методы: {instance_methods}")
        
        # Проверяем with_api
        if hasattr(PinterestDL, 'with_api'):
            p_api = PinterestDL.with_api()
            print(f"\nPinterestDL.with_api():")
            api_methods = [m for m in dir(p_api) if not m.startswith('_') and callable(getattr(p_api, m))]
            print(f"  Доступные методы: {api_methods}")
            
    except ImportError as e:
        print(f"✗ Библиотека не установлена: {e}")
    except Exception as e:
        print(f"✗ Ошибка при проверке: {e}")

if __name__ == "__main__":
    # Установка необходимых библиотек
    try:
        import brotli
    except ImportError:
        print("Устанавливаем brotli...")
        import subprocess
        subprocess.check_call(['pip', 'install', 'brotli'])
        import brotli
    
    # Запуск тестов
    test_pinterest_search("красивые пейзажи")
    test_alternative_apis()
    check_library_version()
    
    print(f"\n{'='*60}")
    print("ДИАГНОСТИКА ЗАВЕРШЕНА")
    print(f"{'='*60}")