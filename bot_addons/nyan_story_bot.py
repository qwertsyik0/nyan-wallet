"""Owner-only /story and /story_close commands for NYAN GAMES group chats."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes


def _api_base() -> str:
    value = (
        os.getenv("NYAN_STORY_API_URL")
        or os.getenv("NYAN_WALLET_API")
        or os.getenv("NYAN_WALLET_API_URL")
        or ""
    ).strip().rstrip("/")
    parsed = urllib.parse.urlsplit(value)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError("укажи NYAN_STORY_API_URL (HTTPS-адрес API FirstVDS)")
    return value


def _command(action: str, chat_id: int) -> dict:
    token = os.getenv("BOT_TOKEN", "").strip()
    if not token:
        raise ValueError("BOT_TOKEN не задан")
    stamp = int(time.time())
    signed = f"nyan-story:{action}:v1:{chat_id}:{stamp}".encode("utf-8")
    signature = hmac.new(token.encode("utf-8"), signed, hashlib.sha256).hexdigest()
    req = urllib.request.Request(
        _api_base() + f"/api/internal/nyan-story/{action}",
        data=b"{}",
        headers={
            "X-Nyan-Story-Chat": str(chat_id),
            "X-Nyan-Story-Time": str(stamp),
            "X-Nyan-Story-Signature": signature,
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=12) as response:
            result = json.load(response)
    except urllib.error.HTTPError as error:
        try:
            body = json.loads(error.read(4096))
            detail = str(body.get("detail") or "ошибка API")
        except Exception:
            detail = "ошибка API"
        raise RuntimeError(f"HTTP {error.code}: {detail[:250]}") from error
    if not result.get("ok"):
        raise RuntimeError("сервер не подтвердил команду")
    return result


async def _run(update: Update, action: str) -> None:
    user = update.effective_user
    chat = update.effective_chat
    owner = os.getenv("OWNER_TELEGRAM_ID", "").strip()
    if not user or not owner.isdecimal() or str(user.id) != owner:
        return
    if not chat or chat.type not in ("group", "supergroup"):
        if update.effective_message:
            await update.effective_message.reply_text("используй команду в группе с участниками")
        return
    try:
        data = await asyncio.to_thread(_command, action, chat.id)
    except Exception as error:
        if update.effective_message:
            await update.effective_message.reply_text("не удалось выполнить команду: " + str(error)[:250])
        return
    if action == "close" and update.effective_message:
        await update.effective_message.reply_text(
            f"набор №{data['round_id']} закрыт. записалось: {data['players']}."
        )
    # /story queues its own rich invitation with a button via Telegram relay.


async def story_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _run(update, "open")


async def story_close_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _run(update, "close")


def register_nyan_story_bot_handlers(app: Application) -> None:
    app.add_handler(CommandHandler("story", story_command), group=-46)
    app.add_handler(CommandHandler("story_close", story_close_command), group=-46)
