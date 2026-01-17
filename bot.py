import logging
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove, Contact, Location
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters
)
from telegram.constants import ParseMode
from telegram.error import Conflict, TelegramError
import config
from database import Database

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Инициализация базы данных
db = Database(config.DATABASE_FILE)


def validate_uzbek_phone(phone):
    """Валидация узбекского номера телефона"""
    if not phone:
        return None
    
    # Убираем все пробелы, дефисы и скобки
    phone = phone.replace(' ', '').replace('-', '').replace('(', '').replace(')', '').replace('.', '')
    
    # Проверяем формат +998XXXXXXXXX
    if phone.startswith('+998'):
        # Должно быть +998 + 9 цифр = 13 символов
        if len(phone) == 13 and phone[4:].isdigit():
            # Проверяем, что номер начинается с правильного кода оператора (90, 91, 93, 94, 95, 97, 98, 99)
            operator_code = phone[4:6]
            if operator_code in ['90', '91', '93', '94', '95', '97', '98', '99']:
                return phone
    
    # Проверяем формат 998XXXXXXXXX (без +)
    elif phone.startswith('998'):
        if len(phone) == 12 and phone[3:].isdigit():
            operator_code = phone[3:5]
            if operator_code in ['90', '91', '93', '94', '95', '97', '98', '99']:
                return '+' + phone
    
    # Проверяем формат 9XXXXXXXXX (без кода страны)
    elif phone.startswith('9') and len(phone) == 9 and phone.isdigit():
        operator_code = phone[0:2]
        if operator_code in ['90', '91', '93', '94', '95', '97', '98', '99']:
            return '+998' + phone
    
    return None


async def check_subscription(user_id, context: ContextTypes.DEFAULT_TYPE):
    """Проверка подписки пользователя на канал Telegram"""
    if not config.CHANNEL_ID:
        return True  # Если канал не указан, разрешаем доступ
    
    try:
        # Пытаемся получить информацию о статусе участника
        member = await context.bot.get_chat_member(config.CHANNEL_ID, user_id)
        return member.status in ['member', 'administrator', 'creator']
    except Exception as e:
        logger.error(f"Ошибка при проверке подписки: {e}")
        return False


async def check_youtube_subscription(user_id, context: ContextTypes.DEFAULT_TYPE):
    """Псевдо-проверка подписки на YouTube канал"""
    # Проверяем, подтвердил ли пользователь подписку на YouTube
    user_data_key = f'youtube_subscribed_{user_id}'
    return context.user_data.get(user_data_key, False)


async def check_instagram_subscription(user_id, context: ContextTypes.DEFAULT_TYPE):
    """Псевдо-проверка подписки на Instagram"""
    # Проверяем, подтвердил ли пользователь подписку на Instagram
    user_data_key = f'instagram_subscribed_{user_id}'
    return context.user_data.get(user_data_key, False)


async def check_all_subscriptions(user_id, context: ContextTypes.DEFAULT_TYPE):
    """Проверка подписки на все платформы"""
    # Проверяем подписку на Telegram канал
    telegram_subscribed = await check_subscription(user_id, context)
    # Проверяем подписку на YouTube (псевдо-проверка)
    youtube_subscribed = await check_youtube_subscription(user_id, context)
    # Проверяем подписку на Instagram (псевдо-проверка)
    instagram_subscribed = await check_instagram_subscription(user_id, context)
    
    all_subscribed = telegram_subscribed and youtube_subscribed and instagram_subscribed
    
    return {
        'telegram': telegram_subscribed,
        'youtube': youtube_subscribed,
        'instagram': instagram_subscribed,
        'all_subscribed': all_subscribed
    }


async def create_invite_link(user_id, context: ContextTypes.DEFAULT_TYPE):
    """Создание уникальной пригласительной ссылки для пользователя"""
    if not config.CHANNEL_ID:
        return None
    
    try:
        channel_id = config.CHANNEL_ID.lstrip('@')
        
        # Определяем chat_id для создания invite link
        if channel_id.startswith('-'):
            # Приватный канал (числовой ID)
            chat_id = int(channel_id)
        else:
            # Публичный канал (username) - получаем chat_id через get_chat
            try:
                chat = await context.bot.get_chat(channel_id)
                chat_id = chat.id
            except Exception as e:
                logger.warning(f"Не удалось получить chat_id для канала {channel_id}: {e}")
                # Возвращаем обычную ссылку для публичного канала
                return f"https://t.me/{channel_id}"
        
        # Создаем уникальную пригласительную ссылку
        invite_link = await context.bot.create_chat_invite_link(
            chat_id=chat_id,
            name=f"User_{user_id}_{context.bot.id}",  # Уникальное имя ссылки
            creates_join_request=False,  # Прямое присоединение без запроса
            expire_date=None,  # Без срока действия
            member_limit=1  # Ограничение: только один пользователь может использовать
        )
        return invite_link.invite_link
            
    except Exception as e:
        logger.error(f"Ошибка при создании пригласительной ссылки: {e}")
        # В случае ошибки возвращаем обычную ссылку
        channel_id = config.CHANNEL_ID.lstrip('@')
        if not channel_id.startswith('http'):
            return f"https://t.me/{channel_id}"
        return channel_id


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка команды /start"""
    user = update.effective_user
    user_id = user.id
    
    # Сохраняем пользователя в БД
    db.add_user(user_id, user.username, user.full_name)
    
    # Проверяем подписки на все платформы
    subscriptions = await check_all_subscriptions(user_id, context)
    
    if not subscriptions['all_subscribed']:
        # Формируем клавиатуру со всеми платформами
        keyboard = []
        missing_subs = []
        
        # Telegram канал
        if not subscriptions['telegram']:
            missing_subs.append("❌ 📢 Telegram канал")
            keyboard.append([InlineKeyboardButton("📢 Telegram каналга обуна бўлиш", callback_data='get_invite_link')])
            keyboard.append([InlineKeyboardButton("✅ Telegram каналга обуна бўлдим", callback_data='check_telegram_sub')])
        else:
            missing_subs.append("✅ 📢 Telegram канал")
        
        # YouTube канал
        if not subscriptions['youtube']:
            missing_subs.append("❌ 📺 YouTube канал")
            keyboard.append([InlineKeyboardButton("📺 YouTube каналга обуна бўлиш", url=config.YOUTUBE_URL)])
            keyboard.append([InlineKeyboardButton("✅ YouTube каналга обуна бўлдим", callback_data='check_youtube_sub')])
        else:
            missing_subs.append("✅ 📺 YouTube канал")
        
        # Instagram
        if not subscriptions['instagram']:
            missing_subs.append("❌ 📷 Instagram")
            keyboard.append([InlineKeyboardButton("📷 Instagramга обуна бўлиш", url=config.INSTAGRAM_URL)])
            keyboard.append([InlineKeyboardButton("✅ Instagramга обуна бўлдим", callback_data='check_instagram_sub')])
        else:
            missing_subs.append("✅ 📷 Instagram")
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        missing_text = "\n".join([f"• {sub}" for sub in missing_subs])
        
        welcome_text = (
            "⚠️ <b>Ундан олдин ботдан фойдаланиш учун куйидаги платформаларга обуна бўлишингиз ШАРТ:</b>\n\n"
            f"{missing_text}\n\n"
            "Юқоридаги тугмаларни босиб обуна бўлинг ва тасдиқланг!"
        )
        
        await update.message.reply_text(welcome_text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)
        return
    
    # Пользователь подписан - проверяем роль из БД
    user_info = db.get_user(user_id)
    user_role = user_info['role'] if user_info else 'user'
    
    # Если пользователь врач - показываем функционал для врача
    if user_role == 'doctor':
        doctor_welcome = (
            "👨‍⚕️ <b>Assalomu alaykum, shifokor!</b>\n\n"
            "Siz bemorlardan keladigan savollarni olasiz va ularga javob berishingiz mumkin.\n\n"
            "📋 <b>Qanday ishlaydi:</b>\n"
            "1. Bemor savol yuboradi\n"
            "2. Sizga savol bilan xabar keladi\n"
            "3. Xabarga javob (Reply) bering\n"
            "4. Javob bemorga avtomatik yuboriladi\n\n"
            "💡 <b>Maslahat:</b> Savol bilan kelgan xabarga javob bering - javob bemorga yuboriladi."
        )
        await update.message.reply_text(doctor_welcome, parse_mode=ParseMode.HTML)
        return
    
    # Обычный пользователь - показываем только кнопки
    keyboard = [
        [KeyboardButton("📍 Klinika manzili")],
        [KeyboardButton("Алоқа учун")]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    welcome_message = (
        "✅ <b>Энди саволларингизни беришингиз мумкин!</b>\n\n"
        "📝 Саволларингизни матн, видео, расм, хужжат, МРТ шаклда юборинг.\n\n"
        "⏱️ Жавоб бироз кечикиши мумкин, лекин барча хабарларга албатта жавоб бераман😊"
    )
    await update.message.reply_text(welcome_message, reply_markup=reply_markup, parse_mode=ParseMode.HTML)


async def update_subscription_status(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int):
    """Обновить статус подписок и показать соответствующее сообщение"""
    subscriptions = await check_all_subscriptions(user_id, context)
    
    if subscriptions['all_subscribed']:
        # Все подписки подтверждены - показываем только кнопки
        # Создаем reply keyboard с кнопками для локации и контакта
        keyboard = [
            [KeyboardButton("📍 Klinika manzili")],
            [KeyboardButton("Алоқа учун")]
        ]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        
        # Отправляем сообщение с reply keyboard (без текста или с минимальным)
        if update.callback_query:
            try:
                # Удаляем предыдущее сообщение с inline кнопками
                await update.callback_query.delete_message()
            except Exception as e:
                logger.debug(f"Не удалось удалить сообщение: {e}")
            # Отправляем новое сообщение с reply keyboard
            welcome_message = (
                "✅ <b>Энди саволларингизни беришингиз мумкин!</b>\n\n"
                "📝 Саволларингизни матн, видео, расм, хужжат, МРТ шаклда юборинг.\n\n"
                "⏱️ Жавоб бироз кечикиши мумкин, лекин барча хабарларга албатта жавоб бераман😊"
            )
            await update.callback_query.message.reply_text(
                welcome_message,
                reply_markup=reply_markup,
                parse_mode=ParseMode.HTML
            )
        else:
            welcome_message = (
                "✅ <b>Энди саволларингизни беришингиз мумкин!</b>\n\n"
                "📝 Саволларингизни матн, видео, расм, хужжат, МРТ шаклда юборинг.\n\n"
                "⏱️ Жавоб бироз кечикиши мумкин, лекин барча хабарларга албатта жавоб бераман😊"
            )
            await update.message.reply_text(
                welcome_message,
                reply_markup=reply_markup,
                parse_mode=ParseMode.HTML
            )
    else:
        # Есть неподтвержденные подписки
        missing_subs = []
        keyboard = []
        
        if not subscriptions['telegram']:
            missing_subs.append("❌ 📢 Telegram канал")
            keyboard.append([InlineKeyboardButton("📢 Telegram каналга обуна бўлиш", callback_data='get_invite_link')])
            keyboard.append([InlineKeyboardButton("✅ Telegram каналга обуна бўлдим", callback_data='check_telegram_sub')])
        else:
            missing_subs.append("✅ 📢 Telegram канал")
        
        if not subscriptions['youtube']:
            missing_subs.append("❌ 📺 YouTube канал")
            keyboard.append([InlineKeyboardButton("📺 YouTube каналга обуна бўлиш", url=config.YOUTUBE_URL)])
            keyboard.append([InlineKeyboardButton("✅ YouTube каналга обуна бўлдим", callback_data='check_youtube_sub')])
        else:
            missing_subs.append("✅ 📺 YouTube канал")
        
        if not subscriptions['instagram']:
            missing_subs.append("❌ 📷 Instagram")
            keyboard.append([InlineKeyboardButton("📷 Instagramга обуна бўлиш", url=config.INSTAGRAM_URL)])
            keyboard.append([InlineKeyboardButton("✅ Instagramга обуна бўлдим", callback_data='check_instagram_sub')])
        else:
            missing_subs.append("✅ 📷 Instagram")
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        missing_text = "\n".join([f"• {sub}" for sub in missing_subs])
        
        status_text = (
            "⚠️ <b>Ботдан фойдаланиш учун куйидаги платформаларга обуна бўлишингиз керак:</b>\n\n"
            f"{missing_text}\n\n"
            "Юқоридаги тугмаларни босиб обуна бўлинг ва тасдиқланг!"
        )
        
        if update.callback_query:
            try:
                await update.callback_query.edit_message_text(status_text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)
            except Exception as e:
                logger.warning(f"Не удалось отредактировать сообщение: {e}")
                await update.callback_query.message.reply_text(status_text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)
        else:
            await update.message.reply_text(status_text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)


async def get_invite_link_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка нажатия кнопки получения пригласительной ссылки"""
    query = update.callback_query
    user_id = query.from_user.id
    
    # Создаем уникальную пригласительную ссылку
    invite_link = await create_invite_link(user_id, context)
    
    if invite_link:
        message_text = (
            "🔗 <b>Sizning maxsus havolangiz:</b>\n\n"
            f"{invite_link}\n\n"
            "📢 Ushbu havola orqali kanalga obuna bo'ling.\n"
            "Obuna bo'lgach, <b>\"✅ Men obuna bo'ldim\"</b> tugmasini bosing."
        )
        await query.answer("Havola yuborildi! ✅", show_alert=False)
        sent_message = await query.message.reply_text(message_text, parse_mode=ParseMode.HTML)
        
        # Сохраняем ID сообщения для возможного удаления после подписки
        if 'invite_messages' not in context.user_data:
            context.user_data['invite_messages'] = []
        context.user_data['invite_messages'].append(sent_message.message_id)
    else:
        await query.answer("Havola yaratishda xatolik yuz berdi", show_alert=True)




async def check_telegram_subscription_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка нажатия кнопки проверки подписки на Telegram канал"""
    query = update.callback_query
    user_id = query.from_user.id
    
    # Проверяем подписку
    is_subscribed = await check_subscription(user_id, context)
    
    if is_subscribed:
        await query.answer("Telegram каналга обуна тасдиқланди! ✅", show_alert=False)
        
        # Удаляем все сообщения со ссылками на канал
        if 'invite_messages' in context.user_data:
            deleted_count = 0
            for msg_id in context.user_data['invite_messages']:
                try:
                    await context.bot.delete_message(chat_id=user_id, message_id=msg_id)
                    deleted_count += 1
                except Exception as e:
                    logger.debug(f"Не удалось удалить сообщение {msg_id}: {e}")
            # Очищаем список сообщений
            context.user_data['invite_messages'] = []
            if deleted_count > 0:
                logger.info(f"Удалено {deleted_count} сообщений со ссылками на канал для пользователя {user_id}")
        
        # Проверяем все подписки и обновляем сообщение
        await update_subscription_status(update, context, user_id)
    else:
        # Пользователь не подписан - создаем новую ссылку и сообщаем об ошибке
        await query.answer("❌ Siz hali kanalga obuna bo'lmadingiz", show_alert=True)
        
        # Создаем новую уникальную пригласительную ссылку
        invite_link = await create_invite_link(user_id, context)
        
        if invite_link:
            error_text = (
                "❌ <b>Obuna tekshiruvi</b>\n\n"
                "Siz hali kanalga obuna bo'lmadingiz.\n\n"
                "🔗 <b>Yangi maxsus havola:</b>\n\n"
                f"{invite_link}\n\n"
                "📢 Iltimos, ushbu havola orqali kanalga obuna bo'ling.\n"
                "Obuna bo'lgach, <b>\"✅ Men obuna bo'ldim\"</b> tugmasini bosing."
            )
            
            # Редактируем текущее сообщение
            keyboard = [
                [InlineKeyboardButton("📢 Kanalga obuna bo'lish", callback_data='get_invite_link')],
                [InlineKeyboardButton("✅ Men obuna bo'ldim", callback_data='check_telegram_sub')]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            try:
                await query.edit_message_text(error_text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)
            except:
                # Если не удалось отредактировать, отправляем новое сообщение
                sent_message = await query.message.reply_text(error_text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)
                # Сохраняем ID для возможного удаления
                if 'invite_messages' not in context.user_data:
                    context.user_data['invite_messages'] = []
                context.user_data['invite_messages'].append(sent_message.message_id)
        else:
            error_text = (
                "❌ <b>Obuna tekshiruvi</b>\n\n"
                "Siz hali kanalga obuna bo'lmadingiz.\n\n"
                "Iltimos, kanalga obuna bo'ling va qayta urinib ko'ring."
            )
            keyboard = [
                [InlineKeyboardButton("✅ Men obuna bo'ldim", callback_data='check_telegram_sub')]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            try:
                await query.edit_message_text(error_text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)
            except:
                await query.message.reply_text(error_text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)


async def check_youtube_subscription_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка нажатия кнопки проверки подписки на YouTube канал (псевдо-проверка)"""
    query = update.callback_query
    user_id = query.from_user.id
    
    # Помечаем, что пользователь подтвердил подписку на YouTube
    user_data_key = f'youtube_subscribed_{user_id}'
    context.user_data[user_data_key] = True
    
    await query.answer("YouTube каналга обуна тасдиқланди! ✅", show_alert=False)
    
    # Проверяем все подписки и обновляем сообщение
    await update_subscription_status(update, context, user_id)


async def check_instagram_subscription_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка нажатия кнопки проверки подписки на Instagram (псевдо-проверка)"""
    query = update.callback_query
    user_id = query.from_user.id
    
    # Помечаем, что пользователь подтвердил подписку на Instagram
    user_data_key = f'instagram_subscribed_{user_id}'
    context.user_data[user_data_key] = True
    
    await query.answer("Instagramга обуна тасдиқланди! ✅", show_alert=False)
    
    # Проверяем все подписки и обновляем сообщение
    await update_subscription_status(update, context, user_id)


async def handle_admin_reply_keyboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка нажатий на кнопки reply keyboard админ-панели"""
    user_id = update.effective_user.id
    message = update.message
    text = message.text or ""
    
    # Проверяем авторизацию
    if 'admin_authorized' not in context.user_data or not context.user_data['admin_authorized']:
        return False
    
    # Обрабатываем кнопки админ-панели
    if text == "➕ Shifokor qo'shish":
        keyboard = [[KeyboardButton("📱 Kontaktni yuborish", request_contact=True)]]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
        
        sent_msg = await message.reply_text(
            "➕ <b>Shifokor qo'shish</b>\n\n"
            "Quyidagi usullardan birini tanlang:\n\n"
            "1️⃣ <b>Kontakt orqali (tavsiya etiladi):</b>\n"
            "   Quyidagi tugmani bosing va shifokor o'z kontaktingizni yuborsin.\n"
            "   Bu usul avtomatik ravishda user ID ni aniqlaydi.\n\n"
            "2️⃣ <b>Username orqali:</b>\n"
            "   Username ni yuboring (masalan: @username yoki username)\n"
            "   Agar shifokor kanalda bo'lsa, uni topamiz.\n\n"
            "3️⃣ <b>User ID orqali:</b>\n"
            "   User ID ni yuboring (masalan: 123456789)\n\n"
            "⚠️ <b>Eslatma:</b> Telegram Bot API telefon raqami orqali user ID ni aniqlash imkonini bermaydi.\n"
            "Shuning uchun eng yaxshi usul - shifokor o'z kontaktingizni yuborishi.",
            parse_mode=ParseMode.HTML,
            reply_markup=reply_markup
        )
        save_admin_message_id(context, sent_msg.message_id)
        context.user_data['admin_waiting_for'] = 'add_doctor'
        return True
    
    elif text == "➖ Shifokorni olib tashlash":
        sent_msg = await message.reply_text(
            "➖ <b>Shifokorni olib tashlash</b>\n\n"
            "Olib tashlash uchun shifokor ID sini yuboring:\n\n"
            "Format: <code>ID:123456789</code>\n\n"
            "Yoki shunchaki ID raqamini yuboring.",
            parse_mode=ParseMode.HTML,
            reply_markup=ReplyKeyboardRemove()
        )
        save_admin_message_id(context, sent_msg.message_id)
        context.user_data['admin_waiting_for'] = 'remove_doctor'
        return True
    
    elif text == "📋 Shifokorlar ro'yxati":
        doctors = db.list_all_doctors()
        if not doctors:
            sent_msg = await message.reply_text("📭 Hozircha shifokorlar yo'q.", reply_markup=ReplyKeyboardRemove())
            save_admin_message_id(context, sent_msg.message_id)
            await show_admin_panel(update, context)
            return True
        
        message_text = f"👨‍⚕️ <b>Barcha shifokorlar ({len(doctors)}):</b>\n\n"
        for i, doctor in enumerate(doctors, 1):
            username_text = f"@{doctor['username']}" if doctor['username'] else "Username yo'q"
            full_name_text = doctor['full_name'] or "Ism yo'q"
            message_text += (
                f"{i}. <b>{full_name_text}</b>\n"
                f"   ID: <code>{doctor['user_id']}</code>\n"
                f"   Username: {username_text}\n\n"
            )
        
        sent_msg = await message.reply_text(message_text, parse_mode=ParseMode.HTML, reply_markup=ReplyKeyboardRemove())
        save_admin_message_id(context, sent_msg.message_id)
        await show_admin_panel(update, context)
        return True
    
    elif text == "🔍 Kanalda qidirish":
        # Поиск администраторов канала
        if not config.CHANNEL_ID:
            sent_msg = await message.reply_text("❌ Kanal ID o'rnatilmagan.", reply_markup=ReplyKeyboardRemove())
            save_admin_message_id(context, sent_msg.message_id)
            await show_admin_panel(update, context)
            return True
        
        try:
            # Получаем список администраторов канала
            admins = await context.bot.get_chat_administrators(config.CHANNEL_ID)
            if not admins:
                sent_msg = await message.reply_text("📭 Kanadda administratorlar topilmadi.", reply_markup=ReplyKeyboardRemove())
                save_admin_message_id(context, sent_msg.message_id)
                await show_admin_panel(update, context)
                return True
            
            message_text = f"👥 <b>Kanal administratorlari ({len(admins)}):</b>\n\n"
            for i, admin in enumerate(admins, 1):
                admin_user = admin.user
                username_text = f"@{admin_user.username}" if admin_user.username else "Username yo'q"
                full_name_text = admin_user.full_name or admin_user.first_name or "Ism yo'q"
                status_text = admin.status
                message_text += (
                    f"{i}. <b>{full_name_text}</b>\n"
                    f"   ID: <code>{admin_user.id}</code>\n"
                    f"   Username: {username_text}\n"
                    f"   Status: {status_text}\n\n"
                )
            
            message_text += "\n💡 <b>Maslahat:</b> Agar shifokor kanalda administrator bo'lsa, uning ID sini ko'chirib qo'shishingiz mumkin."
            
            sent_msg = await message.reply_text(message_text, parse_mode=ParseMode.HTML, reply_markup=ReplyKeyboardRemove())
            save_admin_message_id(context, sent_msg.message_id)
            await show_admin_panel(update, context)
            return True
        except Exception as e:
            logger.error(f"Ошибка при получении администраторов канала: {e}")
            sent_msg = await message.reply_text(
                f"❌ Xatolik yuz berdi: {str(e)}\n\n"
                "Iltimos, bot kanalda administrator ekanligini tekshiring.",
                reply_markup=ReplyKeyboardRemove()
            )
            save_admin_message_id(context, sent_msg.message_id)
            await show_admin_panel(update, context)
            return True
    
    elif text == "🔑 Parolni o'zgartirish":
        sent_msg = await message.reply_text(
            "🔑 <b>Parolni o'zgartirish</b>\n\n"
            "Yangi parolni yuboring:\n\n"
            "Format: <code>parol:yangi_parol</code>\n\n"
            "Yoki shunchaki yangi parolni yuboring.",
            parse_mode=ParseMode.HTML,
            reply_markup=ReplyKeyboardRemove()
        )
        save_admin_message_id(context, sent_msg.message_id)
        context.user_data['admin_waiting_for'] = 'change_password'
        return True
    
    elif text == "📢 Foydalanuvchilarga xabar yuborish":
        sent_msg = await message.reply_text(
            "📢 <b>Foydalanuvchilarga xabar yuborish</b>\n\n"
            "Xabarni yuborish uchun:\n\n"
            "1️⃣ Tayyor xabarni <b>forward</b> qiling (qayta yuborish)\n"
            "2️⃣ Yoki to'g'ridan-to'g'ri xabar yuboring (matn, rasm, video, hujjat va h.k.)\n\n"
            "⚠️ <b>Eslatma:</b> Xabar barcha foydalanuvchilarga yuboriladi (shifokorlar bundan mustasno).",
            parse_mode=ParseMode.HTML,
            reply_markup=ReplyKeyboardRemove()
        )
        save_admin_message_id(context, sent_msg.message_id)
        context.user_data['admin_waiting_for'] = 'broadcast_message'
        return True
    
    elif text == "🚪 Chiqish":
        # Удаляем историю сообщений бота
        await delete_bot_messages(update, context)
        
        # Очищаем user_data (удаляем только админские данные)
        context.user_data.pop('admin_authorized', None)
        context.user_data.pop('admin_waiting_for', None)
        context.user_data.pop('admin_waiting_login', None)
        context.user_data.pop('admin_waiting_password', None)
        context.user_data.pop('admin_messages', None)
        
        # Отправляем сообщение о выходе
        exit_message = await message.reply_text(
            "✅ Siz admin paneldan chiqdingiz.\n\n"
            "💬 Bot yangilandi. Yangi suhbatni boshlash uchun /start buyrug'ini yuboring.",
            reply_markup=ReplyKeyboardRemove()
        )
        
        # Автоматически вызываем /start через небольшую задержку
        await asyncio.sleep(1)
        await start(update, context)
        
        return True
    
    return False


async def delete_bot_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Удаление всех сообщений бота из админ-панели"""
    user_id = update.effective_user.id
    
    # Получаем список сообщений для удаления
    admin_messages = context.user_data.get('admin_messages', [])
    
    if admin_messages:
        deleted_count = 0
        for msg_id in admin_messages:
            try:
                await context.bot.delete_message(chat_id=user_id, message_id=msg_id)
                deleted_count += 1
            except Exception as e:
                logger.debug(f"Не удалось удалить сообщение {msg_id}: {e}")
        
        logger.info(f"Удалено {deleted_count} сообщений из админ-панели для пользователя {user_id}")
    
    # Очищаем список сообщений
    context.user_data.pop('admin_messages', None)


def save_admin_message_id(context: ContextTypes.DEFAULT_TYPE, message_id: int):
    """Сохранение ID сообщения бота в админ-панели"""
    if 'admin_messages' not in context.user_data:
        context.user_data['admin_messages'] = []
    context.user_data['admin_messages'].append(message_id)


async def admin_reply_text(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str, **kwargs):
    """Отправка сообщения в админ-панели с сохранением ID"""
    message = update.message or update.callback_query.message if update.callback_query else None
    if not message:
        return None
    
    sent_message = await message.reply_text(text, **kwargs)
    save_admin_message_id(context, sent_message.message_id)
    return sent_message


async def broadcast_to_users(update: Update, context: ContextTypes.DEFAULT_TYPE, message_to_send):
    """Рассылка сообщения всем пользователям кроме врачей"""
    admin_user_id = update.effective_user.id
    status_msg = await update.message.reply_text("📢 Xabar yuborilmoqda...")
    
    # Получаем список всех пользователей кроме врачей
    users = db.get_all_users_except_doctors()
    
    if not users:
        await status_msg.edit_text("❌ Foydalanuvchilar topilmadi.")
        context.user_data.pop('admin_waiting_for', None)
        await show_admin_panel(update, context)
        return
    
    total_users = len(users)
    successful = 0
    failed = 0
    
    # Отправляем сообщение каждому пользователю
    for user in users:
        try:
            user_id = user['user_id']
            
            # Пропускаем админа, чтобы не отправлять сообщение самому себе
            if user_id == admin_user_id:
                continue
            
            # Если сообщение переслано, пытаемся использовать forward_message
            is_forwarded = hasattr(message_to_send, 'forward_origin') and message_to_send.forward_origin is not None
            if is_forwarded:
                try:
                    # Пытаемся получить информацию об источнике пересылки
                    forward_origin = message_to_send.forward_origin
                    from_chat_id = None
                    
                    # Пробуем разные способы получить chat_id источника
                    if hasattr(forward_origin, 'chat') and forward_origin.chat:
                        from_chat_id = forward_origin.chat.id
                    elif hasattr(forward_origin, 'sender_chat') and forward_origin.sender_chat:
                        from_chat_id = forward_origin.sender_chat.id
                    
                    # Если не удалось получить from_chat_id, используем текущий чат
                    if not from_chat_id:
                        from_chat_id = message_to_send.chat_id
                    
                    await context.bot.forward_message(
                        chat_id=user_id,
                        from_chat_id=from_chat_id,
                        message_id=message_to_send.message_id
                    )
                    successful += 1
                    await asyncio.sleep(0.05)
                    continue
                except Exception as e:
                    # Если forward не работает, пытаемся отправить как обычное сообщение
                    logger.warning(f"Не удалось переслать сообщение пользователю {user_id}, пробуем отправить как обычное: {e}")
                    # Продолжаем к обычной отправке
                    pass
            
            # Отправляем сообщение в зависимости от типа (если не переслано или forward не сработал)
            if message_to_send.photo:
                await context.bot.send_photo(
                    chat_id=user_id,
                    photo=message_to_send.photo[-1].file_id,
                    caption=message_to_send.caption,
                    parse_mode=ParseMode.HTML if message_to_send.caption_html else None
                )
                successful += 1
            elif message_to_send.video:
                await context.bot.send_video(
                    chat_id=user_id,
                    video=message_to_send.video.file_id,
                    caption=message_to_send.caption,
                    parse_mode=ParseMode.HTML if message_to_send.caption_html else None
                )
                successful += 1
            elif message_to_send.document:
                await context.bot.send_document(
                    chat_id=user_id,
                    document=message_to_send.document.file_id,
                    caption=message_to_send.caption,
                    parse_mode=ParseMode.HTML if message_to_send.caption_html else None
                )
                successful += 1
            elif message_to_send.audio:
                await context.bot.send_audio(
                    chat_id=user_id,
                    audio=message_to_send.audio.file_id,
                    caption=message_to_send.caption,
                    parse_mode=ParseMode.HTML if message_to_send.caption_html else None
                )
                successful += 1
            elif message_to_send.voice:
                await context.bot.send_voice(
                    chat_id=user_id,
                    voice=message_to_send.voice.file_id,
                    caption=message_to_send.caption,
                    parse_mode=ParseMode.HTML if message_to_send.caption_html else None
                )
                successful += 1
            elif message_to_send.video_note:
                await context.bot.send_video_note(
                    chat_id=user_id,
                    video_note=message_to_send.video_note.file_id
                )
                successful += 1
            elif message_to_send.sticker:
                await context.bot.send_sticker(
                    chat_id=user_id,
                    sticker=message_to_send.sticker.file_id
                )
                successful += 1
            elif message_to_send.text:
                # Если это просто текст, отправляем его
                await context.bot.send_message(
                    chat_id=user_id,
                    text=message_to_send.text,
                    parse_mode=ParseMode.HTML if message_to_send.text_html else None
                )
                successful += 1
            else:
                # Если тип сообщения не поддерживается, пытаемся переслать
                is_forwarded = hasattr(message_to_send, 'forward_origin') and message_to_send.forward_origin is not None
                if not is_forwarded:
                    failed += 1
                    logger.warning(f"Неподдерживаемый тип сообщения для пользователя {user_id}")
                    continue
            
            # Небольшая задержка, чтобы не превысить лимиты API
            await asyncio.sleep(0.05)
            
        except Exception as e:
            failed += 1
            logger.error(f"Ошибка при отправке сообщения пользователю {user_id}: {e}")
            # Продолжаем отправку остальным пользователям
    
    # Обновляем статус
    result_text = (
        f"✅ <b>Xabar yuborildi!</b>\n\n"
        f"📊 <b>Statistika:</b>\n"
        f"• Jami foydalanuvchilar: {total_users}\n"
        f"• Muvaffaqiyatli: {successful}\n"
        f"• Xatolik: {failed}"
    )
    
    await status_msg.edit_text(result_text, parse_mode=ParseMode.HTML)
    save_admin_message_id(context, status_msg.message_id)
    
    context.user_data.pop('admin_waiting_for', None)
    await show_admin_panel(update, context)


async def handle_admin_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка ввода данных админом"""
    user_id = update.effective_user.id
    message = update.message
    text = message.text or ""
    
    # Сначала проверяем, не нажата ли кнопка reply keyboard
    if await handle_admin_reply_keyboard(update, context):
        return True
    
    # Проверяем, ожидает ли админ ввода данных
    if 'admin_waiting_for' not in context.user_data:
        return False
    
    if 'admin_authorized' not in context.user_data or not context.user_data['admin_authorized']:
        return False
    
    waiting_for = context.user_data['admin_waiting_for']
    
    if waiting_for == 'add_doctor':
        user_id_to_add = None
        username = None
        full_name = None
        phone_number = None
        
        # Проверяем, отправлен ли контакт
        if message.contact:
            contact = message.contact
            phone_number = contact.phone_number
            
            # Если пользователь поделился своим контактом, у нас есть user_id
            if contact.user_id:
                user_id_to_add = contact.user_id
                full_name = contact.first_name
                if contact.last_name:
                    full_name = f"{contact.first_name} {contact.last_name}"
            else:
                # Если это не собственный контакт, валидируем номер и пытаемся найти пользователя
                validated_phone = validate_uzbek_phone(phone_number)
                if not validated_phone:
                    await message.reply_text(
                        "❌ Noto'g'ri telefon raqami formati.\n\n"
                        "Iltimos, o'z kontaktingizni yuboring yoki telefon raqamini to'g'ri formatda kiriting:\n"
                        "Masalan: <code>+998901234567</code>",
                        parse_mode=ParseMode.HTML
                    )
                    return True
                
                await message.reply_text(
                    f"📱 Telefon raqami qabul qilindi: <code>{validated_phone}</code>\n\n"
                    "⚠️ Bu kontakt sizning emas. User ID ni yuboring yoki shifokor o'z kontaktingizni yuborsin.",
                    parse_mode=ParseMode.HTML
                )
                return True
        
        # Если не контакт, проверяем текст - может быть номер телефона, username или ID
        elif text:
            # Проверяем, является ли это номером телефона
            validated_phone = validate_uzbek_phone(text)
            if validated_phone:
                keyboard = [[KeyboardButton("📱 Kontaktni yuborish", request_contact=True)]]
                reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
                
                await message.reply_text(
                    f"📱 Telefon raqami qabul qilindi: <code>{validated_phone}</code>\n\n"
                    "⚠️ <b>Muhim:</b> Telegram Bot API telefon raqami orqali user ID ni aniqlash imkonini bermaydi.\n\n"
                    "Shifokorni qo'shish uchun quyidagi usullardan birini tanlang:\n\n"
                    "1️⃣ <b>Kontakt orqali:</b> Quyidagi tugmani bosing va shifokor o'z kontaktingizni yuborsin\n"
                    "2️⃣ <b>Username orqali:</b> Username ni kiriting (masalan: @username)\n"
                    "3️⃣ <b>User ID orqali:</b> User ID ni kiriting (masalan: 123456789)\n\n"
                    "💡 <b>Maslahat:</b> Eng oson usul - shifokor o'z kontaktingizni yuborishi.",
                    parse_mode=ParseMode.HTML,
                    reply_markup=reply_markup
                )
                return True
            
            # Проверяем, является ли это username
            username_to_search = text.lstrip('@').strip()
            if username_to_search and not username_to_search.isdigit():
                # Пытаемся найти пользователя по username через get_chat
                try:
                    chat = await context.bot.get_chat(f"@{username_to_search}")
                    if chat.type == 'private':
                        # Это личный чат - значит нашли пользователя
                        user_id_to_add = chat.id
                        username = chat.username
                        full_name = chat.full_name or chat.first_name
                        
                        # Пытаемся проверить, является ли пользователь участником канала
                        in_channel = False
                        channel_status = None
                        if config.CHANNEL_ID:
                            try:
                                member = await context.bot.get_chat_member(config.CHANNEL_ID, user_id_to_add)
                                in_channel = True
                                channel_status = str(member.status)
                            except:
                                # Пользователь не в канале
                                pass
                        
                        # Сообщаем о результате поиска
                        if in_channel:
                            status_text = channel_status if channel_status else "Noma'lum"
                            full_name_display = full_name or "Noma'lum"
                            message_text = (
                                "✅ Foydalanuvchi topildi va kanalda mavjud!\n\n"
                                f"👤 Username: <code>@{username_to_search}</code>\n"
                                f"📝 Ism: {full_name_display}\n"
                                f"🆔 ID: <code>{user_id_to_add}</code>\n"
                                f"📢 Kanalda: Ha (Status: {status_text})"
                            )
                            await message.reply_text(
                                message_text,
                                parse_mode=ParseMode.HTML
                            )
                        else:
                            full_name_display = full_name or "Noma'lum"
                            message_text = (
                                "✅ Foydalanuvchi topildi!\n\n"
                                f"👤 Username: <code>@{username_to_search}</code>\n"
                                f"📝 Ism: {full_name_display}\n"
                                f"🆔 ID: <code>{user_id_to_add}</code>\n"
                                "⚠️ Kanalda: Topilmadi (lekin qo'shish mumkin)"
                            )
                            await message.reply_text(
                                message_text,
                                parse_mode=ParseMode.HTML
                            )
                    else:
                        await message.reply_text(
                            f"❌ <code>@{username_to_search}</code> - bu kanal yoki guruh, foydalanuvchi emas.\n\n"
                            "Iltimos, shifokor username ni kiriting (masalan: @username).",
                            parse_mode=ParseMode.HTML
                        )
                        return True
                except Exception as e:
                    logger.warning(f"Не удалось найти пользователя по username @{username_to_search}: {e}")
                    await message.reply_text(
                        f"❌ Foydalanuvchi <code>@{username_to_search}</code> topilmadi.\n\n"
                        "Iltimos, quyidagilarni tekshiring:\n"
                        "• Username to'g'ri kiritilganligi\n"
                        "• Foydalanuvchi botga yozgan yoki o'z kontaktingizni yuborgan\n\n"
                        "Yoki boshqa usulni tanlang.",
                        parse_mode=ParseMode.HTML
                    )
                    return True
            
            # Проверяем, является ли это ID
            if not user_id_to_add:
                if text.startswith('ID:'):
                    try:
                        user_id_to_add = int(text.split('ID:')[1].strip())
                    except:
                        pass
                else:
                    try:
                        user_id_to_add = int(text.strip())
                    except:
                        pass
        
        # Если user_id не найден
        if not user_id_to_add:
            keyboard = [[KeyboardButton("📱 Kontaktni yuborish", request_contact=True)]]
            reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
            
            await message.reply_text(
                "❌ User ID topilmadi.\n\n"
                "Iltimos, quyidagi usullardan birini tanlang:\n\n"
                "1️⃣ <b>Kontakt orqali (tavsiya etiladi):</b>\n"
                "   Quyidagi tugmani bosing va shifokor o'z kontaktingizni yuborsin.\n"
                "   Bu usul avtomatik ravishda user ID ni aniqlaydi.\n\n"
                "2️⃣ <b>User ID orqali:</b>\n"
                "   User ID ni kiriting (masalan: 123456789)\n\n"
                "⚠️ <b>Eslatma:</b> Telegram Bot API telefon raqami orqali user ID ni aniqlash imkonini bermaydi.\n"
                "Shuning uchun eng yaxshi usul - shifokor o'z kontaktingizni yuborishi.",
                parse_mode=ParseMode.HTML,
                reply_markup=reply_markup
            )
            return True
        
        # Пытаемся получить информацию о пользователе из Telegram
        try:
            chat = await context.bot.get_chat(user_id_to_add)
            username = chat.username
            if not full_name:
                full_name = chat.full_name or chat.first_name
        except Exception as e:
            logger.warning(f"Не удалось получить информацию о пользователе {user_id_to_add}: {e}")
            if not full_name:
                full_name = None
        
        # Добавляем врача
        if db.add_doctor(user_id_to_add, username, full_name):
            full_name_display = full_name or "Noma'lum"
            username_display = username if username else "yo'q"
            result_text = (
                f"✅ Shifokor qo'shildi!\n\n"
                f"👤 ID: <code>{user_id_to_add}</code>\n"
                f"📝 Ism: {full_name_display}\n"
                f"🔗 Username: @{username_display}"
            )
            if phone_number:
                validated_phone = validate_uzbek_phone(phone_number)
                if validated_phone:
                    result_text += f"\n📱 Telefon: <code>{validated_phone}</code>"
            
            sent_msg = await message.reply_text(result_text, parse_mode=ParseMode.HTML)
            save_admin_message_id(context, sent_msg.message_id)
        else:
            sent_msg = await message.reply_text("❌ Xatolik yuz berdi. Shifokor qo'shilmadi.")
            save_admin_message_id(context, sent_msg.message_id)
        
        context.user_data.pop('admin_waiting_for', None)
        await show_admin_panel(update, context)
        return True
    
    elif waiting_for == 'remove_doctor':
        # Извлекаем ID из текста
        user_id_to_remove = None
        if text.startswith('ID:'):
            try:
                user_id_to_remove = int(text.split('ID:')[1].strip())
            except:
                pass
        else:
            try:
                user_id_to_remove = int(text.strip())
            except:
                pass
        
        if not user_id_to_remove:
            await message.reply_text("❌ Noto'g'ri format. ID raqamini yuboring.")
            return True
        
        if db.remove_doctor(user_id_to_remove):
            sent_msg = await message.reply_text(f"✅ Shifokor olib tashlandi!\n\n👤 ID: <code>{user_id_to_remove}</code>", parse_mode=ParseMode.HTML)
            save_admin_message_id(context, sent_msg.message_id)
        else:
            sent_msg = await message.reply_text(f"❌ Shifokor topilmadi yoki allaqachon olib tashlangan.\n\n👤 ID: <code>{user_id_to_remove}</code>", parse_mode=ParseMode.HTML)
            save_admin_message_id(context, sent_msg.message_id)
        
        context.user_data.pop('admin_waiting_for', None)
        await show_admin_panel(update, context)
        return True
    
    elif waiting_for == 'change_password':
        # Извлекаем пароль из текста
        new_password = None
        if text.startswith('parol:'):
            new_password = text.split('parol:')[1].strip()
        else:
            new_password = text.strip()
        
        if not new_password or len(new_password) < 3:
            await message.reply_text("❌ Parol kamida 3 belgidan iborat bo'lishi kerak.")
            return True
        
        db.set_admin_password(new_password)
        sent_msg = await message.reply_text(f"✅ Parol muvaffaqiyatli o'zgartirildi!\n\nYangi parol: <code>{new_password}</code>", parse_mode=ParseMode.HTML)
        save_admin_message_id(context, sent_msg.message_id)
        
        context.user_data.pop('admin_waiting_for', None)
        await show_admin_panel(update, context)
        return True
    
    elif waiting_for == 'broadcast_message':
        # Проверяем, что есть сообщение для отправки (пересланное или обычное)
        is_forwarded = hasattr(message, 'forward_origin') and message.forward_origin is not None
        has_content = bool(message.text or message.photo or message.video or message.document or message.audio or message.voice or message.video_note or message.sticker)
        
        if not is_forwarded and not has_content:
            await message.reply_text(
                "❌ Xabar topilmadi.\n\n"
                "Iltimos, yubormoqchi bo'lgan xabarni <b>forward</b> qiling yoki to'g'ridan-to'g'ri yuboring.",
                parse_mode=ParseMode.HTML
            )
            return True
        
        # Запускаем рассылку
        await broadcast_to_users(update, context, message)
        return True
    
    return False


async def handle_user_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка сообщений от пользователей"""
    message = update.message
    
    # Проверяем авторизацию админа (если идет процесс авторизации)
    if 'admin_waiting_login' in context.user_data and context.user_data['admin_waiting_login']:
        # Пользователь вводит логин (только текст, не контакт)
        if message.text:
            login = message.text.strip()
            if login == 'admin':
                context.user_data['admin_login'] = login
                context.user_data['admin_waiting_password'] = True
                context.user_data.pop('admin_waiting_login', None)
                await message.reply_text("✅ Login qabul qilindi.\n\nEndi parolni kiriting:")
            else:
                await message.reply_text("❌ Noto'g'ri login! Qayta urinib ko'ring.\n\nLoginni kiriting:")
        else:
            await message.reply_text("❌ Iltimos, loginni matn shaklida kiriting.")
        return
    
    if 'admin_waiting_password' in context.user_data and context.user_data['admin_waiting_password']:
        # Пользователь вводит пароль (только текст, не контакт)
        if message.text:
            password = message.text.strip()
            if password == db.get_admin_password():
                context.user_data['admin_authorized'] = True
                context.user_data.pop('admin_waiting_password', None)
                context.user_data.pop('admin_login', None)
                await show_admin_panel(update, context)
            else:
                await message.reply_text("❌ Noto'g'ri parol! Qayta urinib ko'ring.\n\nParolni kiriting:")
        else:
            await message.reply_text("❌ Iltimos, parolni matn shaklida kiriting.")
        return
    
    # Проверяем, не ожидает ли админ ввода данных для админ-панели
    if await handle_admin_input(update, context):
        return
    
    user = update.effective_user
    user_id = user.id
    message = update.message
    
    # Проверяем все подписки
    subscriptions = await check_all_subscriptions(user_id, context)
    if not subscriptions['all_subscribed']:
        # Формируем список неподписанных платформ
        missing_subs = []
        keyboard = []
        
        if not subscriptions['telegram']:
            missing_subs.append("❌ 📢 Telegram канал")
            keyboard.append([InlineKeyboardButton("📢 Telegram каналга обуна бўлиш", callback_data='get_invite_link')])
            keyboard.append([InlineKeyboardButton("✅ Telegram каналга обуна бўлдим", callback_data='check_telegram_sub')])
        else:
            missing_subs.append("✅ 📢 Telegram канал")
        
        if not subscriptions['youtube']:
            missing_subs.append("❌ 📺 YouTube канал")
            keyboard.append([InlineKeyboardButton("📺 YouTube каналга обуна бўлиш", url=config.YOUTUBE_URL)])
            keyboard.append([InlineKeyboardButton("✅ YouTube каналга обуна бўлдим", callback_data='check_youtube_sub')])
        else:
            missing_subs.append("✅ 📺 YouTube канал")
        
        if not subscriptions['instagram']:
            missing_subs.append("❌ 📷 Instagram")
            keyboard.append([InlineKeyboardButton("📷 Instagramга обуна бўлиш", url=config.INSTAGRAM_URL)])
            keyboard.append([InlineKeyboardButton("✅ Instagramга обуна бўлдим", callback_data='check_instagram_sub')])
        else:
            missing_subs.append("✅ 📷 Instagram")
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        missing_text = "\n".join([f"• {sub}" for sub in missing_subs])
        
        await message.reply_text(
            "⚠️ <b>Ботдан фойдаланиш учун куйидаги платформаларга обуна бўлишингиз керак:</b>\n\n"
            f"{missing_text}\n\n"
            "Юқоридаги тугмаларни босиб обуна бўлинг ва тасдиқланг!",
            reply_markup=reply_markup,
            parse_mode=ParseMode.HTML
        )
        return
    
    # Проверяем, нажата ли кнопка "Алоқа учун"
    if message.text and message.text.strip() == "Алоқа учун":
        contact_text = (
            "📞 <b>Биз билан боғланиш учун:</b>\n\n"
            "📱 <a href=\"tel:+9989989404655\">99 894-046-55-00</a>\n"
            "📱 <a href=\"tel:+9989989401655\">99 894-016-55-00</a>\n"
            "📱 <a href=\"tel:+99899899489215\">99 899-489-92-15</a>\n\n"
            "💬 <i>Рақамни босиб қўнғироқ қилинг</i>"
        )
        await message.reply_text(contact_text, parse_mode=ParseMode.HTML)
        return
    
    # Проверяем, нажата ли кнопка "📍 Klinika manzili"
    if message.text and message.text.strip() == "📍 Klinika manzili":
        # Координаты клиники: 41.287102, 69.184537
        await message.reply_location(
            latitude=41.287102,
            longitude=69.184537
        )
        # Отправляем сообщение с адресом
        address_text = (
            "📍 <b>Клиника манзили:</b>\n\n"
            "Тошкент шаҳри, Учтепа тумани, 23-квартал, 59-уй"
        )
        await message.reply_text(address_text, parse_mode=ParseMode.HTML)
        return
    
    # Проверяем, что есть содержимое сообщения
    question_text = message.text or message.caption
    if not question_text and not (message.photo or message.video or message.document):
        await message.reply_text(
            "❓ Iltimos, savolingizni matn, rasm, video yoki hujjat shaklida yuboring."
        )
        return
    
    # Если нет текста, но есть медиа
    if not question_text:
        question_text = "Media-xabar"
    
    # Сохраняем вопрос в БД
    question_id = db.add_question(user_id, message.message_id, question_text)
    
    # Получаем всех врачей
    doctors = db.get_all_doctors()
    
    if not doctors:
        reply_text = (
            "⏳ <b>Shifokorlar hozircha mavjud emas</b>\n\n"
            f"📝 Savolingiz saqlandi (ID: <code>{question_id}</code>)\n"
            "Shifokor mavjud bo'lgach, sizga javob beradi.\n\n"
            "💡 Savollaringiz holatini kuzatish uchun /myquestions buyrug'idan foydalaning."
        )
        await message.reply_text(reply_text, parse_mode=ParseMode.HTML)
        return
    
    # Формируем сообщение для врачей
    user_name = user.full_name or user.username or f"Foydalanuvchi {user_id}"
    doctor_message = (
        f"❓ <b>Yangi savol bemordan:</b>\n\n"
        f"👤 {user_name}\n"
        f"ID: {user_id}\n\n"
        f"📝 <b>Savol:</b>\n{question_text}\n\n"
        f"ID savol: {question_id}"
    )
    
    # Отправляем вопрос всем врачам
    sent_count = 0
    for doctor in doctors:
        try:
            # Отправляем сообщение врачу
            if message.photo:
                await context.bot.send_photo(
                    chat_id=doctor['user_id'],
                    photo=message.photo[-1].file_id,
                    caption=doctor_message,
                    parse_mode=ParseMode.HTML
                )
            elif message.video:
                await context.bot.send_video(
                    chat_id=doctor['user_id'],
                    video=message.video.file_id,
                    caption=doctor_message,
                    parse_mode=ParseMode.HTML
                )
            elif message.document:
                await context.bot.send_document(
                    chat_id=doctor['user_id'],
                    document=message.document.file_id,
                    caption=doctor_message,
                    parse_mode=ParseMode.HTML
                )
            else:
                await context.bot.send_message(
                    chat_id=doctor['user_id'],
                    text=doctor_message,
                    parse_mode=ParseMode.HTML
                )
            sent_count += 1
        except Exception as e:
            logger.error(f"Ошибка при отправке сообщения врачу {doctor['user_id']}: {e}")
    
    # Формируем информативное сообщение
    reply_text = (
        "✅ <b>Savolingiz shifokorlarga yuborildi!</b>\n\n"
        f"📝 Savol ID: <code>{question_id}</code>\n"
        "⏱ Shifokor sizga tez orada javob beradi.\n\n"
        "💡 Savollaringiz holatini ko'rish uchun /myquestions buyrug'idan foydalaning."
    )
    
    await message.reply_text(reply_text, parse_mode=ParseMode.HTML)


async def my_questions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда для просмотра своих вопросов"""
    user_id = update.effective_user.id
    
    # Проверяем все подписки
    subscriptions = await check_all_subscriptions(user_id, context)
    if not subscriptions['all_subscribed']:
        # Формируем список неподписанных платформ
        missing_subs = []
        keyboard = []
        
        if not subscriptions['telegram']:
            missing_subs.append("❌ 📢 Telegram канал")
            keyboard.append([InlineKeyboardButton("📢 Telegram каналга обуна бўлиш", callback_data='get_invite_link')])
            keyboard.append([InlineKeyboardButton("✅ Telegram каналга обуна бўлдим", callback_data='check_telegram_sub')])
        else:
            missing_subs.append("✅ 📢 Telegram канал")
        
        if not subscriptions['youtube']:
            missing_subs.append("❌ 📺 YouTube канал")
            keyboard.append([InlineKeyboardButton("📺 YouTube каналга обуна бўлиш", url=config.YOUTUBE_URL)])
            keyboard.append([InlineKeyboardButton("✅ YouTube каналга обуна бўлдим", callback_data='check_youtube_sub')])
        else:
            missing_subs.append("✅ 📺 YouTube канал")
        
        if not subscriptions['instagram']:
            missing_subs.append("❌ 📷 Instagram")
            keyboard.append([InlineKeyboardButton("📷 Instagramга обуна бўлиш", url=config.INSTAGRAM_URL)])
            keyboard.append([InlineKeyboardButton("✅ Instagramга обуна бўлдим", callback_data='check_instagram_sub')])
        else:
            missing_subs.append("✅ 📷 Instagram")
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        missing_text = "\n".join([f"• {sub}" for sub in missing_subs])
        
        await update.message.reply_text(
            "⚠️ <b>Ботдан фойдаланиш учун куйидаги платформаларга обуна бўлишингиз керак:</b>\n\n"
            f"{missing_text}\n\n"
            "Юқоридаги тугмаларни босиб обуна бўлинг ва тасдиқланг!",
            reply_markup=reply_markup,
            parse_mode=ParseMode.HTML
        )
        return
    
    # Получаем вопросы пользователя
    questions = db.get_user_questions(user_id, limit=10)
    
    if not questions:
        await update.message.reply_text(
            "📭 Sizda hozircha savollar yo'q.\n\n"
            "Savolingizni botga yuboring, shifokor sizga javob beradi."
        )
        return
    
    # Формируем сообщение со списком вопросов
    message_text = "📋 <b>Sizning savollaringiz:</b>\n\n"
    
    for i, q in enumerate(questions, 1):
        status_emoji = "✅" if q['status'] == 'answered' else "⏳"
        status_text = "Javob berildi" if q['status'] == 'answered' else "Javob kutilmoqda"
        
        # Обрезаем длинный текст вопроса
        question_preview = q['question_text'][:50] + "..." if len(q['question_text']) > 50 else q['question_text']
        
        message_text += f"{status_emoji} <b>Savol #{q['question_id']}</b> ({status_text})\n"
        message_text += f"   {question_preview}\n\n"
    
    if len(questions) == 10:
        message_text += "\n(Oxirgi 10 ta savol ko'rsatilmoqda)"
    
    await update.message.reply_text(message_text, parse_mode=ParseMode.HTML)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда справки"""
    user_id = update.effective_user.id
    
    # Проверяем все подписки
    subscriptions = await check_all_subscriptions(user_id, context)
    if not subscriptions['all_subscribed']:
        # Формируем список неподписанных платформ
        missing_subs = []
        keyboard = []
        
        if not subscriptions['telegram']:
            missing_subs.append("❌ 📢 Telegram канал")
            keyboard.append([InlineKeyboardButton("📢 Telegram каналга обуна бўлиш", callback_data='get_invite_link')])
            keyboard.append([InlineKeyboardButton("✅ Telegram каналга обуна бўлдим", callback_data='check_telegram_sub')])
        else:
            missing_subs.append("✅ 📢 Telegram канал")
        
        if not subscriptions['youtube']:
            missing_subs.append("❌ 📺 YouTube канал")
            keyboard.append([InlineKeyboardButton("📺 YouTube каналга обуна бўлиш", url=config.YOUTUBE_URL)])
            keyboard.append([InlineKeyboardButton("✅ YouTube каналга обуна бўлдим", callback_data='check_youtube_sub')])
        else:
            missing_subs.append("✅ 📺 YouTube канал")
        
        if not subscriptions['instagram']:
            missing_subs.append("❌ 📷 Instagram")
            keyboard.append([InlineKeyboardButton("📷 Instagramга обуна бўлиш", url=config.INSTAGRAM_URL)])
            keyboard.append([InlineKeyboardButton("✅ Instagramга обуна бўлдим", callback_data='check_instagram_sub')])
        else:
            missing_subs.append("✅ 📷 Instagram")
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        missing_text = "\n".join([f"• {sub}" for sub in missing_subs])
        
        await update.message.reply_text(
            "⚠️ <b>Ботдан фойдаланиш учун куйидаги платформаларга обуна бўлишингиз керак:</b>\n\n"
            f"{missing_text}\n\n"
            "Юқоридаги тугмаларни босиб обуна бўлинг ва тасдиқланг!",
            reply_markup=reply_markup,
            parse_mode=ParseMode.HTML
        )
        return
    
    help_text = (
        "📖 <b>Botdan foydalanish bo'yicha yordam</b>\n\n"
        "👋 <b>Savol qanday beriladi:</b>\n"
        "Savolingizni botga matn, rasm, video yoki hujjat shaklida yuboring.\n\n"
        "📋 <b>Mavjud buyruqlar:</b>\n"
        "/start - Bot bilan ishlashni boshlash\n"
        "/myquestions - Sizning savollaringizni ko'rish\n"
        "/help - Bu yordam\n\n"
        "⏱ <b>Qanday ishlaydi:</b>\n"
        "1. Siz savol yuborasiz\n"
        "2. Savol shifokorlarga yuboriladi\n"
        "3. Shifokor sizning savolingizga javob beradi\n"
        "4. Siz javobni botda olasiz\n\n"
        "💡 <b>Maslahat:</b> Faqat matn emas, balki rasm, video yoki hujjatlarni ham yuborishingiz mumkin - bu muammoni batafsilroq tasvirlashga yordam beradi."
    )
    
    await update.message.reply_text(help_text, parse_mode=ParseMode.HTML)


async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /admin с авторизацией"""
    user_id = update.effective_user.id
    
    # Проверяем, авторизован ли пользователь
    if 'admin_authorized' not in context.user_data or not context.user_data['admin_authorized']:
        # Начинаем процесс авторизации - запрашиваем логин
        context.user_data['admin_waiting_login'] = True
        await update.message.reply_text(
            "🔐 <b>Admin panel</b>\n\n"
            "Kirish uchun loginni kiriting:",
            parse_mode=ParseMode.HTML,
            reply_markup=ReplyKeyboardRemove()
        )
    else:
        # Пользователь уже авторизован - показываем панель
        await show_admin_panel(update, context)


async def show_admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать админ-панель с кнопками"""
    keyboard = [
        [KeyboardButton("➕ Shifokor qo'shish"), KeyboardButton("➖ Shifokorni olib tashlash")],
        [KeyboardButton("📋 Shifokorlar ro'yxati"), KeyboardButton("🔍 Kanalda qidirish")],
        [KeyboardButton("📢 Foydalanuvchilarga xabar yuborish")],
        [KeyboardButton("🔑 Parolni o'zgartirish"), KeyboardButton("🚪 Chiqish")]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=False)
    
    sent_message = await update.message.reply_text(
        "🔐 <b>Admin panel</b>\n\n"
        "Quyidagi tugmalardan birini tanlang:",
        reply_markup=reply_markup,
        parse_mode=ParseMode.HTML
    )
    save_admin_message_id(context, sent_message.message_id)


async def admin_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик callback кнопок админ-панели"""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    
    # Проверяем авторизацию
    if 'admin_authorized' not in context.user_data or not context.user_data['admin_authorized']:
        await query.edit_message_text("❌ Siz avtorizatsiyadan o'tmagansiz. /admin buyrug'ini bosing.")
        return
    
    callback_data = query.data
    
    if callback_data == 'admin_add_doctor':
        await query.edit_message_text(
            "➕ <b>Shifokor qo'shish</b>\n\n"
            "Shifokor ID sini yuboring:\n\n"
            "Format: <code>ID:123456789</code>\n\n"
            "Yoki shunchaki ID raqamini yuboring.",
            parse_mode=ParseMode.HTML
        )
        context.user_data['admin_waiting_for'] = 'add_doctor'
    
    elif callback_data == 'admin_remove_doctor':
        await query.edit_message_text(
            "➖ <b>Shifokorni olib tashlash</b>\n\n"
            "Olib tashlash uchun shifokor ID sini yuboring:\n\n"
            "Format: <code>ID:123456789</code>\n\n"
            "Yoki shunchaki ID raqamini yuboring.",
            parse_mode=ParseMode.HTML
        )
        context.user_data['admin_waiting_for'] = 'remove_doctor'
    
    elif callback_data == 'admin_list_doctors':
        doctors = db.list_all_doctors()
        if not doctors:
            await query.edit_message_text("📭 Hozircha shifokorlar yo'q.")
            return
        
        message_text = f"👨‍⚕️ <b>Barcha shifokorlar ({len(doctors)}):</b>\n\n"
        for i, doctor in enumerate(doctors, 1):
            username_text = f"@{doctor['username']}" if doctor['username'] else "Username yo'q"
            full_name_text = doctor['full_name'] or "Ism yo'q"
            message_text += (
                f"{i}. <b>{full_name_text}</b>\n"
                f"   ID: <code>{doctor['user_id']}</code>\n"
                f"   Username: {username_text}\n\n"
            )
        
        keyboard = [[InlineKeyboardButton("🔙 Orqaga", callback_data='admin_back')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(message_text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)
    
    elif callback_data == 'admin_change_password':
        await query.edit_message_text(
            "🔑 <b>Parolni o'zgartirish</b>\n\n"
            "Yangi parolni yuboring:\n\n"
            "Format: <code>parol:yangi_parol</code>\n\n"
            "Yoki shunchaki yangi parolni yuboring.",
            parse_mode=ParseMode.HTML
        )
        context.user_data['admin_waiting_for'] = 'change_password'
    
    elif callback_data == 'admin_logout':
        context.user_data['admin_authorized'] = False
        context.user_data.pop('admin_waiting_for', None)
        await query.edit_message_text("✅ Siz admin paneldan chiqdingiz.")
    
    elif callback_data == 'admin_back':
        await show_admin_panel_callback(query, context)


async def show_admin_panel_callback(query, context):
    """Показать админ-панель через callback"""
    keyboard = [
        [InlineKeyboardButton("➕ Shifokor qo'shish", callback_data='admin_add_doctor')],
        [InlineKeyboardButton("➖ Shifokorni olib tashlash", callback_data='admin_remove_doctor')],
        [InlineKeyboardButton("📋 Shifokorlar ro'yxati", callback_data='admin_list_doctors')],
        [InlineKeyboardButton("🔑 Parolni o'zgartirish", callback_data='admin_change_password')],
        [InlineKeyboardButton("🚪 Chiqish", callback_data='admin_logout')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        "🔐 <b>Admin panel</b>\n\n"
        "Quyidagi tugmalardan birini tanlang:",
        reply_markup=reply_markup,
        parse_mode=ParseMode.HTML
    )


async def set_doctor_role(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Скрытая команда для установки роли врача (устаревшая, используйте /admin)"""
    await update.message.reply_text("⚠️ Bu buyruq eskirgan. Iltimos, /admin buyrug'idan foydalaning.")


async def handle_doctor_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка ответов врачей на вопросы (скрытый функционал)"""
    user = update.effective_user
    user_id = user.id
    message = update.message
    
    # Проверяем, является ли пользователь врачом
    user_info = db.get_user(user_id)
    if not user_info or user_info['role'] != 'doctor':
        return
    
    # Проверяем, является ли это ответом на сообщение
    if not message.reply_to_message:
        return
    
    replied_message = message.reply_to_message
    replied_text = replied_message.text or replied_message.caption or ""
    
    # Извлекаем ID вопроса из текста сообщения
    question_id = None
    if "ID savol:" in replied_text or "ID вопроса:" in replied_text:
        try:
            # Пробуем найти ID вопроса
            text_to_search = "ID savol:" if "ID savol:" in replied_text else "ID вопроса:"
            question_id = int(replied_text.split(text_to_search)[-1].strip().split()[0])
        except:
            pass
    
    if not question_id:
        await message.reply_text("Savolni aniqlab bo'lmadi. Savol bilan xabarga javob bering.")
        return
    
    # Получаем информацию о вопросе
    question = db.get_question(question_id)
    if not question:
        await message.reply_text("Savol topilmadi.")
        return
    
    # Сохраняем ответ в БД
    answer_text = message.text or message.caption or "Media-xabar"
    db.add_answer(question_id, user_id, message.message_id, answer_text)
    
    # Отправляем ответ пациенту
    doctor_name = user.full_name or user.username or "Shifokor"
    question_preview = question['question_text'][:100] + "..." if len(question['question_text']) > 100 else question['question_text']
    
    patient_message = (
        f"👨‍⚕️ <b>Javob shifokordan {doctor_name}</b>\n\n"
        f"📝 <b>Sizning savolingiz:</b>\n{question_preview}\n\n"
        f"💬 <b>Javob:</b>\n{answer_text}"
    )
    
    try:
        if message.photo:
            await context.bot.send_photo(
                chat_id=question['user_id'],
                photo=message.photo[-1].file_id,
                caption=patient_message,
                parse_mode=ParseMode.HTML
            )
        elif message.video:
            await context.bot.send_video(
                chat_id=question['user_id'],
                video=message.video.file_id,
                caption=patient_message,
                parse_mode=ParseMode.HTML
            )
        elif message.document:
            await context.bot.send_document(
                chat_id=question['user_id'],
                document=message.document.file_id,
                caption=patient_message,
                parse_mode=ParseMode.HTML
            )
        else:
            await context.bot.send_message(
                chat_id=question['user_id'],
                text=patient_message,
                parse_mode=ParseMode.HTML
            )
        
        await message.reply_text("✅ Javob bemorga yuborildi.")
    except Exception as e:
        logger.error(f"Ошибка при отправке ответа пациенту: {e}")
        await message.reply_text("❌ Javob yuborishda xatolik yuz berdi. Keyinroq urinib ko'ring.")


async def post_init(application: Application):
    """Инициализация после создания приложения - настройка меню команд"""
    bot = application.bot
    
    # Устанавливаем команды меню (кнопка Start)
    commands = [
        BotCommand("start", "Botni ishga tushirish"),
        BotCommand("myquestions", "Mening savollarim"),
        BotCommand("help", "Yordam")
    ]
    
    await bot.set_my_commands(commands)
    
    # Устанавливаем описание бота на узбекском языке
    bot_description = (
        "👋🏻 Хуш келибсиз!\n"
        "Мен Шерзод Тойиров, сиз ёзган саволларга шахсан ўзим жавоб бераман.\n\n"
        "Ундан олдин каналга аъзо бўлишингиз ШАРТ!\n\n"
        "Муаммо ва савалларингизни матн, видео, расм, хужжат, МРТ шаклда юбориб батафсил ёзинг 👇🏻\n\n"
        "Жавоб бироз кечикиши мумкин, лекин барча хабарларга албатта жавоб бераман😊"
    )
    
    try:
        await bot.set_my_description(bot_description)
        await bot.set_my_short_description("Шерзод Тойиров - тиббий консультация")
    except Exception as e:
        logger.warning(f"Не удалось установить описание бота: {e}")


def main():
    """Главная функция запуска бота"""
    if not config.BOT_TOKEN:
        logger.error("BOT_TOKEN не установлен! Установите его в файле .env")
        return
    
    # Создаем приложение
    application = Application.builder().token(config.BOT_TOKEN).post_init(post_init).build()
    
    # Регистрируем обработчики
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("myquestions", my_questions))
    application.add_handler(CommandHandler("admin", admin_command))  # Команда для управления врачами с авторизацией
    application.add_handler(CommandHandler("setdoctor", set_doctor_role))  # Устаревшая команда
    application.add_handler(CallbackQueryHandler(get_invite_link_callback, pattern='get_invite_link'))
    application.add_handler(CallbackQueryHandler(check_telegram_subscription_callback, pattern='check_telegram_sub'))
    application.add_handler(CallbackQueryHandler(check_youtube_subscription_callback, pattern='check_youtube_sub'))
    application.add_handler(CallbackQueryHandler(check_instagram_subscription_callback, pattern='check_instagram_sub'))
    
    # Обработчик ответов врачей (должен быть до обычных сообщений)
    application.add_handler(MessageHandler(filters.REPLY & (filters.TEXT | filters.PHOTO | filters.VIDEO | filters.Document.ALL), handle_doctor_reply))
    
    # Обработчики сообщений от пользователей
    application.add_handler(MessageHandler(filters.CONTACT, handle_user_message))  # Обработка контактов (для админ-панели)
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_user_message))
    application.add_handler(MessageHandler(filters.PHOTO | filters.VIDEO | filters.Document.ALL, handle_user_message))
    
    # Добавляем обработчик ошибок
    async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Обработчик ошибок"""
        logger.error(f"Exception while handling an update: {context.error}", exc_info=context.error)
        
        # Обработка конфликта (несколько экземпляров бота)
        if isinstance(context.error, Conflict):
            logger.error(
                "Конфликт: обнаружено несколько экземпляров бота. "
                "Убедитесь, что запущен только один экземпляр бота."
            )
            # Не прерываем работу, просто логируем
        elif isinstance(context.error, TelegramError):
            logger.error(f"Telegram API ошибка: {context.error}")
        else:
            logger.error(f"Неожиданная ошибка: {context.error}", exc_info=context.error)
    
    application.add_error_handler(error_handler)
    
    # Запускаем бота
    logger.info("Бот запущен")
    try:
        application.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)
    except KeyboardInterrupt:
        logger.info("Бот остановлен пользователем")
    except Exception as e:
        logger.error(f"Критическая ошибка при запуске бота: {e}", exc_info=e)


if __name__ == '__main__':
    main()
