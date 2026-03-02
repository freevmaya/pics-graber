# combine_run.py
import os
import glob

def combine_project_files():
    """Объединяет все файлы в текущей директории и поддиректориях"""
    
    output_file = "combined.txt"
    exclude_files = ["combine_run.py", output_file]
    exclude_paths = ["vendor", "dev", "env", "graber"]
    
    # Определяем расширения файлов для обработки
    target_extensions = [".py", ".txt", "json"]
    prompt = '''*Общая концепция для кодинга*

Придерживайся объектно ориентированной концепции и событийной модели.
Придерживаться изначальных именований классов, методов, функций, констант, переменных и не переименовывать при модификации.
Если требуется создать отдельный класс и код его больше 100 строк, создавай его в отдельном файле
Константы должны быть написаны в ВЕРХНЕМ РЕГИСТРЕ
Важно: 
При модификации показывай весь код изменяемого файла!
Показывай полный код в файле, если изменения более 50 строк!
Используй средства локализации (LocalizationManager, get_text), не используй жестко заданные строки
Если добавляются тексты в локализации, то показывать все измененые json файлы!
'''
    
    with open(output_file, "w", encoding="utf-8") as outfile:
        outfile.write(prompt + "\n\n")
        outfile.write("# COMBINED PROJECT FILES FOR DEEPSEEK\n")
        outfile.write("# Encoding: UTF-8\n")
        outfile.write(f"# Processed extensions: {', '.join(target_extensions)}\n\n")
        
        # Ищем все файлы с нужными расширениями рекурсивно
        project_files = []
        for root, dirs, files in os.walk("."):
            if not any(substring in root for substring in exclude_paths):
                for file in files:
                    file_ext = os.path.splitext(file)[1].lower()
                    if file_ext in target_extensions and file not in exclude_files:
                        full_path = os.path.join(root, file)
                        project_files.append((full_path, file_ext))
        
        # Сортируем файлы по расширению для лучшей организации
        project_files.sort(key=lambda x: (x[1], x[0]))
        
        for file_path, file_ext in project_files:
            outfile.write(f"# {'='*60}\n")
            outfile.write(f"# FILE: {file_path}\n")
            outfile.write(f"# TYPE: {file_ext.upper()}\n")
            outfile.write(f"# {'='*60}\n\n")
            
            try:
                # Пробуем разные кодировки
                with open(file_path, "r", encoding="utf-8") as infile:
                    content = infile.read()
            except UnicodeDecodeError:
                try:
                    with open(file_path, "r", encoding="cp1251") as infile:
                        content = infile.read()
                except UnicodeDecodeError:
                    try:
                        with open(file_path, "r", encoding="latin-1") as infile:
                            content = infile.read()
                    except Exception as e:
                        content = f"# ERROR reading file: {str(e)}\n"
            
            outfile.write(content)
            outfile.write("\n\n\n")
    
    print(f"Объединено {len(project_files)} файлов в {output_file}")
    
    # Выводим статистику по типам файлов
    ext_count = {}
    for _, ext in project_files:
        ext_count[ext] = ext_count.get(ext, 0) + 1
    
    print("Статистика по типам файлов:")
    for ext, count in ext_count.items():
        print(f"  {ext}: {count} файлов")
    
    return output_file

if __name__ == "__main__":
    result_file = combine_project_files()
    print(f"Файл создан: {result_file}")