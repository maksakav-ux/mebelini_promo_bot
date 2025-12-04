import os
import sqlite3
import secrets
from datetime import datetime

from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

TOKEN = os.getenv("BOT_TOKEN")          # зададим через Railway
CHANNEL_ID = os.getenv("CHANNEL_ID")    # например "@mebelini_channel"

# ---- ПУТЬ К БАЗЕ ДАННЫХ ----
DB_DIR = os.getenv("DB_DIR", "data")    # на Railway будет /app/data
DB_PATH = os.path.join(DB_DIR, "users.db")


def init_db():
    os.makedirs(DB_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            code TEXT,
            created_at TEXT
        )
        """
    )
    conn.commit()
    conn.close()


def get_user(user_id: int):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT user_id, username, code, created_at FROM users WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    conn.close()
    return row


def save_user(user_id: int, username: str | None, code: str):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        "INSERT OR REPLACE INTO users (user_id, username, code, created_at) VALUES (?, ?, ?, ?)",
        (user_id, username, code, datetime.utcnow().isoformat())
    )
    conn.commit()
    conn.close()


def generate_code() -> str:
    # код вида MEBEL-AB12CD
    suffix = secrets.token_hex(3).upper()
    return f"MEBEL-{suffix}"


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "Здравствуйте! 🎉\n\n"
        "Здесь вы можете получить персональный промокод на скидку.\n\n"
        "1️⃣ Подпишитесь на наш канал:\n"
        f"{CHANNEL_ID}\n\n"
        "2️⃣ После подписки нажмите /check, и бот проверит подписку и выдаст код."
    )
    await update.message.reply_text(text)


async def check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id

    existing = get_user(user_id)

    # проверяем подписку
    try:
        member = await context.bot.get_chat_member(CHANNEL_ID, user_id)
        status = member.status  # "member", "administrator", "creator", "left", "kicked"
    except Exception:
        status = "left"

    if status not in ["member", "administrator", "creator"]:
        await update.message.reply_text(
            "Вы ещё не подписаны на канал.\n"
            "Подпишитесь, пожалуйста, и потом снова нажмите /check 😊"
        )
        return

    # уже есть в базе → второй заход
    if existing:
        await update.message.reply_text(
            "Вы уже подписаны на канал. Следите за акциями и скидками! 😉"
        )
        return

    # подписан и первый раз → выдаём код
    code = generate_code()
    save_user(user_id, user.username, code)

    await update.message.reply_text(
        "Отлично! Вы подписаны на канал 🎉\n\n"
        f"Ваш персональный промокод на скидку:\n\n"
        f"👉 {code} 👈\n\n"
        "Сообщите его менеджеру при оформлении заказа."
    )


async def main():
    init_db()

    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("check", check))

    print("Бот запущен...")
    await app.run_polling()


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
