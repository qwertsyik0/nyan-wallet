"""NYAN MAFIA owner-only Telegram command for the existing python-telegram-bot."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
import urllib.error
import urllib.parse
import urllib.request

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes


def _api_base() -> str:
    value = (
        os.getenv("NYAN_MAFIA_API_URL")
        or os.getenv("NYAN_WALLET_API")
        or os.getenv("NYAN_WALLET_API_URL")
        or ""
    ).strip().rstrip("/")
    parsed = urllib.parse.urlsplit(value)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError("Укажи NYAN_MAFIA_API_URL (HTTPS-адрес API FirstVDS)")
    return value


def _open_registration() -> dict:
    token = os.getenv("BOT_TOKEN", "").strip()
    if not token:
        raise ValueError("BOT_TOKEN не задан")
    signature = hmac.new(
        token.encode("utf-8"), b"nyan-mafia:open:v1", hashlib.sha256,
    ).hexdigest()
    req = urllib.request.Request(
        _api_base() + "/api/internal/nyan-mafia/open",
        data=b"{}",
        headers={
            "X-Nyan-Mafia-Command": signature,
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=12) as response:
            result = json.load(response)
        if not result.get("ok") or not result.get("invitation_queued"):
            raise RuntimeError("API не подтвердил открытие набора")
        return result
    except urllib.error.HTTPError as error:
        try:
            body = json.loads(error.read(4096))
            detail = str(body.get("detail") or "Ошибка API")
        except Exception:
            detail = "Ошибка API"
        raise RuntimeError(f"HTTP {error.code}: {detail[:250]}") from error


async def mafia_open_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    uid = update.effective_user.id if update.effective_user else None
    owner = os.getenv("OWNER_TELEGRAM_ID", "").strip()
    # Only a PRIVATE message from the exact configured owner can open the game.
    if not uid or not owner.isdecimal() or str(uid) != owner:
        return
    if not update.effective_chat or update.effective_chat.type != "private":
        return
    if not update.effective_message:
        return
    try:
        data = await asyncio.to_thread(_open_registration)
    except Exception as error:
        await update.effective_message.reply_text(
            "не удалось открыть набор NYAN MAFIA: " + str(error)[:320]
        )
        return
    await update.effective_message.reply_text(
        f"набор NYAN MAFIA открыт (раунд #{data['round_id']}). "
        "приглашение с кнопкой поставлено в очередь отправки в группу."
    )


def register_nyan_mafia_bot_handlers(app: Application) -> None:
    app.add_handler(CommandHandler("mafia", mafia_open_command), group=-45)
