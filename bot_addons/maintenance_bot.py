from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import os
import time
import urllib.error
import urllib.request

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

logger = logging.getLogger("nyan_wallet.maintenance_bot")

API_BASE = os.getenv("NYAN_WALLET_API", "https://nyan-wallet-api.onrender.com").rstrip("/")
OWNER_TELEGRAM_ID = int(os.getenv("OWNER_TELEGRAM_ID", "6289461565"))
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()

DEFAULT_TITLE = "Nyan Wallet становится лучше"
DEFAULT_MESSAGE = (
    "Сейчас мы проводим технические работы: добавляем новые функции, "
    "улучшаем стабильность и готовим обновления для вас. "
    "Кошелёк скоро снова будет доступен в обычном режиме."
)


class MaintenanceBotError(RuntimeError):
    pass


def signed_request(payload: dict) -> dict:
    if not BOT_TOKEN:
        raise MaintenanceBotError("BOT_TOKEN отсутствует")

    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    timestamp = str(int(time.time()))
    signature = hmac.new(
        BOT_TOKEN.encode("utf-8"),
        timestamp.encode("utf-8") + b"\n" + body,
        hashlib.sha256,
    ).hexdigest()

    request = urllib.request.Request(
        API_BASE + "/api/internal/maintenance/toggle",
        data=body,
        headers={
            "Content-Type": "application/json",
            "X-Nyan-Timestamp": timestamp,
            "X-Nyan-Signature": signature,
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            detail = json.loads(raw).get("detail")
        except Exception:
            detail = raw or f"HTTP {exc.code}"
        raise MaintenanceBotError(str(detail)) from exc
    except Exception as exc:
        raise MaintenanceBotError(f"Не удалось связаться с Nyan Wallet API: {exc}") from exc

    if not data.get("ok"):
        raise MaintenanceBotError("API не подтвердил изменение режима")
    return data


async def maintenance_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    message = update.effective_message
    if user is None or message is None:
        return

    if user.id != OWNER_TELEGRAM_ID:
        await message.reply_text("Команда доступна только владельцу Nyan Wallet.")
        return

    args = list(context.args or [])
    if not args:
        await message.reply_text(
            "Использование:\n"
            "/maintenance on [свой текст]\n"
            "/maintenance off\n"
            "/maintenance status"
        )
        return

    action = args[0].lower()

    if action == "status":
        def fetch_status() -> dict:
            request = urllib.request.Request(
                API_BASE + "/api/maintenance/status",
                method="GET",
            )
            with urllib.request.urlopen(request, timeout=10) as response:
                return json.loads(response.read().decode("utf-8"))

        try:
            data = await asyncio.to_thread(fetch_status)
            state = data.get("maintenance", {})
            status = "ВКЛЮЧЕН" if state.get("enabled") else "ВЫКЛЮЧЕН"
            await message.reply_text(
                f"Режим технических работ: {status}\n"
                f"Заголовок: {state.get('title') or DEFAULT_TITLE}\n"
                f"Текст: {state.get('message') or DEFAULT_MESSAGE}"
            )
        except Exception as exc:
            logger.exception("maintenance_status_command_failed")
            await message.reply_text(f"Не удалось получить статус: {exc}")
        return

    if action not in {"on", "off"}:
        await message.reply_text("Используйте /maintenance on, /maintenance off или /maintenance status.")
        return

    enabled = action == "on"
    custom_message = " ".join(args[1:]).strip() if enabled else ""
    if len(custom_message) > 800:
        await message.reply_text("Текст режима обслуживания не должен превышать 800 символов.")
        return

    payload = {
        "enabled": enabled,
        "title": DEFAULT_TITLE,
        "message": custom_message or DEFAULT_MESSAGE,
        "owner_telegram_id": OWNER_TELEGRAM_ID,
    }

    try:
        data = await asyncio.to_thread(signed_request, payload)
    except MaintenanceBotError as exc:
        logger.exception("maintenance_toggle_command_failed")
        await message.reply_text(f"Не удалось изменить режим: {exc}")
        return

    state = data["maintenance"]
    if enabled:
        await message.reply_text(
            "Технические работы включены.\n"
            "Обычные пользователи увидят страницу обслуживания.\n"
            "Для владельца Mini App продолжает работать в штатном режиме.\n\n"
            f"{state['message']}"
        )
    else:
        await message.reply_text(
            "Технические работы выключены. Nyan Wallet снова доступен всем пользователям."
        )


def register_maintenance_handlers(app: Application) -> None:
    app.add_handler(CommandHandler("maintenance", maintenance_command))
