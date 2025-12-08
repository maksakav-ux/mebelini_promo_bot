import os
import json
import secrets
from datetime import datetime

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
)

import gspread
from google.oauth2.service_account import Credentials

# ---------------- НАСТРОЙКИ ЧЕРЕЗ ПЕРЕМЕННЫЕ ОКРУЖЕНИЯ ----------------

BOT_TOKEN = os.getenv("BOT_TOKEN")          # токен бота от @BotFather
CHANNEL_ID = os.getenv("CHANNEL_ID")        # например "@amebelini"
SHEET_ID = os.getenv("SHEET_ID")            # ID таблицы из URL
SERVICE_ACCOUNT_JSON = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")  # JSON ключ как строка


# ---------------- РАБОТА С GOOGLE SHEETS ----------------

def get_sheet():
    if not SERVICE_ACCOUNT_JSON:
        raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_JSON is not set")

    info = json.loads(SERVICE_ACCOUNT_JSON)
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_info(info, scopes=scopes)
    client = gspread.authorize(creds)

    sh = client.open_by_key(SHEET_ID)
    sheet = sh.sheet1

    # убеждаемся, что есть шапка нужного формата
    header = sheet.row_values(1)
    expected = ["user_id", "username", "code", "code_created_at"]
    if header != expected:
        sheet.clear()
        sheet.append_row(expected)

    return sheet


def find_user_row(sheet, user_id: int):
    """
    Ищем строку пользователя по user_id.
    Возвращаем dict с данными или None.
    """
    values = sheet.get_all_values()
    if len(values) <= 1:
        return None

    for idx, row in enumerate(values[1:], start=2):  # строки с данными начинаются с 2-й
        if not row:
            continue
        uid = row[0]
        if uid == str(user_id):
            while len(row) < 4:
                row.append("")
            return {
                "row_index": idx,
                "user_id": row[0],
                "username": row[1],
                "code": row[2],
                "code_created_at": row[3],
            }
    return None


def set_user_no_code(sheet, user_id: int, username: str | None):
    """
    Добавляем пользователя в таблицу без кода, если его там ещё нет.
    """
    existing = find_user_row(sheet, user_id)
    if existing:
        return

    sheet.append_row(
        [
            str(user_id),
            username or "",
            "",
            "",
        ]
    )


def set_code(sheet, user_id: int, username: str | None, code: str, now_iso: str):
    """
    Записываем/обновляем код для пользователя.
    Если его нет в таблице — добавляем.
    """
    existing = find_user_row(sheet, user_id)
    row_values = [str(user_id), username or "", code, now_iso]

    if existing:
        row_index = existing["row_index"]
        # обновляем строку A-D
        range_name = f"A{row_index}:D{row_index}"
        sheet.update(range_name, [row_values])
    else:
        sheet.append_row(row_values)


def generate_code() -> str:
    """Генерация промокода вида MEBEL-AB12CD."""
    suffix = secrets.token_hex(3).upper()
    return f"MEBEL-{suffix}"


# ---------------- КОМАНДЫ БОТА ----------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id

    # 1. Проверяем подписку
    try:
        member = await context.bot.get_chat_member(CHANNEL_ID, user_id)
        status = member.status  # "member", "administrator", "creator", "left", "kicked"
    except Exception as e:
        print("get_chat_member error in /start:", e)
        status = "left"

    sheet = get_sheet()
    info = find_user_row(sheet, user_id)

    # ---------- ПОДПИСАН ----------
    if status in ["member", "administrator", "creator"]:
        if info:
            # подписан + есть строка
            await update.message.reply_text(
                "Вы уже подписаны на канал. Следите за акциями и скидками!"
            )
        else:
            # подписан + строки нет → добавляем без кода
            set_user_no_code(sheet, user_id, user.username)
            await update.message.reply_text(
                "Вы уже подписаны на канал. Следите за акциями и скидками!"
            )
        return

    # ---------- НЕ ПОДПИСАН ----------
    if info is None:
        # не подписан + строки нет
        await update.message.reply_text(
            "Вы ещё не подписаны на канал.\n"
            f"Подпишитесь: https://t.me/{CHANNEL_ID.lstrip('@')}\n"
            "После подписки выполните команду /check, чтобы получить промокод."
        )
    else:
        # не подписан + строка есть
        await update.message.reply_text(
            "Вы были подписаны, но сейчас у вас нет подписки.\n"
            "Советуем подписаться вновь, чтобы не пропускать акции и скидки 🙂\n"
            f"Ссылка на канал: https://t.me/{CHANNEL_ID.lstrip('@')}"
        )


async def check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id

    # 1. Проверяем подписку
    try:
        member = await context.bot.get_chat_member(CHANNEL_ID, user_id)
        status = member.status
    except Exception as e:
        print("get_chat_member error in /check:", e)
        status = "left"

    # НЕ подписан → сразу просим подписаться
    if status not in ["member", "administrator", "creator"]:
        await update.message.reply_text(
            "Сначала подпишитесь на канал, затем выполните команду /check.\n"
            f"Ссылка: https://t.me/{CHANNEL_ID.lstrip('@')}"
        )
        return

    # ПОДПИСАН → работаем с таблицей
    sheet = get_sheet()
    info = find_user_row(sheet, user_id)
    now_iso = datetime.utcnow().isoformat()

    # есть строка и code не пустой → уже получал промокод
    if info and info["code"]:
        await update.message.reply_text(
            "Вы уже получали персональный промокод. "
            "Следите за новыми акциями и скидками в канале!"
        )
        return

    # есть строка и code пустой → уже подписан, но промо ему не положено
    if info and not info["code"]:
        await update.message.reply_text(
            "Вы уже подписаны на канал. Следите за акциями и скидками!"
        )
        return

    # строки нет вообще → новый подписчик, выдаём код
    code = generate_code()
    set_code(sheet, user_id, user.username, code, now_iso)

    await update.message.reply_text(
        "Отлично! Вы подписаны на канал 🎉\n\n"
        f"Ваш персональный промокод на скидку:\n\n"
        f"👉 {code} 👈\n\n"
        "Сообщите его менеджеру при оформлении заказа."
    )


# ---------------- ЗАПУСК ПРИЛОЖЕНИЯ ----------------

def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN is not set")

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("check", check))

    print("Бот запущен...")
    app.run_polling()


if __name__ == "__main__":
    main()
