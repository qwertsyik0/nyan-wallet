"""Topic archive for the standalone python-telegram-bot process, not Wallet API."""
import asyncio
import io
import json
import logging
import os
import sqlite3
from pathlib import Path
from telegram.ext import CommandHandler, MessageHandler, ApplicationHandlerStop, filters

OWNER = int(os.getenv("NYAN_ARCHIVE_OWNER_ID", "6289461565"))
CHAT = int(os.getenv("NYAN_ARCHIVE_CHAT_ID", "-1006074926414"))
DB = Path(__file__).resolve().parent / ".nyan_archive" / "messages.sqlite3"
log = logging.getLogger(__name__)

def connect():
    DB.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    c = sqlite3.connect(str(DB), timeout=20)
    c.row_factory = sqlite3.Row
    return c

def initialize():
    with connect() as c:
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("""CREATE TABLE IF NOT EXISTS messages(
            chat INTEGER, topic INTEGER, mid INTEGER, date TEXT,
            author TEXT, text TEXT, attachment TEXT,
            PRIMARY KEY(chat,mid))""")
        c.execute("CREATE INDEX IF NOT EXISTS topic_order ON messages(chat,topic,mid)")
        c.execute("""CREATE TABLE IF NOT EXISTS snapshots(
            id INTEGER PRIMARY KEY, chat INTEGER, topic INTEGER, command_mid INTEGER,
            content TEXT NOT NULL, UNIQUE(chat,command_mid))""")

def record(message):
    text = message.text or message.caption or ""
    if text.startswith("/"):
        return
    if not text and not message.effective_attachment:
        return
    sender = message.sender_chat
    user = message.from_user
    author = (sender.title + " [chat " + str(sender.id) + "]") if sender else (
        (user.full_name + (" @" + user.username if user.username else "") +
         " [id " + str(user.id) + "]") if user else "unknown")
    attachment = ""
    for kind in ("document","video","audio","voice","photo","sticker","animation","video_note"):
        item = getattr(message, kind, None)
        if item:
            attachment = kind + (": " + getattr(item, "file_name", "") if getattr(item, "file_name", None) else "")
            break
    with connect() as c:
        values = (message.chat_id, message.message_thread_id or 0, message.message_id,
                  message.date.isoformat(), author, text, attachment)
        # UPDATE + INSERT OR IGNORE works with the older SQLite on the bot host.
        # Both statements share one transaction; edits preserve the original date.
        c.execute("UPDATE messages SET topic=?,author=?,text=?,attachment=? WHERE chat=? AND mid=?",
                  (values[1], author, text, attachment, values[0], values[2]))
        c.execute("INSERT OR IGNORE INTO messages VALUES(?,?,?,?,?,?,?)", values)

def select_rows(chat, topic, before, count):
    with connect() as c:
        return [dict(r) for r in reversed(c.execute(
            "SELECT * FROM messages WHERE chat=? AND topic=? AND mid<? ORDER BY mid DESC LIMIT ?",
            (chat, topic, before, count)).fetchall())]

def snapshot(chat, topic, command, rows):
    with connect() as c:
        c.execute("INSERT OR IGNORE INTO snapshots(chat,topic,command_mid,content) VALUES(?,?,?,?)",
                  (chat,topic,command,json.dumps(rows,ensure_ascii=False)))
        return c.execute("SELECT id FROM snapshots WHERE chat=? AND command_mid=?",
                         (chat,command)).fetchone()["id"]

def render(rows):
    parts = ["NYAN WORLD // topic export",
             "Text and captions only. Attachment contents are not extracted.",
             "Only messages received since archive installation are available.", ""]
    for r in rows:
        parts.append("[" + r["date"] + "] " + r["author"] + " // message " + str(r["mid"]))
        parts.append(r["text"] or "")
        if r["attachment"]:
            parts.append("[attachment: " + r["attachment"] + "]")
        parts.append("")
    return "\n".join(parts)

async def collect(update, context):
    message = update.effective_message
    if not message or message.chat_id != CHAT:
        return
    try:
        await asyncio.to_thread(record, message)
    except Exception:
        log.exception("Topic archive recording failed")

async def command(update, context):
    message = update.effective_message
    if not message:
        return
    if message.sender_chat or not update.effective_user or update.effective_user.id != OWNER:
        raise ApplicationHandlerStop
    if message.chat_id != CHAT:
        await message.reply_text("Use this command inside a Nyan World topic.")
        raise ApplicationHandlerStop
    try:
        if len(context.args) != 1 or not context.args[0].isascii() or not context.args[0].isdigit():
            raise ValueError()
        count = int(context.args[0])
        if not 1 <= count <= 1000:
            raise ValueError()
    except ValueError:
        await message.reply_text("Usage: /save N or /export N. N: 1..1000.")
        raise ApplicationHandlerStop
    rows = await asyncio.to_thread(select_rows, CHAT, message.message_thread_id or 0,
                                  message.message_id, count)
    name = message.text.split()[0].split("@")[0].lower()
    if name == "/save":
        sid = await asyncio.to_thread(snapshot, CHAT, message.message_thread_id or 0,
                                     message.message_id, rows)
        response = "Saved snapshot #" + str(sid) + ": " + str(len(rows)) + "/" + str(count) + " messages."
        try:
            await context.bot.send_message(OWNER, response, parse_mode=None)
        except Exception:
            await message.reply_text("Snapshot saved. Open the bot in private and press Start.")
    else:
        if not rows:
            await message.reply_text("No archived messages above this command in this topic yet.")
            raise ApplicationHandlerStop
        content = io.BytesIO(render(rows).encode("utf-8-sig"))
        filename = "nyan-topic-" + str(message.message_thread_id or 0) + "-" + str(message.message_id) + ".txt"
        try:
            await context.bot.send_document(OWNER, document=content, filename=filename,
                caption=str(len(rows)) + "/" + str(count) + " messages from this topic.", parse_mode=None)
        except Exception:
            log.warning("Archive delivery to owner failed")
            await message.reply_text("Export not delivered. Open the bot in private and press Start, then retry.")
    raise ApplicationHandlerStop

def register_topic_archive(app):
    initialize()
    base = min([0] + list(app.handlers.keys())) - 2
    app.add_handler(MessageHandler(filters.Chat(CHAT), collect, block=True), group=base)
    app.add_handler(CommandHandler(["save","export"], command, block=True), group=base+1)
