"""Private Nyan Shop support pilot for python-telegram-bot v20+.

Register with register_shop_support_handlers(application). The pilot never
changes global bot commands or the public keyboard.
"""
from __future__ import annotations

import os
import sqlite3
from html import escape
from pathlib import Path

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup, Update
from telegram.ext import Application, ApplicationHandlerStop, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters

TESTER_ID = 8587776155
DEFAULT_OWNER_ID = 6289461565
MAX_TICKETS_PER_DAY = 5
MAX_MESSAGES_PER_HOUR = 30
SUPPORT_BUTTON = "🛟 Поддержка"
CATEGORIES = {"order": "Проблема с заказом", "account": "Аккаунты", "other": "Другой вопрос"}
CATEGORY_ICONS = {"order": "📦", "account": "👤", "other": "💬"}


def customer_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"{CATEGORY_ICONS[code]} {title}", callback_data=f"shop:new:{code}")] for code, title in CATEGORIES.items()
    ] + [
        [InlineKeyboardButton("📋 Мои обращения", callback_data="shop:mine")],
    ])


def help_text(is_admin: bool) -> str:
    result = (
        "Команды поддержки Нян Шопа\n\n"
        "/support — открыть меню поддержки\n"
        "/newticket — создать обращение\n"
        "/tickets — мои обращения\n"
        "/closeticket — закрыть своё активное обращение\n"
        "/helps — полный список команд поддержки"
    )
    if is_admin:
        result += (
            "\n\nКоманды администратора\n"
            "/support_admin — панель с кнопками\n"
            "/admin_tickets — последние обращения\n"
            "/ticket 1 — история обращения №1\n"
            "/reply 1 текст — ответить покупателю\n"
            "/close 1 — закрыть обращение\n"
            "/reopen 1 — открыть повторно\n"
            "/stats_support — статистика"
        )
    return result


def admin_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📨 Открытые обращения", callback_data="shop:admin:open")],
        [InlineKeyboardButton("📋 Все обращения", callback_data="shop:admin:all"),
         InlineKeyboardButton("📊 Статистика", callback_data="shop:admin:stats")],
    ])


def ticket_controls(ticket_id: int, status: str) -> InlineKeyboardMarkup:
    action = "reopen" if status == "closed" else "close"
    label = "🔓 Открыть повторно" if status == "closed" else "🔒 Закрыть обращение"
    return InlineKeyboardMarkup([[InlineKeyboardButton(label, callback_data=f"shop:admin:{action}:{ticket_id}")],
                                 [InlineKeyboardButton("◀️ К списку", callback_data="shop:admin:open")]])


def owner_id() -> int:
    return int(os.getenv("OWNER_TELEGRAM_ID", str(DEFAULT_OWNER_ID)))


def enabled() -> bool:
    # Emergency switch, independent from the public/closed access setting.
    return os.getenv("NYAN_SHOP_SUPPORT_PILOT", "1") == "1"


def allowed(user_id: int) -> bool:
    return user_id in (TESTER_ID, owner_id()) or os.getenv("NYAN_SHOP_SUPPORT_PUBLIC", "1") == "1"


def ticket_quota_reached(db: sqlite3.Connection, user_id: int) -> bool:
    count = db.execute(
        "SELECT COUNT(*) FROM shop_tickets WHERE user_id=? AND created_at>=datetime('now','-1 day')",
        (user_id,),
    ).fetchone()[0]
    return count >= MAX_TICKETS_PER_DAY


def customer_identity(user) -> str:
    """User-facing admin label; links work even without public usernames."""
    telegram_id = int(user.id)
    username = f"@{escape(user.username)} · " if user.username else ""
    return f'{username}<a href="tg://user?id={telegram_id}">{telegram_id}</a>'


def linked_id(telegram_id: int) -> str:
    return f'<a href="tg://user?id={int(telegram_id)}">{int(telegram_id)}</a>'


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
    await update.effective_message.reply_text("Поддержка Нян Шопа\n\nВыберите тему обращения.\n\n/helps — полный список команд", reply_markup=customer_menu())
    await update.effective_message.reply_text(
        "Быстрый доступ к поддержке:",
        reply_markup=ReplyKeyboardMarkup([[KeyboardButton(SUPPORT_BUTTON)]], resize_keyboard=True),
    )
    if update.effective_user.id == owner_id():
        await update.effective_message.reply_text("Панель администратора", reply_markup=admin_menu())
    raise ApplicationHandlerStop


async def helps(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not enabled() or not update.effective_user or not allowed(update.effective_user.id):
        return
    if not update.effective_chat or update.effective_chat.type != "private":
        return
    await update.effective_message.reply_text(help_text(update.effective_user.id == owner_id()))
    raise ApplicationHandlerStop


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
        if ticket_quota_reached(db, user_id):
            await update.effective_message.reply_text("Вы достигли лимита обращений на 24 часа. Пожалуйста, попробуйте позднее.")
            raise ApplicationHandlerStop
        cursor = db.execute("INSERT INTO shop_tickets(user_id) VALUES(?)", (user_id,))
        ticket_id = cursor.lastrowid
    await update.effective_message.reply_text(f"Обращение NS-{ticket_id:06d} создано. Опишите проблему следующим сообщением. Можно прислать фото или документ.")
    if user_id != owner_id():
        await context.bot.send_message(owner_id(), f"Новое обращение NS-{ticket_id:06d} · {customer_identity(update.effective_user)}\nОтветьте на следующее сообщение с обращением.", parse_mode="HTML")
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


def is_admin_update(update: Update) -> bool:
    return bool(enabled() and update.effective_user and update.effective_user.id == owner_id()
                and update.effective_chat and update.effective_chat.type == "private")


def ticket_arg(context: ContextTypes.DEFAULT_TYPE) -> int | None:
    if not context.args:
        return None
    raw = context.args[0].upper().removeprefix("NS-")
    return int(raw) if raw.isdecimal() and int(raw) > 0 else None


async def admin_tickets(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin_update(update):
        return
    with connect() as db:
        rows = db.execute("SELECT id, user_id, status, created_at FROM shop_tickets ORDER BY id DESC LIMIT 20").fetchall()
    result = "\n".join(f"NS-{r['id']:06d} · {r['status']} · {linked_id(r['user_id'])} · {r['created_at']}" for r in rows)
    await update.effective_message.reply_text(result or "Обращений пока нет.", parse_mode="HTML")
    raise ApplicationHandlerStop


async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin_update(update):
        return
    await update.effective_message.reply_text("Панель поддержки Нян Шопа", reply_markup=admin_menu())
    raise ApplicationHandlerStop


async def admin_ticket(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin_update(update):
        return
    ident = ticket_arg(context)
    if ident is None:
        await update.effective_message.reply_text("Использование: /ticket 1")
        raise ApplicationHandlerStop
    with connect() as db:
        row = db.execute("SELECT * FROM shop_tickets WHERE id=?", (ident,)).fetchone()
        history = db.execute("SELECT sender,text,created_at FROM shop_messages WHERE ticket_id=? ORDER BY id DESC LIMIT 8", (ident,)).fetchall()
    if not row:
        await update.effective_message.reply_text("Обращение не найдено.")
    else:
        lines = [f"NS-{ident:06d} · {row['status']} · пользователь {linked_id(row['user_id'])}"]
        for msg in reversed(history):
            lines.append(f"{msg['created_at']} · {msg['sender']}: {escape((msg['text'] or '[вложение]')[:350])}")
        await update.effective_message.reply_text("\n".join(lines)[:4000], parse_mode="HTML")
    raise ApplicationHandlerStop


async def admin_reply(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin_update(update):
        return
    ident = ticket_arg(context)
    body = " ".join(context.args[1:]).strip() if ident is not None else ""
    if not body:
        await update.effective_message.reply_text("Использование: /reply 1 текст ответа")
        raise ApplicationHandlerStop
    with connect() as db:
        ticket = db.execute("SELECT user_id,status FROM shop_tickets WHERE id=?", (ident,)).fetchone()
        if not ticket or ticket['status'] != 'open':
            await update.effective_message.reply_text("Открытое обращение не найдено.")
            raise ApplicationHandlerStop
        await context.bot.send_message(ticket['user_id'], body)
        db.execute("INSERT INTO shop_messages(ticket_id,sender,text) VALUES(?,?,?)", (ident, 'admin', body))
    await update.effective_message.reply_text(f"Ответ по NS-{ident:06d} доставлен.")
    raise ApplicationHandlerStop


async def admin_status(update: Update, context: ContextTypes.DEFAULT_TYPE, status: str) -> None:
    if not is_admin_update(update):
        return
    ident = ticket_arg(context)
    if ident is None:
        await update.effective_message.reply_text("Укажите номер обращения, например /close 1")
        raise ApplicationHandlerStop
    with connect() as db:
        row = db.execute("SELECT user_id,status FROM shop_tickets WHERE id=?", (ident,)).fetchone()
        if row:
            db.execute("UPDATE shop_tickets SET status=? WHERE id=?", (status, ident))
    if not row:
        await update.effective_message.reply_text("Обращение не найдено.")
    else:
        label = "закрыто" if status == "closed" else "снова открыто"
        await update.effective_message.reply_text(f"Обращение NS-{ident:06d} {label}.")
        if row['status'] != status:
            await context.bot.send_message(row['user_id'], f"Ваше обращение NS-{ident:06d} {label}.")
    raise ApplicationHandlerStop


async def admin_close(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await admin_status(update, context, "closed")


async def admin_reopen(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await admin_status(update, context, "open")


async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin_update(update):
        return
    with connect() as db:
        counts = dict(db.execute("SELECT status,COUNT(*) FROM shop_tickets GROUP BY status").fetchall())
    await update.effective_message.reply_text(f"Обращения: {sum(counts.values())}\nОткрытые: {counts.get('open',0)}\nЗакрытые: {counts.get('closed',0)}")
    raise ApplicationHandlerStop


async def support_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.data or not query.data.startswith("shop:"):
        return
    user = update.effective_user
    if not enabled() or not user or not allowed(user.id) or not update.effective_chat or update.effective_chat.type != "private":
        await query.answer("Функция пока недоступна", show_alert=True)
        raise ApplicationHandlerStop
    await query.answer()
    parts = query.data.split(":")
    if len(parts) == 3 and parts[1] == "new" and parts[2] in CATEGORIES:
        with connect() as db:
            row = db.execute("SELECT id FROM shop_tickets WHERE user_id=? AND status='open' ORDER BY id DESC LIMIT 1", (user.id,)).fetchone()
            if row:
                await query.message.reply_text(f"У вас уже открыто NS-{row['id']:06d}. Отправьте сообщение сюда или закройте обращение.")
                raise ApplicationHandlerStop
            if ticket_quota_reached(db, user.id):
                await query.message.reply_text("Лимит — 5 обращений за 24 часа. Попробуйте позднее.")
                raise ApplicationHandlerStop
            cur = db.execute("INSERT INTO shop_tickets(user_id,category) VALUES(?,?)", (user.id, CATEGORIES[parts[2]]))
            ident = cur.lastrowid
        await query.message.reply_text(f"Создано обращение NS-{ident:06d} · {CATEGORIES[parts[2]]}\nОпишите проблему следующим сообщением.")
        if user.id != owner_id():
            await context.bot.send_message(owner_id(), f"Новое обращение NS-{ident:06d} · {CATEGORIES[parts[2]]}\nПокупатель: {customer_identity(user)}", parse_mode="HTML")
    elif query.data == "shop:mine":
        with connect() as db:
            rows = db.execute("SELECT id,category,status FROM shop_tickets WHERE user_id=? ORDER BY id DESC LIMIT 10", (user.id,)).fetchall()
        buttons = [[InlineKeyboardButton(f"NS-{r['id']:06d} · {r['status']}", callback_data=f"shop:mine:{r['id']}")] for r in rows]
        await query.message.reply_text("Ваши обращения:" if rows else "Обращений пока нет.", reply_markup=InlineKeyboardMarkup(buttons) if buttons else customer_menu())
    elif len(parts) == 3 and parts[1] == "mine" and parts[2].isdecimal():
        ident = int(parts[2])
        with connect() as db:
            row = db.execute("SELECT category,status FROM shop_tickets WHERE id=? AND user_id=?", (ident, user.id)).fetchone()
        if not row:
            await query.message.reply_text("Обращение не найдено.")
        else:
            buttons = [[InlineKeyboardButton("🔒 Закрыть обращение", callback_data=f"shop:mineclose:{ident}")]] if row['status'] == 'open' else [[InlineKeyboardButton("➕ Создать новое", callback_data="shop:menu")]]
            await query.message.reply_text(f"NS-{ident:06d} · {row['category']} · {row['status']}", reply_markup=InlineKeyboardMarkup(buttons))
    elif len(parts) == 3 and parts[1] == "mineclose" and parts[2].isdecimal():
        with connect() as db:
            result = db.execute("UPDATE shop_tickets SET status='closed' WHERE id=? AND user_id=? AND status='open'", (int(parts[2]), user.id))
        await query.message.reply_text("Обращение закрыто." if result.rowcount else "Обращение уже закрыто или не найдено.")
    elif query.data == "shop:menu":
        await query.message.reply_text("Выберите тему:", reply_markup=customer_menu())
    elif query.data == "shop:help":
        # Legacy button on messages sent before this menu revision.
        await query.message.reply_text(help_text(user.id == owner_id()))
    elif user.id == owner_id() and query.data.startswith("shop:admin:"):
        action = parts[2] if len(parts) >= 3 else ""
        if action in ("open", "all") and len(parts) == 3:
            with connect() as db:
                sql = "SELECT id,user_id,status FROM shop_tickets"
                if action == "open":
                    sql += " WHERE status='open'"
                rows = db.execute(sql + " ORDER BY id DESC LIMIT 20").fetchall()
            buttons = [[InlineKeyboardButton(f"NS-{r['id']:06d} · {r['user_id']} · {r['status']}", callback_data=f"shop:admin:view:{r['id']}")] for r in rows]
            buttons.append([InlineKeyboardButton("Назад", callback_data="shop:admin:home")])
            await query.message.reply_text("Обращения:" if rows else "Обращений нет.", reply_markup=InlineKeyboardMarkup(buttons))
        elif action == "home":
            await query.message.reply_text("Панель администратора", reply_markup=admin_menu())
        elif action == "stats":
            with connect() as db:
                counts = dict(db.execute("SELECT status,COUNT(*) FROM shop_tickets GROUP BY status").fetchall())
            await query.message.reply_text(f"Всего: {sum(counts.values())}\nОткрыто: {counts.get('open',0)}\nЗакрыто: {counts.get('closed',0)}", reply_markup=admin_menu())
        elif action in ("view", "close", "reopen") and len(parts) == 4 and parts[3].isdecimal():
            ident = int(parts[3])
            with connect() as db:
                if action in ("close", "reopen"):
                    db.execute("UPDATE shop_tickets SET status=? WHERE id=?", ("closed" if action == "close" else "open", ident))
                ticket = db.execute("SELECT user_id,category,status FROM shop_tickets WHERE id=?", (ident,)).fetchone()
                last = db.execute("SELECT sender,text FROM shop_messages WHERE ticket_id=? ORDER BY id DESC LIMIT 5", (ident,)).fetchall()
            if not ticket:
                await query.message.reply_text("Обращение не найдено.")
            else:
                history = "\n".join(f"{r['sender']}: {escape((r['text'] or '[вложение]')[:180])}" for r in reversed(last))
                await query.message.reply_text(
                    f"NS-{ident:06d} · {ticket['status']}\nТема: {escape(ticket['category'])}\nПользователь: {linked_id(ticket['user_id'])}\n\n{history}\n\nОтвет: /reply {ident} текст",
                    reply_markup=ticket_controls(ident, ticket['status']),
                    parse_mode="HTML",
                )
                if action in ("close", "reopen"):
                    await context.bot.send_message(ticket['user_id'], f"Ваше обращение NS-{ident:06d} {'закрыто' if action == 'close' else 'снова открыто'}.")
    raise ApplicationHandlerStop


async def support_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not enabled() or not update.effective_user or not allowed(update.effective_user.id):
        return
    if update.effective_chat.type != "private" or not update.effective_message:
        return
    message = update.effective_message
    user_id = update.effective_user.id
    if message.text in {SUPPORT_BUTTON, "Поддержка"}:
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
                        await context.bot.send_message(target, message.text)
                    else:
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
        sent_count = db.execute(
            "SELECT COUNT(*) FROM shop_messages WHERE ticket_id=? AND sender='customer' AND created_at>=datetime('now','-1 hour')",
            (ticket_id,),
        ).fetchone()[0]
        if sent_count >= MAX_MESSAGES_PER_HOUR:
            await message.reply_text("Лимит — 30 сообщений в час. Пожалуйста, подождите.")
            raise ApplicationHandlerStop
        copied = await context.bot.copy_message(owner_id(), message.chat_id, message.message_id)
        header = await context.bot.send_message(owner_id(), f"NS-{ticket_id:06d} · {customer_identity(update.effective_user)}\nОтветьте на это сообщение, чтобы ответить покупателю.", reply_to_message_id=copied.message_id, parse_mode="HTML")
        db.execute("INSERT INTO shop_admin_links(admin_message_id,ticket_id) VALUES(?,?)", (header.message_id, ticket_id))
        db.execute("INSERT INTO shop_admin_links(admin_message_id,ticket_id) VALUES(?,?)", (copied.message_id, ticket_id))
        db.execute("INSERT INTO shop_messages(ticket_id,sender,telegram_message_id,text) VALUES(?,?,?,?)", (ticket_id, 'customer', message.message_id, message.text))
    await message.reply_text("Сообщение передано администрации Нян Шопа.")
    raise ApplicationHandlerStop


def register_shop_support_handlers(app: Application) -> None:
    """Use one negative handler group; inactive until pilot env flag is enabled."""
    app.add_handler(CommandHandler("support", support), group=-45)
    app.add_handler(CommandHandler("helps", helps), group=-45)
    app.add_handler(CommandHandler("newticket", new_ticket), group=-45)
    app.add_handler(CommandHandler("tickets", tickets), group=-45)
    app.add_handler(CommandHandler("closeticket", close_ticket), group=-45)
    app.add_handler(CommandHandler("admin_tickets", admin_tickets), group=-45)
    app.add_handler(CommandHandler("support_admin", admin_panel), group=-45)
    app.add_handler(CommandHandler("ticket", admin_ticket), group=-45)
    app.add_handler(CommandHandler("reply", admin_reply), group=-45)
    app.add_handler(CommandHandler("close", admin_close), group=-45)
    app.add_handler(CommandHandler("reopen", admin_reopen), group=-45)
    app.add_handler(CommandHandler("stats_support", admin_stats), group=-45)
    app.add_handler(CallbackQueryHandler(support_buttons, pattern=r"^shop:"), group=-45)
    app.add_handler(MessageHandler(filters.ChatType.PRIVATE & ~filters.COMMAND, support_message), group=-45)
