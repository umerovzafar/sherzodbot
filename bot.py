import logging
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove, Contact
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters
)
from telegram.constants import ParseMode
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


async def check_all_subscriptions(user_id, context: ContextTypes.DEFAULT_TYPE):
    """Проверка подписок на все платформы (Telegram, Instagram, YouTube)"""
    # Проверяем подписку на Telegram канал
    telegram_subscribed = await check_subscription(user_id, context)
    
    # Проверяем подписки на социальные сети из базы данных
    social_subs = db.check_all_subscriptions(user_id)
    instagram_subscribed = social_subs.get('instagram', False)
    youtube_subscribed = social_subs.get('youtube', False)
    
    return {
        'telegram': telegram_subscribed,
        'instagram': instagram_subscribed,
        'youtube': youtube_subscribed,
        'all_subscribed': telegram_subscribed and instagram_subscribed and youtube_subscribed
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
        
        # Telegram канал
        if not subscriptions['telegram']:
            keyboard.append([InlineKeyboardButton("📢 Telegram каналга обуна бўлиш", callback_data='get_invite_link')])
            keyboard.append([InlineKeyboardButton("✅ Telegram каналга обуна бўлдим", callback_data='check_telegram_sub')])
        else:
            keyboard.append([InlineKeyboardButton("✅ Telegram каналга обуна бўлганман", callback_data='check_telegram_sub')])
        
        # Instagram
        if not subscriptions['instagram']:
            keyboard.append([InlineKeyboardButton("📷 Instagram", url=config.INSTAGRAM_URL)])
            keyboard.append([InlineKeyboardButton("✅ Instagramга обуна бўлдим", callback_data='confirm_instagram')])
        else:
            keyboard.append([InlineKeyboardButton("✅ Instagramга обуна бўлганман", callback_data='confirm_instagram')])
        
        # YouTube
        if not subscriptions['youtube']:
            keyboard.append([InlineKeyboardButton("📺 YouTube", url=config.YOUTUBE_URL)])
            keyboard.append([InlineKeyboardButton("✅ YouTubeга обуна бўлдим", callback_data='confirm_youtube')])
        else:
            keyboard.append([InlineKeyboardButton("✅ YouTubeга обуна бўлганман", callback_data='confirm_youtube')])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        # Формируем список платформ с отметками о подписке
        platforms_text = []
        if subscriptions['telegram']:
            platforms_text.append("✅ 📢 Telegram канал")
        else:
            platforms_text.append("❌ 📢 Telegram канал")
        
        if subscriptions['instagram']:
            platforms_text.append("✅ 📷 Instagram")
        else:
            platforms_text.append("❌ 📷 Instagram")
        
        if subscriptions['youtube']:
            platforms_text.append("✅ 📺 YouTube")
        else:
            platforms_text.append("❌ 📺 YouTube")
        
        platforms_list = "\n".join([f"• {platform}" for platform in platforms_text])
        
        welcome_text = (
            "👋🏻 <b>Хуш келибсиз!</b>\n\n"
            "Мен Шерзод Тойиров, сиз ёзган саволларга шахсан ўзим жавоб бераман.\n\n"
            "⚠️ <b>Ундан олдин куйидаги платформаларга аъзо бўлишингиз ШАРТ:</b>\n\n"
            f"{platforms_list}\n\n"
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
    
    # Обычный пользователь - показываем приветствие
    welcome_text = (
        "👋🏻 <b>Хуш келибсиз!</b>\n\n"
        "Мен Шерзод Тойиров, сиз ёзган саволларга шахсан ўзим жавоб бераман.\n\n"
        "📝 <b>Муаммо ва савалларингизни</b> матн, видео, расм, хужжат, МРТ шаклда юбориб батафсил ёзинг 👇🏻\n\n"
        "⏱️ Жавоб бироз кечикиши мумкин, лекин барча хабарларга албатта жавоб бераман😊\n\n"
        "📋 <b>Mavjud buyruqlar:</b>\n"
        "/myquestions - Mening savollarim\n"
        "/help - Yordam"
    )
    
    await update.message.reply_text(welcome_text, parse_mode=ParseMode.HTML)


async def update_subscription_status(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int):
    """Обновить статус подписок и показать соответствующее сообщение"""
    subscriptions = await check_all_subscriptions(user_id, context)
    
    if subscriptions['all_subscribed']:
        # Все подписки подтверждены
        welcome_text = (
            "✅ <b>Барча платформаларга обуна бўлдингиз!</b>\n\n"
            "👋🏻 <b>Хуш келибсиз!</b>\n\n"
            "Мен Шерзод Тойиров, сиз ёзган саволларга шахсан ўзим жавоб бераман.\n\n"
            "📝 <b>Муаммо ва савалларингизни</b> матн, видео, расм, хужжат, МРТ шаклда юбориб батафсил ёзинг 👇🏻\n\n"
            "⏱️ Жавоб бироз кечикиши мумкин, лекин барча хабарларга албатта жавоб бераман😊\n\n"
            "📋 <b>Mavjud buyruqlar:</b>\n"
            "/myquestions - Mening savollarim\n"
            "/help - Yordam"
        )
        
        if update.callback_query:
            try:
                await update.callback_query.edit_message_text(welcome_text, reply_markup=None, parse_mode=ParseMode.HTML)
            except Exception as e:
                logger.warning(f"Не удалось отредактировать сообщение: {e}")
                await update.callback_query.message.reply_text(welcome_text, parse_mode=ParseMode.HTML)
        else:
            await update.message.reply_text(welcome_text, parse_mode=ParseMode.HTML)
    else:
        # Есть неподтвержденные подписки
        missing_subs = []
        keyboard = []
        
        if not subscriptions['telegram']:
            missing_subs.append("📢 Telegram канал")
            keyboard.append([InlineKeyboardButton("📢 Telegram каналга обуна бўлиш", callback_data='get_invite_link')])
            keyboard.append([InlineKeyboardButton("✅ Telegram каналга обуна бўлдим", callback_data='check_telegram_sub')])
        
        if not subscriptions['instagram']:
            missing_subs.append("📷 Instagram")
            keyboard.append([InlineKeyboardButton("📷 Instagram", url=config.INSTAGRAM_URL)])
            keyboard.append([InlineKeyboardButton("✅ Instagramга обуна бўлдим", callback_data='confirm_instagram')])
        
        if not subscriptions['youtube']:
            missing_subs.append("📺 YouTube")
            keyboard.append([InlineKeyboardButton("📺 YouTube", url=config.YOUTUBE_URL)])
            keyboard.append([InlineKeyboardButton("✅ YouTubeга обуна бўлдим", callback_data='confirm_youtube')])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        missing_text = "\n".join([f"• {sub}" for sub in missing_subs])
        
        status_text = (
            "⚠️ <b>Куйидаги платформаларга обуна бўлишингиз керак:</b>\n\n"
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


async def confirm_instagram_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка подтверждения подписки на Instagram"""
    query = update.callback_query
    user_id = query.from_user.id
    
    # Сохраняем подтверждение подписки на Instagram
    db.set_social_subscription(user_id, 'instagram', True)
    await query.answer("Instagramга обуна тасдиқланди! ✅", show_alert=False)
    
    # Обновляем статус подписок
    await update_subscription_status(update, context, user_id)


async def confirm_youtube_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка подтверждения подписки на YouTube"""
    query = update.callback_query
    user_id = query.from_user.id
    
    # Сохраняем подтверждение подписки на YouTube
    db.set_social_subscription(user_id, 'youtube', True)
    await query.answer("YouTubeга обуна тасдиқланди! ✅", show_alert=False)
    
    # Обновляем статус подписок
    await update_subscription_status(update, context, user_id)


async def check_telegram_subscription_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка нажатия кнопки проверки подписки на Telegram канал"""
    query = update.callback_query
    user_id = query.from_user.id
    
    # Проверяем подписку
    is_subscribed = await check_subscription(user_id, context)
    
    if is_subscribed:
        await query.answer("Telegram каналга обуна тасдиқланди! ✅", show_alert=False)
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
                [InlineKeyboardButton("✅ Men obuna bo'ldim", callback_data='check_subscription')]
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
                [InlineKeyboardButton("✅ Men obuna bo'ldim", callback_data='check_subscription')]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            try:
                await query.edit_message_text(error_text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)
            except:
                await query.message.reply_text(error_text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)


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
                        if config.CHANNEL_ID:
                            try:
                                member = await context.bot.get_chat_member(config.CHANNEL_ID, user_id_to_add)
                                in_channel = True
                                channel_status = member.status
                            except:
                                # Пользователь не в канале
                                pass
                        
                        # Сообщаем о результате поиска
                        if in_channel:
                            await message.reply_text(
                                f"✅ Foydalanuvchi topildi va kanalda mavjud!\n\n"
                                f"👤 Username: <code>@{username_to_search}</code>\n"
                                f"📝 Ism: {full_name or 'Noma\'lum'}\n"
                                f"🆔 ID: <code>{user_id_to_add}</code>\n"
                                f"📢 Kanalda: Ha (Status: {channel_status})",
                                parse_mode=ParseMode.HTML
                            )
                        else:
                            await message.reply_text(
                                f"✅ Foydalanuvchi topildi!\n\n"
                                f"👤 Username: <code>@{username_to_search}</code>\n"
                                f"📝 Ism: {full_name or 'Noma\'lum'}\n"
                                f"🆔 ID: <code>{user_id_to_add}</code>\n"
                                f"⚠️ Kanalda: Topilmadi (lekin qo'shish mumkin)",
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
            result_text = (
                f"✅ Shifokor qo'shildi!\n\n"
                f"👤 ID: <code>{user_id_to_add}</code>\n"
                f"📝 Ism: {full_name or 'Noma\'lum'}\n"
                f"🔗 Username: @{username if username else 'yo\'q'}"
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
            missing_subs.append("📢 Telegram канал")
            keyboard.append([InlineKeyboardButton("📢 Telegram каналга обуна бўлиш", callback_data='get_invite_link')])
            keyboard.append([InlineKeyboardButton("✅ Telegram каналга обуна бўлдим", callback_data='check_telegram_sub')])
        
        if not subscriptions['instagram']:
            missing_subs.append("📷 Instagram")
            keyboard.append([InlineKeyboardButton("📷 Instagram", url=config.INSTAGRAM_URL)])
            keyboard.append([InlineKeyboardButton("✅ Instagramга обуна бўлдим", callback_data='confirm_instagram')])
        
        if not subscriptions['youtube']:
            missing_subs.append("📺 YouTube")
            keyboard.append([InlineKeyboardButton("📺 YouTube", url=config.YOUTUBE_URL)])
            keyboard.append([InlineKeyboardButton("✅ YouTubeга обуна бўлдим", callback_data='confirm_youtube')])
        
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
            missing_subs.append("📢 Telegram канал")
            keyboard.append([InlineKeyboardButton("📢 Telegram каналга обуна бўлиш", callback_data='get_invite_link')])
            keyboard.append([InlineKeyboardButton("✅ Telegram каналга обуна бўлдим", callback_data='check_telegram_sub')])
        
        if not subscriptions['instagram']:
            missing_subs.append("📷 Instagram")
            keyboard.append([InlineKeyboardButton("📷 Instagram", url=config.INSTAGRAM_URL)])
            keyboard.append([InlineKeyboardButton("✅ Instagramга обуна бўлдим", callback_data='confirm_instagram')])
        
        if not subscriptions['youtube']:
            missing_subs.append("📺 YouTube")
            keyboard.append([InlineKeyboardButton("📺 YouTube", url=config.YOUTUBE_URL)])
            keyboard.append([InlineKeyboardButton("✅ YouTubeга обуна бўлдим", callback_data='confirm_youtube')])
        
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
            missing_subs.append("📢 Telegram канал")
            keyboard.append([InlineKeyboardButton("📢 Telegram каналга обуна бўлиш", callback_data='get_invite_link')])
            keyboard.append([InlineKeyboardButton("✅ Telegram каналга обуна бўлдим", callback_data='check_telegram_sub')])
        
        if not subscriptions['instagram']:
            missing_subs.append("📷 Instagram")
            keyboard.append([InlineKeyboardButton("📷 Instagram", url=config.INSTAGRAM_URL)])
            keyboard.append([InlineKeyboardButton("✅ Instagramга обуна бўлдим", callback_data='confirm_instagram')])
        
        if not subscriptions['youtube']:
            missing_subs.append("📺 YouTube")
            keyboard.append([InlineKeyboardButton("📺 YouTube", url=config.YOUTUBE_URL)])
            keyboard.append([InlineKeyboardButton("✅ YouTubeга обуна бўлдим", callback_data='confirm_youtube')])
        
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
    application.add_handler(CallbackQueryHandler(confirm_instagram_callback, pattern='confirm_instagram'))
    application.add_handler(CallbackQueryHandler(confirm_youtube_callback, pattern='confirm_youtube'))
    
    # Обработчик ответов врачей (должен быть до обычных сообщений)
    application.add_handler(MessageHandler(filters.REPLY & (filters.TEXT | filters.PHOTO | filters.VIDEO | filters.Document.ALL), handle_doctor_reply))
    
    # Обработчики сообщений от пользователей
    application.add_handler(MessageHandler(filters.CONTACT, handle_user_message))  # Обработка контактов (для админ-панели)
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_user_message))
    application.add_handler(MessageHandler(filters.PHOTO | filters.VIDEO | filters.Document.ALL, handle_user_message))
    
    # Запускаем бота
    logger.info("Бот запущен")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == '__main__':
    main()
