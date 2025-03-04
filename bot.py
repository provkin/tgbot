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
ADMIN_ID = int(os.getenv("ADMIN_ID"))

# Инициализация Яндекс.Диска
y = yadisk.YaDisk(token=YANDEX_TOKEN)

# Состояния ConversationHandler
(
    NAME, SURNAME, PHONE, SOURCE, PHOTO, COURSE,
    PAYMENT_AMOUNT, PAYMENT_PROOF,
    EVENT_NAME, EVENT_DATE, EVENT_TIME, EVENT_DETAILS
) = range(12)

# Константы
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

async def get_photo(update: Update, context: CallbackContext):
    try:
        photo = await update.message.photo[-1].get_file()
        local_path = f"temp/{update.message.message_id}.jpg"
        os.makedirs("temp", exist_ok=True)
        await photo.download_to_drive(local_path)
        
        # Формируем уникальное имя файла
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        file_name = f"{context.user_data['name']}_{context.user_data['surname']}_{timestamp}.jpg"
        
        # Сохраняем в папку Платежи
        y.upload(local_path, f"/Платежи/{file_name}")
        os.remove(local_path)
        
        # Формируем сообщение админу
        admin_msg = (
            f"💸 Новый платеж:\n"
            f"Студент: {context.user_data['name']} {context.user_data['surname']}\n"
            f"Курс: {context.user_data['course']}\n"
            f"Текущий баланс: {context.user_data['balance']} руб\n"
            f"Скриншот: {y.get_download_link(f'/Платежи/{file_name}')}"
        )
        
        await notify_admin(context, admin_msg)
        await update.message.reply_text("✅ Платеж отправлен на проверку!", reply_markup=PROFILE_KEYBOARD)
        return ConversationHandler.END
        
    except Exception as e:
        logger.error(f"Ошибка обработки платежа: {str(e)}")
        await update.message.reply_text("❌ Ошибка обработки платежа")
        return ConversationHandler.END

async def handle_admin_reply(update: Update, context: CallbackContext):
    """Обработка ответов администратора на платежи"""
    try:
        if update.message.reply_to_message and update.message.from_user.id == ADMIN_ID:
            # Парсим сумму из сообщения
            amount = int(update.message.text)
            
            # Получаем user_id из оригинального сообщения
            original_text = update.message.reply_to_message.text
            user_id = int(original_text.split("ID: ")[1].split("\n")[0])
            
            # Обновляем баланс в таблице
            temp_file = "temp_students.xlsx"
            y.download("/Таблицы/Студенты.xlsx", temp_file)
            df = pd.read_excel(temp_file)
            
            df.loc[df["user_id"] == user_id, "Баланс"] += amount
            df.to_excel(temp_file, index=False)
            y.upload(temp_file, "/Таблицы/Студенты.xlsx", overwrite=True)
            os.remove(temp_file)
            
            # Уведомляем студента
            new_balance = df.loc[df["user_id"] == user_id, "Баланс"].values[0]
            await context.bot.send_message(
                chat_id=user_id,
                text=f"✅ Ваш баланс пополнен на {amount} руб!\nНовый баланс: {new_balance} руб",
                reply_markup=PROFILE_KEYBOARD
            )
            
            await update.message.reply_text("💰 Баланс успешно обновлен!")
    except Exception as e:
        logger.error(f"Ошибка обработки платежа админом: {str(e)}")

async def show_events(update: Update, context: CallbackContext):
    """Показывает список событий"""
    try:
        temp_file = "temp_events.xlsx"
        y.download("/Таблицы/События.xlsx", temp_file)
        df = pd.read_excel(temp_file)
        
        if df.empty:
            await update.callback_query.message.reply_text("На ближайшее время событий нет.")
            return
        
        events_list = []
        for _, row in df.iterrows():
            events_list.append(
                f"📅 {row['Дата']} {row['Время']}\n"
                f"🏷 {row['Название']}\n"
                f"📝 {row['Описание']}\n"
            )
            
        await update.callback_query.message.reply_text("\n\n".join(events_list))
        
    except Exception as e:
        logger.error(f"Ошибка показа событий: {str(e)}")
        await update.callback_query.message.reply_text("❌ Ошибка загрузки событий")

def main():
    application = ApplicationBuilder().token(TOKEN).build()

    # Регистрация студента
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

    # Обработчики кнопок
    application.add_handler(CallbackQueryHandler(show_events, pattern="^events$"))
    application.add_handler(MessageHandler(filters.TEXT & filters.user(ADMIN_ID), handle_admin_reply))

    application.add_handler(conv_handler)
    application.run_polling()

if __name__ == "__main__":
    # Создаем необходимые папки при первом запуске
    for folder in ["Фото студентов", "Платежи", "Таблицы"]:
        if not y.exists(folder):
            y.mkdir(folder)
    
    main()
