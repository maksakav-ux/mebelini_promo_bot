import os
import json
import secrets
from datetime import datetime, timedelta

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    ChatMemberHandler,
)

import gspread
from google.oauth2.service_account import Credentials

# ---------------- НАСТРОЙКИ ЧЕРЕЗ ПЕРЕМЕННЫЕ ОКРУЖЕНИЯ ----------------

BOT_TOKEN = os.getenv("BOT_TOKEN")          # токен бота от @BotFather
CHANNEL_ID = os.getenv("CHANNEL_ID")        # например "@amebelini"
SHEET_ID = os.getenv("SHEET_ID")            # ID таблицы из URL
SERVICE_ACCOUNT_JSON = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")  # JSON ключ как строка

# сколько времени после подписки действует промокод
PROMO_WINDOW_HOURS = 24


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
    expected = ["user_id", "username", "code", "code_created_at", "joined_at"]
    if header != expected:
        sheet.clear()
        sheet.append_row(expected)

    return sheet


def find_user_row(sheet, user_id: int):
    """
    Ищем строку пользователя по user_id.
    Возвращаем dict с данными или None.
    """
    values = sheet.get_all_values()  # список списков
    if len(values) <= 1:
        return None

    # values[0] — заголовки
    for idx, row in enumerate(values[1:], start=2):  # начинаем со 2-й строки (индекс 2)
        if len(row) == 0:
            continue
        uid = row[0]
        if uid == str(user_id):
            # гарантируем нужную длину
            while len(row) < 5:
                row.append("")
            return {
                "row_index": idx,
                "user_id": row[0],
                "username": row[1],
                "code": row[2],
                "code_created_at": row[3],
                "joined_at": row[4],
            }

    return None


def set_joined_at(sheet, user_id: int, username: str | None, joined_at_iso: str):
    """
    Сохраняем факт подписки (joined_at).
    Если пользователя нет в таблице — добавляем.
    Если есть — НЕ трогаем (чтобы не переоткрывать окно акции).
    """
    existing = find_user_row(sheet, user_id)
    if existing:
        # если уже есть joined_at, НЕ переписываем
        if existing["joined_at"]:
            return
        row_index = existing["row_index"]
        sheet.update_cell(row_index, 5, joined_at_iso)  # колонка E = joined_at
    else:
        sheet.append_row(
            [
                str(user_id),
                username or "",
                "",          # code
                "",          # code_created_at
                joined_at_iso,
            ]
        )


def set_code(sheet, user_id: int, code: str, now_iso: str):
    """
    Записываем выданный код и время выдачи.
    Предполагаем, что пользователь уже есть в таблице.
    """
    existing = find_user_row(sheet, user_id)
    if not existing:
        # на всякий случай добавим
        sheet.append_row(
            [str(user_id), "", code, now_iso, ""]
        )
    else:
        row_index = existing["row_index"]
        sheet.update_row(row_index, [
            str(user_id),
            existing["username"],
            code,
            now_iso,
            existing["joined_at"],
        ])


def generate_code() -> str:
    """Генерация промокода вида MEBEL-AB12CD."""
    suffix = secrets.token_hex(3).upper()
    return f"MEBEL-{suffix}"


# ---------------- ХЭНДЛЕРЫ ЧЛЕНСТВА В КАНАЛЕ ----------------

async def track_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Отслеживаем новые подписки на канал.
    Срабатывает, когда пользователь меняет статус в чате (канале).
    """
    chat_member_update = update.chat_member
    chat = chat_member_update.chat

    # работаем только с нашим каналом
    # для каналов chat.id — отрицательный int, CHANNEL_ID у нас строкой '@name',
    # поэтому просто проверяем тип канала
    if chat.type != "channel":
        return

    old = chat_member_update.old_chat_member.status
    new = chat_member_update.new_chat_member.status

    # интересует переход из "left/kicked" в "member/administrator"
    if old in ("left", "kicked") and new in ("member", "administrator"):
        user = chat_member_update.new_chat_member.user
        now_iso = datetime.utcnow().isoformat()

        sheet = get_sheet()
        set_joined_at(sheet, user.id, user.username, now_iso)
        print(f"User {user.id} joined the channel at {now_iso}")


# ---------------- КОМАНДЫ БОТА ----------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "Здравствуйте! 🎉\n\n"
        "Здесь вы можете получить персональный промокод на скидку.\n\n"
        "1️⃣ Подпишитесь на наш канал:\n"
        f"https://t.me/{CHANNEL_ID.lstrip('@')}\n\n"
        "2️⃣ После подписки нажмите /check, и бот проверит подписку и выдаст код.\n\n"
        "Промокод выдаётся только новым подписчикам в течение 24 часов после подписки."
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

    sheet = get_sheet()
    now = datetime.utcnow()

    # 2. Смотрим, есть ли пользователь в таблице
    info = find_user_row(sheet, user_id)

    # ---- СЛУЧАЙ: пользователя ещё нет в таблице ----
    if not info:
        # Если он сейчас подписан, но у нас нет joined_at, считаем его СТАРЫМ подписчиком
        await update.message.reply_text(
            "Вы уже подписаны на канал. "
            "Промокод действует только для новых подписчиков в течение первых 24 часов после подписки. 😉"
        )
        # на всякий случай добавим его без кода, чтобы в будущем не считать новым
        set_joined_at(sheet, user_id, user.username, "")
        return

    # ---- СЛУЧАЙ: есть запись в таблице ----

    # если код уже есть — просто напоминаем, что он уже получал/а акцию
    if info["code"]:
        await update.message.reply_text(
            "Вы уже получали персональный промокод. "
            "Следите за акциями и скидками в нашем канале! 😉"
        )
        return

    # если нет joined_at — считаем старым подписчиком (подписка была до старта отслеживания)
    if not info["joined_at"]:
        await update.message.reply_text(
            "Вы уже подписаны на канал. "
            "Промокод доступен только для новых подписчиков в течение 24 часов после подписки."
        )
        return

    # есть joined_at, считаем окно
    try:
        joined_at = datetime.fromisoformat(info["joined_at"])
    except ValueError:
        # если кривой формат, на всякий случай считаем старым подписчиком
        await update.message.reply_text(
            "Вы уже подписаны на канал. "
            "Промокод доступен только для новых подписчиков в течение 24 часов после подписки."
        )
        return

    if now - joined_at > timedelta(hours=PROMO_WINDOW_HOURS):
        # подписка старше 24 часов → код не выдаём
        await update.message.reply_text(
            "Промокод доступен только в течение 24 часов после подписки на канал. "
            "Следите за новыми акциями и скидками! 😊"
        )
        return

    # Всё ок: подписка не старше 24 часов, кода ещё не было → выдаём код
    code = generate_code()
    now_iso = now.isoformat()
    set_code(sheet, user_id, code, now_iso)

    await update.message.reply_text(
        "Отлично! Вы подписаны на канал и попадаете в акцию 🎉\n\n"
        f"Ваш персональный промокод на скидку:\n\n"
        f"👉 {code} 👈\n\n"
        "Сообщите его менеджеру при оформлении заказа."
    )


# ---------------- ЗАПУСК ПРИЛОЖЕНИЯ ----------------

def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN is not set")

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # команды
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("check", check))

    # отслеживание новых подписчиков в канале
    app.add_handler(ChatMemberHandler(track_subscription, ChatMemberHandler.CHAT_MEMBER))

    print("Бот запущен...")
    app.run_polling()


if __name__ == "__main__":
    main()
