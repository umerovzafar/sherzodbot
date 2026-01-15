#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Скрипт для очистки базы данных медицинского бота
"""
import sys
import os
import config
from database import Database

# Устанавливаем кодировку для Windows
if sys.platform == 'win32':
    os.system('chcp 65001 > nul')

def main():
    """Очистка базы данных"""
    print("=" * 50)
    print("Database cleanup script")
    print("=" * 50)
    
    # Подтверждение
    response = input("\nWARNING! This will delete all data from the database.\n"
                    "Are you sure? (yes/no): ").strip().lower()
    
    if response not in ['yes', 'y']:
        print("Operation cancelled.")
        return
    
    # Выбор типа очистки
    print("\nChoose cleanup type:")
    print("1. Clear all data (keep admin settings)")
    print("2. Full cleanup (including admin settings)")
    
    choice = input("Your choice (1 or 2): ").strip()
    
    # Инициализация базы данных
    db = Database(config.DATABASE_FILE)
    
    try:
        if choice == '1':
            print("\nClearing data (keeping admin settings)...")
            if db.clear_all_data(keep_admin_settings=True):
                print("Database cleared successfully!")
                print("   - All users deleted")
                print("   - All questions deleted")
                print("   - All answers deleted")
                print("   - Admin settings preserved")
            else:
                print("Error clearing database!")
                sys.exit(1)
        
        elif choice == '2':
            print("\nFull database cleanup...")
            confirm = input("This will also delete admin settings. Continue? (yes/no): ").strip().lower()
            if confirm not in ['yes', 'y']:
                print("Operation cancelled.")
                return
            
            if db.clear_database_completely():
                print("Database fully cleared!")
                print("   - All users deleted")
                print("   - All questions deleted")
                print("   - All answers deleted")
                print("   - Admin settings deleted and restored to default")
                print("   - Admin password: admin123")
            else:
                print("Error clearing database!")
                sys.exit(1)
        
        else:
            print("Invalid choice!")
            sys.exit(1)
    
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)
    
    print("\n" + "=" * 50)
    print("Operation completed successfully!")
    print("=" * 50)

if __name__ == '__main__':
    main()

