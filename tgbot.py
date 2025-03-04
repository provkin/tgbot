import os
import logging
import pandas as pd
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    filters,
    ConversationHandler,
    CallbackContext,
    CallbackQueryHandler,
)
import yadisk
from dotenv import load_dotenv

# Загрузка переменных окружения
load_dotenv()
TOKEN = os.getenv("TELEGRAM_TOKEN")
YANDEX_TOKEN = os.getenv("YANDEX_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", 0)) 

# Инициализация Яндекс.Диска
y = yadisk.YaDisk(token=YANDEX_TOKEN)

# Состояния ConversationHandler
(
    NAME, SURNAME, PHONE, SOURCE, PHOTO, COURSE,
    PAYMENT_AMOUNT, PAYMENT_PROOF,
    EVENT_NAME, EVENT_DATE, EVENT_TIME, EVENT_DETAILS
) = range(12)

# Стоимости курсов
COURSES = {
    "intensive": 34000,
    "basic": 72000,
    "advanced": 80000,
    "master": 90000,
}

# Логирование
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Клавиатуры
PROFILE_KEYBOARD = InlineKeyboardMarkup([
    [InlineKeyboardButton("💳 Оплата", callback_data="payment"),
     InlineKeyboardButton("📅 События", callback_data="events")],
    [InlineKeyboardButton("👩🏫 Педагоги", callback_data="teachers"),
     InlineKeyboardButton("🎓 Перейти на курс", callback_data="change_course")]
])

ADMIN_KEYBOARD = InlineKeyboardMarkup([
    [InlineKeyboardButton("📝 Создать событие", callback_data="create_event"),
     InlineKeyboardButton("📋 Список событий", callback_data="list_events")]
])

def save_to_table(data, table_path):
    """Сохраняет данные в таблицу на Яндекс.Диске"""
    temp_file = "temp.xlsx"
    try:
        y.download(table_path, temp_file)
        df = pd.read_excel(temp_file)
    except:
        df = pd.DataFrame()

    df = pd.concat([df, pd.DataFrame([data])], ignore_index=True)
    df.to_excel(temp_file, index=False)
    y.upload(temp_file, table_path, overwrite=True)
    os.remove(temp_file)

async def notify_admin(context, message, photo_url=None):
    """Отправляет уведомление администратору"""
    try:
        if photo_url:
            await context.bot.send_photo(
                chat_id=ADMIN_ID,
                photo=photo_url,
                caption=message
            )
        else:
            await context.bot.send_message(
                chat_id=ADMIN_ID,
                text=message
            )
    except Exception as e:
        logger.error(f"Ошибка уведомления админа: {str(e)}")

# Основные обработчики
async def start(update: Update, context: CallbackContext):
    user = update.message.from_user
    if user.id == ADMIN_ID:
        await update.message.reply_text("👑 Панель администратора", reply_markup=ADMIN_KEYBOARD)
        return ConversationHandler.END
    else:
        context.user_data.clear()
        await update.message.reply_text("Добро пожаловать! Давайте зарегистрируем вас.\nВведите ваше имя:")
        return NAME

async def get_name(update: Update, context: CallbackContext) -> int:
    """Обработка имени"""
    context.user_data["name"] = update.message.text
    await update.message.reply_text("Введите вашу фамилию:")
    return SURNAME

async def get_surname(update: Update, context: CallbackContext) -> int:
    """Обработка фамилии"""
    context.user_data["surname"] = update.message.text
    await update.message.reply_text("Введите ваш номер телефона:")
    return PHONE

async def get_phone(update: Update, context: CallbackContext) -> int:
    """Обработка телефона"""
    context.user_data["phone"] = update.message.text
    await update.message.reply_text("Откуда вы узнали о школе?")
    return SOURCE

async def get_source(update: Update, context: CallbackContext) -> int:
    """Обработка источника информации"""
    context.user_data["source"] = update.message.text
    await update.message.reply_text("Загрузите ваше фото:")
    return PHOTO

async def get_photo(update: Update, context: CallbackContext) -> int:
    """Обработка фото"""
    try:
        photo = await update.message.photo[-1].get_file()
        local_path = f"temp/{update.message.message_id}.jpg"
        os.makedirs("temp", exist_ok=True)
        await photo.download_to_drive(local_path)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        file_name = f"{context.user_data['name']}_{context.user_data['surname']}_{timestamp}.jpg"
        y.upload(local_path, f"/Фото студентов/{file_name}")
        os.remove(local_path)
        
        context.user_data["photo_url"] = y.get_download_link(f"/Фото студентов/{file_name}")
        
        keyboard = [[InlineKeyboardButton(course, callback_data=course)] for course in COURSES]
        await update.message.reply_text(
            "Выберите курс:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return COURSE
    except Exception as e:
        logger.error(f"Ошибка загрузки фото: {str(e)}")
        await update.message.reply_text("❌ Ошибка загрузки фото")
        return PHOTO

async def get_course(update: Update, context: CallbackContext) -> int:
    """Обработка выбора курса"""
    query = update.callback_query
    await query.answer()
    course = query.data
    context.user_data.update({
        "course": course,
        "balance": -COURSES[course],
        "user_id": query.from_user.id
    })

    student_data = {
        "Имя": context.user_data["name"],
        "Фамилия": context.user_data["surname"],
        "Телефон": context.user_data["phone"],
        "Курс": course,
        "Баланс": -COURSES[course],
        "user_id": query.from_user.id,
        "Ссылка на фото": context.user_data["photo_url"]
    }
    
    save_to_table(student_data, "/Таблицы/Студенты.xlsx")
    
    await query.message.reply_text(
        "✅ Регистрация завершена!",
        reply_markup=PROFILE_KEYBOARD
    )
    
    admin_msg = (
        f"🎓 Новый студент:\n"
        f"Имя: {student_data['Имя']}\n"
        f"Фамилия: {student_data['Фамилия']}\n"
        f"Телефон: {student_data['Телефон']}\n"
        f"Курс: {course}\n"
        f"Баланс: {student_data['Баланс']} руб"
    )
    await notify_admin(context, admin_msg, student_data["Ссылка на фото"])
    
    return ConversationHandler.END

def main() -> None:
    application = ApplicationBuilder().token(TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_name)],
            SURNAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_surname)],
            PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_phone)],
            SOURCE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_source)],
            PHOTO: [MessageHandler(filters.PHOTO, get_photo)],
            COURSE: [CallbackQueryHandler(get_course)],
        },
        fallbacks=[]
    )

    application.add_handler(conv_handler)
    application.run_polling()

if __name__ == "__main__":
    # Создание папок на Яндекс.Диске
    for folder in ["Фото студентов", "Платежи", "Таблицы"]:
        if not y.exists(folder):
            y.mkdir(folder)
    
    main()
