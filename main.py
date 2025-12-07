import os
import json
import secrets
from datetime import datetime

from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

import gspread
from google.oauth2.service_account import Credentials

# ---------- НАСТРОЙКИ ЧЕРЕЗ ПЕРЕМЕННЫЕ ОКРУЖЕНИЯ ----------

BOT_TOKEN = os.getenv("BOT_TOKEN")          # токен бота от @BotFather
CHANNEL_ID = os.getenv("CHANNEL_ID")        # например "@amebelini"
SHEET_ID = os.getenv("SHEET_ID")            # ID таблицы из URL
SERVICE_ACCOUNT_JSON = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")  # JSON ключ как строка


# ---------- ИНИЦИАЛИЗАЦИЯ GOOGLE SHEETS ----------

def get_sheet():
    if not SERVICE_ACCOUNT_JSON:
        raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_JSON is not set")

    info = json.loads(SERVICE_ACCOUNT_JSON)
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    creds = Credentials.from_service_account_info(info, scopes=scopes)
    client = gspread.authorize(creds)

    sh = client.open_by_key(SHEET_ID)
    # возьмём первый лист
    return sh.sheet1


def get_user_exists(sheet, user_id: int) -> bool:
    """
    Проверка, есть ли user_id уже в таблице.
    Предполагаем, что user_id лежит в колонке A.
    """
    # Считываем всю колонку A, кроме заголовка
    col = sheet.col_values(1)[1:]  # пропускаем шапку
    return str(user_id) in col


def append_user(sheet, user_id: int, username: str | None, code: str):
    """
    Добавляем строку в таблицу:
    user_id | username | code | created_at
    """
    created_at = datetime.utcnow().isoformat()
    sheet.append_row([str(user_id), username or "", code, created_at])


def generate_code() -> str:
    """Генерация промокода вида MEBEL-AB12CD."""
    suffix = secrets.token_hex(3).upper()
    return f"MEBEL-{suffix}"


# ---------- ХЭНДЛЕРЫ ТЕЛЕГРАМ-БОТА ----------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "Здравствуйте! 🎉\n\n"
        "Здесь вы можете получить персональный промокод на скидку.\n\n"
        "1️⃣ Подпишитесь на наш канал:\n"
        f"https://t.me/{CHANNEL_ID.lstrip('@')}\n\n"
        "2️⃣ После подписки нажмите /check, и бот проверит подписку и выдаст код."
    )
    await update.message.reply_text(text)


async def check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id

    # 1. Проверяем подписку на канал
    try:
        member = await context.bot.get_chat_member(CHANNEL_ID, user_id)
        status = member.status  # "member", "administrator", "creator", "left", "kicked"
    except Exception as e:
        print("get_chat_member error:", e)
        status = "left"

    if status not in ["member", "administrator", "creator"]:
        await update.message.reply_text(
            "Вы ещё не подписаны на канал.\n"
            "Подпишитесь, пожалуйста, и потом снова нажмите /check 😊"
        )
        return

    # 2. Работа с Google Sheets
    sheet = get_sheet()

    # проверяем, выдавался ли код ранее
    if get_user_exists(sheet, user_id):
        await update.message.reply_text(
            "Вы уже подписаны на канал. Следите за акциями и скидками! 😉"
        )
        return

    # 3. Новый пользователь → генерируем код, записываем в таблицу, отправляем
    code = generate_code()
    append_user(sheet, user_id, user.username, code)

    await update.message.reply_text(
        "Отлично! Вы подписаны на канал 🎉\n\n"
        f"Ваш персональный промокод на скидку:\n\n"
        f"👉 {code} 👈\n\n"
        "Сообщите его менеджеру при оформлении заказа."
    )


async def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN is not set")

    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("check", check))

    print("Бот запущен...")
    await app.run_polling()


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
