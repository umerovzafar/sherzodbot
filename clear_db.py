#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Простой скрипт для очистки базы данных
"""
import sys
import config
from database import Database

def main():
    """Очистка базы данных"""
    db = Database(config.DATABASE_FILE)
    
    print("Clearing database...")
    
    # Очищаем все данные, но сохраняем настройки админа
    if db.clear_all_data(keep_admin_settings=True):
        print("Database cleared successfully!")
        print("  - All users deleted")
        print("  - All questions deleted")
        print("  - All answers deleted")
        print("  - Admin settings preserved")
        return 0
    else:
        print("Error clearing database!")
        return 1

if __name__ == '__main__':
    sys.exit(main())



