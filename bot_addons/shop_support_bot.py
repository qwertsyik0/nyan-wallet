"""Private Nyan Shop support pilot for python-telegram-bot v20+.

Register with register_shop_support_handlers(application). The pilot never
changes global bot commands or the public keyboard.
"""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from telegram import KeyboardButton, ReplyKeyboardMarkup, Update
from telegram.ext import Application, ApplicationHandlerStop, CommandHandler, ContextTypes, MessageHandler, filters

TESTER_ID = 8587776155
DEFAULT_OWNER_ID = 6289461565
SUPPORT_BUTTON = "Поддержка"


def owner_id() -> int:
    return int(os.getenv("OWNER_TELEGRAM_ID", str(DEFAULT_OWNER_ID)))


def enabled() -> bool:
    # Registering the addon is the explicit pilot opt-in. An emergency override
    # can disable it without removing the registration.
    return os.getenv("NYAN_SHOP_SUPPORT_PILOT", "1") == "1"


def allowed(user_id: int) -> bool:
    return user_id in (TESTER_ID, owner_id())


def db_path() -> Path:
    return Path(os.getenv("NYAN_SHOP_SUPPORT_DB", "/home/nyanteam/new_bot/shop_support.sqlite3"))


def connect() -> sqlite3.Connection:
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout = 10000")
    connection.execute("""CREATE TABLE IF NOT EXISTS shop_tickets (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        category TEXT NOT NULL DEFAULT 'Общий вопрос',
        status TEXT NOT NULL DEFAULT 'open',
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )""")
    connection.execute("""CREATE TABLE IF NOT EXISTS shop_messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ticket_id INTEGER NOT NULL,
        sender TEXT NOT NULL,
        telegram_message_id INTEGER,
        text TEXT,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )""")
    connection.execute("""CREATE TABLE IF NOT EXISTS shop_admin_links (
        admin_message_id INTEGER PRIMARY KEY,
        ticket_id INTEGER NOT NULL
    )""")
    connection.commit()
    return connection


async def support(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not enabled() or not update.effective_user or not allowed(update.effective_user.id):
        return
    if update.effective_chat.type != "private":
        return
    await update.effective_message.reply_text(
        "Поддержка Нян Шопа (закрытый тест)\n\n"
        "Чтобы создать обращение, напишите /newticket и опишите проблему.\n"
        "Ваши обращения: /tickets\n"
        "Закрыть активное обращение: /closeticket",
        reply_markup=ReplyKeyboardMarkup([[KeyboardButton(SUPPORT_BUTTON)]], resize_keyboard=True),
    )


async def new_ticket(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not enabled() or not update.effective_user or not allowed(update.effective_user.id):
        return
    if update.effective_chat.type != "private":
        return
    user_id = update.effective_user.id
    with connect() as db:
        existing = db.execute("SELECT id FROM shop_tickets WHERE user_id=? AND status='open' ORDER BY id DESC LIMIT 1", (user_id,)).fetchone()
        if existing:
            await update.effective_message.reply_text(f"У вас уже открыто обращение NS-{existing['id']:06d}. Напишите сообщение сюда.")
            raise ApplicationHandlerStop
        cursor = db.execute("INSERT INTO shop_tickets(user_id) VALUES(?)", (user_id,))
        ticket_id = cursor.lastrowid
    await update.effective_message.reply_text(f"Обращение NS-{ticket_id:06d} создано. Опишите проблему следующим сообщением. Можно прислать фото или документ.")
    if user_id != owner_id():
        await context.bot.send_message(owner_id(), f"Новое обращение NS-{ticket_id:06d} от тестировщика {user_id}. Ответьте на следующее сообщение с обращением.")
    raise ApplicationHandlerStop


async def tickets(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not enabled() or not update.effective_user or not allowed(update.effective_user.id):
        return
    if update.effective_chat.type != "private":
        return
    with connect() as db:
        rows = db.execute("SELECT id, status FROM shop_tickets WHERE user_id=? ORDER BY id DESC LIMIT 10", (update.effective_user.id,)).fetchall()
    await update.effective_message.reply_text("\n".join(f"NS-{row['id']:06d} — {row['status']}" for row in rows) if rows else "Обращений пока нет. /newticket")
    raise ApplicationHandlerStop


async def close_ticket(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not enabled() or not update.effective_user or not allowed(update.effective_user.id):
        return
    if update.effective_chat.type != "private":
        return
    with connect() as db:
        row = db.execute("SELECT id FROM shop_tickets WHERE user_id=? AND status='open' ORDER BY id DESC LIMIT 1", (update.effective_user.id,)).fetchone()
        if row:
            db.execute("UPDATE shop_tickets SET status='closed' WHERE id=?", (row['id'],))
    await update.effective_message.reply_text(f"Обращение NS-{row['id']:06d} закрыто." if row else "Открытых обращений нет.")
    raise ApplicationHandlerStop


async def support_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not enabled() or not update.effective_user or not allowed(update.effective_user.id):
        return
    if update.effective_chat.type != "private" or not update.effective_message:
        return
    message = update.effective_message
    user_id = update.effective_user.id
    if message.text == SUPPORT_BUTTON:
        await support(update, context)
        raise ApplicationHandlerStop
    with connect() as db:
        if user_id == owner_id() and message.reply_to_message:
            link = db.execute("SELECT ticket_id FROM shop_admin_links WHERE admin_message_id=?", (message.reply_to_message.message_id,)).fetchone()
            if link:
                ticket = db.execute("SELECT user_id, status FROM shop_tickets WHERE id=?", (link['ticket_id'],)).fetchone()
                if ticket and ticket['status'] == 'open':
                    target = ticket['user_id']
                    if message.text:
                        await context.bot.send_message(target, "Администрация Нян Шопа:\n\n" + message.text)
                    else:
                        await context.bot.send_message(target, "Администрация Нян Шопа:")
                        await context.bot.copy_message(target, message.chat_id, message.message_id)
                    db.execute("INSERT INTO shop_messages(ticket_id,sender,telegram_message_id,text) VALUES(?,?,?,?)", (link['ticket_id'], 'admin', message.message_id, message.text))
                    await message.reply_text("Ответ доставлен.")
                    raise ApplicationHandlerStop
        ticket = db.execute("SELECT id FROM shop_tickets WHERE user_id=? AND status='open' ORDER BY id DESC LIMIT 1", (user_id,)).fetchone()
        if not ticket:
            return
        if user_id == owner_id():
            return  # Owner replies only to linked admin messages.
        ticket_id = ticket['id']
        copied = await context.bot.copy_message(owner_id(), message.chat_id, message.message_id)
        header = await context.bot.send_message(owner_id(), f"NS-{ticket_id:06d} · сообщение от {user_id}\nОтветьте на это сообщение, чтобы ответить покупателю.", reply_to_message_id=copied.message_id)
        db.execute("INSERT INTO shop_admin_links(admin_message_id,ticket_id) VALUES(?,?)", (header.message_id, ticket_id))
        db.execute("INSERT INTO shop_admin_links(admin_message_id,ticket_id) VALUES(?,?)", (copied.message_id, ticket_id))
        db.execute("INSERT INTO shop_messages(ticket_id,sender,telegram_message_id,text) VALUES(?,?,?,?)", (ticket_id, 'customer', message.message_id, message.text))
    await message.reply_text("Сообщение передано администрации Нян Шопа.")
    raise ApplicationHandlerStop


def register_shop_support_handlers(app: Application) -> None:
    """Use one negative handler group; inactive until pilot env flag is enabled."""
    app.add_handler(CommandHandler("support", support), group=-45)
    app.add_handler(CommandHandler("newticket", new_ticket), group=-45)
    app.add_handler(CommandHandler("tickets", tickets), group=-45)
    app.add_handler(CommandHandler("closeticket", close_ticket), group=-45)
    app.add_handler(MessageHandler(filters.ChatType.PRIVATE & ~filters.COMMAND, support_message), group=-45)
