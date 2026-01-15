import sqlite3
import logging

logger = logging.getLogger(__name__)

class Database:
    def __init__(self, db_file):
        self.db_file = db_file
        self.init_db()
    
    def get_connection(self):
        return sqlite3.connect(self.db_file, check_same_thread=False)
    
    def init_db(self):
        """Инициализация базы данных и создание таблиц"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        # Таблица пользователей
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                full_name TEXT,
                role TEXT NOT NULL DEFAULT 'user',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Таблица вопросов от пользователей
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS questions (
                question_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                message_id INTEGER NOT NULL,
                question_text TEXT NOT NULL,
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (user_id)
            )
        ''')
        
        # Таблица ответов врачей
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS answers (
                answer_id INTEGER PRIMARY KEY AUTOINCREMENT,
                question_id INTEGER NOT NULL,
                doctor_id INTEGER NOT NULL,
                message_id INTEGER NOT NULL,
                answer_text TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (question_id) REFERENCES questions (question_id),
                FOREIGN KEY (doctor_id) REFERENCES users (user_id)
            )
        ''')
        
        # Таблица настроек админа
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS admin_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        ''')
        
        # Таблица подписок на социальные сети
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS social_subscriptions (
                user_id INTEGER NOT NULL,
                platform TEXT NOT NULL,
                subscribed INTEGER DEFAULT 0,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (user_id, platform),
                FOREIGN KEY (user_id) REFERENCES users (user_id)
            )
        ''')
        
        # Устанавливаем пароль по умолчанию, если его нет
        cursor.execute('SELECT * FROM admin_settings WHERE key = ?', ('admin_password',))
        if not cursor.fetchone():
            cursor.execute('INSERT INTO admin_settings (key, value) VALUES (?, ?)', ('admin_password', 'admin123'))
        
        conn.commit()
        conn.close()
        logger.info("База данных инициализирована")
    
    def add_user(self, user_id, username, full_name, role='user'):
        """Добавить пользователя в базу данных"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute('''
                INSERT OR IGNORE INTO users (user_id, username, full_name, role)
                VALUES (?, ?, ?, ?)
            ''', (user_id, username, full_name, role))
            conn.commit()
            return True
        except Exception as e:
            logger.error(f"Ошибка при добавлении пользователя: {e}")
            return False
        finally:
            conn.close()
    
    def get_user(self, user_id):
        """Получить информацию о пользователе"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
        result = cursor.fetchone()
        conn.close()
        if result:
            return {
                'user_id': result[0],
                'username': result[1],
                'full_name': result[2],
                'role': result[3],
                'created_at': result[4]
            }
        return None
    
    def set_user_role(self, user_id, role):
        """Установить роль пользователя"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('UPDATE users SET role = ? WHERE user_id = ?', (role, user_id))
        conn.commit()
        conn.close()
    
    def add_question(self, user_id, message_id, question_text):
        """Добавить вопрос от пользователя"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO questions (user_id, message_id, question_text)
            VALUES (?, ?, ?)
        ''', (user_id, message_id, question_text))
        question_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return question_id
    
    def get_question(self, question_id):
        """Получить вопрос по ID"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM questions WHERE question_id = ?', (question_id,))
        result = cursor.fetchone()
        conn.close()
        if result:
            return {
                'question_id': result[0],
                'user_id': result[1],
                'message_id': result[2],
                'question_text': result[3],
                'status': result[4],
                'created_at': result[5]
            }
        return None
    
    def add_answer(self, question_id, doctor_id, message_id, answer_text):
        """Добавить ответ врача"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO answers (question_id, doctor_id, message_id, answer_text)
            VALUES (?, ?, ?, ?)
        ''', (question_id, doctor_id, message_id, answer_text))
        answer_id = cursor.lastrowid
        # Обновляем статус вопроса
        cursor.execute('UPDATE questions SET status = ? WHERE question_id = ?', ('answered', question_id))
        conn.commit()
        conn.close()
        return answer_id
    
    def get_all_doctors(self):
        """Получить список всех врачей"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT user_id, username, full_name FROM users WHERE role = ?', ('doctor',))
        results = cursor.fetchall()
        conn.close()
        return [{'user_id': r[0], 'username': r[1], 'full_name': r[2]} for r in results]
    
    def get_question_by_message_id(self, user_id, message_id):
        """Получить вопрос по ID сообщения и пользователя"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM questions WHERE user_id = ? AND message_id = ?', (user_id, message_id))
        result = cursor.fetchone()
        conn.close()
        if result:
            return {
                'question_id': result[0],
                'user_id': result[1],
                'message_id': result[2],
                'question_text': result[3],
                'status': result[4],
                'created_at': result[5]
            }
        return None
    
    def get_user_questions(self, user_id, limit=10):
        """Получить вопросы пользователя"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT question_id, question_text, status, created_at 
            FROM questions 
            WHERE user_id = ? 
            ORDER BY created_at DESC 
            LIMIT ?
        ''', (user_id, limit))
        results = cursor.fetchall()
        conn.close()
        return [
            {
                'question_id': r[0],
                'question_text': r[1],
                'status': r[2],
                'created_at': r[3]
            }
            for r in results
        ]
    
    def get_answer_for_question(self, question_id):
        """Получить ответ на вопрос"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT a.answer_text, a.created_at, u.full_name, u.username
            FROM answers a
            JOIN users u ON a.doctor_id = u.user_id
            WHERE a.question_id = ?
            ORDER BY a.created_at DESC
            LIMIT 1
        ''', (question_id,))
        result = cursor.fetchone()
        conn.close()
        if result:
            return {
                'answer_text': result[0],
                'created_at': result[1],
                'doctor_name': result[2] or result[3] or 'Врач'
            }
        return None
    
    def add_doctor(self, user_id, username=None, full_name=None):
        """Добавить врача в базу данных"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            # Сначала проверяем, существует ли пользователь
            cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
            existing = cursor.fetchone()
            
            if existing:
                # Обновляем роль существующего пользователя
                cursor.execute('UPDATE users SET role = ? WHERE user_id = ?', ('doctor', user_id))
                if username or full_name:
                    cursor.execute('UPDATE users SET username = COALESCE(?, username), full_name = COALESCE(?, full_name) WHERE user_id = ?', 
                                (username, full_name, user_id))
            else:
                # Создаем нового пользователя с ролью врача
                cursor.execute('''
                    INSERT INTO users (user_id, username, full_name, role)
                    VALUES (?, ?, ?, ?)
                ''', (user_id, username, full_name, 'doctor'))
            conn.commit()
            return True
        except Exception as e:
            logger.error(f"Ошибка при добавлении врача: {e}")
            return False
        finally:
            conn.close()
    
    def remove_doctor(self, user_id):
        """Удалить врача (изменить роль на user)"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute('UPDATE users SET role = ? WHERE user_id = ? AND role = ?', ('user', user_id, 'doctor'))
            conn.commit()
            return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"Ошибка при удалении врача: {e}")
            return False
        finally:
            conn.close()
    
    def get_doctor(self, user_id):
        """Получить информацию о враче"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM users WHERE user_id = ? AND role = ?', (user_id, 'doctor'))
        result = cursor.fetchone()
        conn.close()
        if result:
            return {
                'user_id': result[0],
                'username': result[1],
                'full_name': result[2],
                'role': result[3],
                'created_at': result[4]
            }
        return None
    
    def list_all_doctors(self):
        """Получить полный список всех врачей с подробной информацией"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT user_id, username, full_name, created_at FROM users WHERE role = ? ORDER BY created_at DESC', ('doctor',))
        results = cursor.fetchall()
        conn.close()
        return [
            {
                'user_id': r[0],
                'username': r[1],
                'full_name': r[2],
                'created_at': r[3]
            }
            for r in results
        ]
    
    def get_admin_password(self):
        """Получить пароль админа"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT value FROM admin_settings WHERE key = ?', ('admin_password',))
        result = cursor.fetchone()
        conn.close()
        return result[0] if result else 'admin123'
    
    def set_admin_password(self, new_password):
        """Установить новый пароль админа"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO admin_settings (key, value)
            VALUES (?, ?)
        ''', ('admin_password', new_password))
        conn.commit()
        conn.close()
        return True
    
    def set_social_subscription(self, user_id, platform, subscribed=True):
        """Установить статус подписки на социальную сеть"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute('''
                INSERT OR REPLACE INTO social_subscriptions (user_id, platform, subscribed, updated_at)
                VALUES (?, ?, ?, CURRENT_TIMESTAMP)
            ''', (user_id, platform, 1 if subscribed else 0))
            conn.commit()
            return True
        except Exception as e:
            logger.error(f"Ошибка при установке подписки на {platform}: {e}")
            return False
        finally:
            conn.close()
    
    def get_social_subscription(self, user_id, platform):
        """Получить статус подписки на социальную сеть"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT subscribed FROM social_subscriptions 
            WHERE user_id = ? AND platform = ?
        ''', (user_id, platform))
        result = cursor.fetchone()
        conn.close()
        return result[0] == 1 if result else False
    
    def check_all_subscriptions(self, user_id):
        """Проверить подписки на все платформы"""
        return {
            'instagram': self.get_social_subscription(user_id, 'instagram'),
            'youtube': self.get_social_subscription(user_id, 'youtube')
        }
    
    def clear_all_data(self, keep_admin_settings=True):
        """Очистить все данные из базы данных"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            # Сохраняем пароль админа, если нужно
            admin_password = None
            if keep_admin_settings:
                admin_password = self.get_admin_password()
            
            # Очищаем все таблицы
            cursor.execute('DELETE FROM answers')
            cursor.execute('DELETE FROM questions')
            cursor.execute('DELETE FROM users')
            
            # Если нужно сохранить настройки админа, восстанавливаем пароль
            if keep_admin_settings and admin_password:
                cursor.execute('DELETE FROM admin_settings')
                cursor.execute('INSERT INTO admin_settings (key, value) VALUES (?, ?)', ('admin_password', admin_password))
            
            conn.commit()
            logger.info("База данных очищена")
            return True
        except Exception as e:
            logger.error(f"Ошибка при очистке базы данных: {e}")
            conn.rollback()
            return False
        finally:
            conn.close()
    
    def clear_database_completely(self):
        """Полностью очистить базу данных (включая настройки админа)"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            # Очищаем все таблицы
            cursor.execute('DELETE FROM answers')
            cursor.execute('DELETE FROM questions')
            cursor.execute('DELETE FROM users')
            cursor.execute('DELETE FROM admin_settings')
            
            # Восстанавливаем пароль по умолчанию
            cursor.execute('INSERT INTO admin_settings (key, value) VALUES (?, ?)', ('admin_password', 'admin123'))
            
            conn.commit()
            logger.info("База данных полностью очищена")
            return True
        except Exception as e:
            logger.error(f"Ошибка при полной очистке базы данных: {e}")
            conn.rollback()
            return False
        finally:
            conn.close()

