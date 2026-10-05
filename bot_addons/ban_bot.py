from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import os
import socket
import time
import urllib.error
import urllib.request
from typing import Any
from urllib.parse import urlparse

from telegram import BotCommand, BotCommandScopeChat, Update
from telegram.error import TelegramError
from telegram.ext import Application, ApplicationHandlerStop, CommandHandler, ContextTypes

logger = logging.getLogger("nyan_wallet.ban_bot")

DEFAULT_API_BASE = "https://nyan-wallet-api.onrender.com"
DEFAULT_OWNER_ID = 6289461565
MAX_REASON_LENGTH = 300
MAX_RESPONSE_BYTES = 64 * 1024
TIMEOUT_SECONDS = 10.0
_menu_hook_installed = False


class BanBotError(RuntimeError):
    pass


def _owner_id() -> int:
    raw = os.getenv("OWNER_TELEGRAM_ID", str(DEFAULT_OWNER_ID)).strip()
    try:
        value = int(raw)
    except ValueError as exc:
        raise BanBotError("OWNER_TELEGRAM_ID должен быть положительным числом") from exc
    if value <= 0:
        raise BanBotError("OWNER_TELEGRAM_ID должен быть положительным числом")
    return value


def _api_base() -> str:
    value = os.getenv("NYAN_WALLET_API", DEFAULT_API_BASE).strip().rstrip("/")
    parsed = urlparse(value)
    if parsed.scheme not in {"https", "http"} or not parsed.netloc:
        raise BanBotError("NYAN_WALLET_API содержит некорректный URL")
    if parsed.scheme != "https" and parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise BanBotError("NYAN_WALLET_API должен использовать HTTPS")
    return value


def _bot_token() -> str:
    token = os.getenv("BOT_TOKEN", "").strip()
    if not token:
        raise BanBotError("BOT_TOKEN отсутствует в окружении")
    return token


def _http_detail(exc: urllib.error.HTTPError) -> str:
    try:
        raw = exc.read(MAX_RESPONSE_BYTES + 1)
    except Exception:
        return f"HTTP {exc.code}"
    try:
        value = json.loads(raw.decode("utf-8"))
    except Exception:
        text = raw.decode("utf-8", errors="replace").strip()
        return text[:500] or f"HTTP {exc.code}"
    if isinstance(value, dict) and isinstance(value.get("detail"), str):
        return value["detail"][:500]
    return f"HTTP {exc.code}"


def signed_action(action: str, target: str, reason: str | None = None) -> dict[str, Any]:
    token = _bot_token()
    payload = {
        "action": action,
        "target": target,
        "reason": reason or None,
        "owner_telegram_id": _owner_id(),
    }
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    timestamp = str(int(time.time()))
    signature = hmac.new(
        token.encode("utf-8"),
        timestamp.encode("utf-8") + b"\n" + body,
        hashlib.sha256,
    ).hexdigest()

    request = urllib.request.Request(
        f"{_api_base()}/api/internal/user-ban",
        data=body,
        headers={
            "Content-Type": "application/json",
            "X-Nyan-Timestamp": timestamp,
            "X-Nyan-Signature": signature,
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
    except urllib.error.HTTPError as exc:
        raise BanBotError(_http_detail(exc)) from exc
    except (urllib.error.URLError, TimeoutError, socket.timeout, ConnectionError) as exc:
        raise BanBotError("Nyan Wallet API сейчас недоступен") from exc

    if len(raw) > MAX_RESPONSE_BYTES:
        raise BanBotError("API вернул слишком большой ответ")
    try:
        data = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise BanBotError("API вернул некорректный ответ") from exc
    if not isinstance(data, dict) or data.get("ok") is not True:
        raise BanBotError("API не подтвердил операцию")
    return data


async def _require_owner(update: Update) -> bool:
    user = update.effective_user
    message = update.effective_message
    if user is None or message is None:
        return False
    if user.id != _owner_id():
        await message.reply_text("Команда доступна только владельцу Nyan Wallet.")
        return False
    return True


async def _ensure_owner_command_menu(application: Application) -> None:
    scope = BotCommandScopeChat(chat_id=_owner_id())
    try:
        default_commands = await application.bot.get_my_commands()
        owner_commands = await application.bot.get_my_commands(scope=scope)
        merged: dict[str, BotCommand] = {
            command.command: command
            for command in [*default_commands, *owner_commands]
        }
        merged["ban"] = BotCommand(command="ban", description="Заблокировать пользователя")
        merged["unban"] = BotCommand(command="unban", description="Разблокировать пользователя")
        await application.bot.set_my_commands(
            list(merged.values())[:100],
            scope=scope,
        )
    except TelegramError:
        logger.exception("ban_owner_command_menu_failed")


async def ban_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if message is None:
        raise ApplicationHandlerStop
    if not await _require_owner(update):
        raise ApplicationHandlerStop

    args = list(context.args or [])
    if not args:
        await message.reply_text(
            "Использование:\n"
            "/ban @username [причина]\n"
            "/ban Telegram_ID [причина]\n\n"
            "Причину можно не указывать."
        )
        raise ApplicationHandlerStop

    target = args[0].strip()
    reason = " ".join(args[1:]).strip() or None
    if reason and len(reason) > MAX_REASON_LENGTH:
        await message.reply_text(f"Причина не должна превышать {MAX_REASON_LENGTH} символов.")
        raise ApplicationHandlerStop

    try:
        data = await asyncio.to_thread(signed_action, "ban", target, reason)
    except BanBotError as exc:
        await message.reply_text(f"Не удалось заблокировать: {exc}")
        raise ApplicationHandlerStop
    except Exception:
        logger.exception("ban_command_failed target=%s", target)
        await message.reply_text("Не удалось заблокировать пользователя: внутренняя ошибка.")
        raise ApplicationHandlerStop

    result = data.get("ban") or {}
    username = result.get("username")
    display = f"@{username}" if username else str(result.get("telegram_id") or target)
    text = f"🚫 {display} заблокирован в Nyan Wallet."
    if reason:
        text += f"\nПричина: {reason}"
    await message.reply_text(text)


async def unban_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if message is None or not await _require_owner(update):
        return

    args = list(context.args or [])
    if not args:
        await message.reply_text(
            "Использование:\n"
            "/unban @username\n"
            "/unban Telegram_ID"
        )
        raise ApplicationHandlerStop

    target = args[0].strip()

    try:
        data = await asyncio.to_thread(signed_action, "unban", target, None)
    except BanBotError as exc:
        await message.reply_text(f"Не удалось разблокировать: {exc}")
        raise ApplicationHandlerStop
    except Exception:
        logger.exception("unban_command_failed target=%s", target)
        await message.reply_text("Не удалось разблокировать пользователя: внутренняя ошибка.")
        raise ApplicationHandlerStop

    result = data.get("unban") or {}
    username = result.get("username")
    display = f"@{username}" if username else str(result.get("telegram_id") or target)
    if result.get("was_blocked") is False:
        await message.reply_text(f"{display} и так не был заблокирован.")
    else:
        await message.reply_text(f"✅ {display} разблокирован в Nyan Wallet.")
    raise ApplicationHandlerStop


def register_ban_handlers(app: Application) -> None:
    global _menu_hook_installed

    # Negative group makes admin commands run before generic text/catch-all handlers.
    app.add_handler(CommandHandler("ban", ban_command), group=-100)
    app.add_handler(CommandHandler("unban", unban_command), group=-100)

    if not _menu_hook_installed:
        previous_post_init = getattr(app, "post_init", None)

        async def _ban_post_init(application: Application) -> None:
            if previous_post_init is not None:
                await previous_post_init(application)
            await _ensure_owner_command_menu(application)

        try:
            app.post_init = _ban_post_init
            _menu_hook_installed = True
        except Exception:
            logger.exception("ban_post_init_hook_failed")
