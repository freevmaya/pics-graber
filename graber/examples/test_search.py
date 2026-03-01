#!/usr/bin/env python3
"""
Тестовый скрипт для проверки поиска Pinterest
"""

import requests
import json
import re
from urllib.parse import quote

def test_pinterest_search(query):
    print(f"Testing search for: {query}")
    print("-" * 50)
    
    # Формируем URL
    encoded_query = quote(query)
    url = f"https://www.pinterest.com/search/pins/?q={encoded_query}"
    
    # Заголовки как у браузера
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5',
        'Accept-Encoding': 'gzip, deflate, br',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
    }
    
    try:
        # Выполняем запрос
        response = requests.get(url, headers=headers, timeout=10)
        print(f"Status code: {response.status_code}")
        
        if response.status_code == 200:
            # Ищем JSON данные
            html = response.text
            
            # Паттерны для поиска данных
            patterns = [
                r'<script data-relay-response="true" type="application/json">(.*?)</script>',
                r'<script id="__PWS_DATA__" type="application/json">(.*?)</script>',
            ]
            
            found_data = False
            for i, pattern in enumerate(patterns):
                matches = re.findall(pattern, html, re.DOTALL)
                if matches:
                    print(f"\nFound {len(matches)} JSON data blocks (pattern {i+1})")
                    found_data = True
                    
                    # Пробуем распарсить первый блок
                    try:
                        data = json.loads(matches[0])
                        print("Successfully parsed JSON data")
                        
                        # Ищем пины в данных
                        pin_count = 0
                        
                        # Рекурсивный поиск ключа 'pin'
                        def find_pins(obj, depth=0):
                            nonlocal pin_count
                            if depth > 10:
                                return
                            
                            if isinstance(obj, dict):
                                if 'pin' in obj and isinstance(obj['pin'], dict):
                                    pin_count += 1
                                for key, value in obj.items():
                                    find_pins(value, depth + 1)
                            elif isinstance(obj, list):
                                for item in obj:
                                    find_pins(item, depth + 1)
                        
                        find_pins(data)
                        print(f"Found approximately {pin_count} pins in data")
                        
                        # Показываем структуру
                        print("\nData structure keys:")
                        if isinstance(data, dict):
                            print(list(data.keys())[:10])
                        
                    except json.JSONDecodeError as e:
                        print(f"JSON decode error: {e}")
            
            if not found_data:
                print("No JSON data blocks found in HTML")
                
                # Сохраняем HTML для анализа
                with open("debug_search.html", "w", encoding="utf-8") as f:
                    f.write(html)
                print("Saved HTML to debug_search.html for analysis")
        
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    test_pinterest_search("красивые пейзажи")