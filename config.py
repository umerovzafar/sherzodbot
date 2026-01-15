import os
from dotenv import load_dotenv

load_dotenv()

# Токен бота от @BotFather
BOT_TOKEN = os.getenv('BOT_TOKEN', '')

# ID канала, на который должны подписаться пользователи (например: @channel_username или -1001234567890)
CHANNEL_ID = os.getenv('CHANNEL_ID', '')

# ID канала должен быть числом (если передан username, нужно конвертировать)
# Для публичных каналов можно использовать username, для приватных - числовой ID

# Ссылки на социальные сети
INSTAGRAM_URL = 'https://www.instagram.com/sherzod_kineziolog?igsh=ZWx3eTY0azNsNTl6&utm_source=qr'
YOUTUBE_URL = 'https://youtube.com/@kineziomed_clinic?si=vTvHc9saAxjFJZpc'

# База данных
DATABASE_FILE = 'medical_bot.db'

