from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import os
import random
import socket
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Mapping, TypedDict
from urllib.parse import urlparse

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

logger = logging.getLogger("nyan_wallet.maintenance_bot")

DEFAULT_API_BASE = "https://nyan-wallet-api.onrender.com"
DEFAULT_OWNER_ID = 6289461565
DEFAULT_TITLE = "Nyan Wallet становится лучше"
DEFAULT_MESSAGE = (
    "Сейчас мы проводим технические работы: добавляем новые функции, "
    "улучшаем стабильность и готовим обновления для вас. "
    "Кошелёк скоро снова будет доступен в обычном режиме."
)
MAX_MESSAGE_LENGTH = 800
MAX_RESPONSE_BYTES = 64 * 1024
TIMEOUT_SECONDS = 10.0
RETRYABLE_HTTP = frozenset({429, 502, 503, 504})


class MaintenanceBotError(RuntimeError):
    pass


class MaintenanceState(TypedDict):
    enabled: bool
    title: str
    message: str
    updated_at: str | None


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    attempts: int = 5
    base_delay: float = 0.75
    max_delay: float = 6.0
    jitter: float = 0.25

    def delay(self, attempt: int) -> float:
        base = min(self.base_delay * (2 ** max(0, attempt - 1)), self.max_delay)
        return base + random.uniform(0.0, self.jitter)


RETRY = RetryPolicy()


def _owner_id() -> int:
    raw = os.getenv("OWNER_TELEGRAM_ID", str(DEFAULT_OWNER_ID)).strip()
    try:
        value = int(raw)
    except ValueError as exc:
        raise MaintenanceBotError("OWNER_TELEGRAM_ID должен быть положительным числом") from exc
    if value <= 0:
        raise MaintenanceBotError("OWNER_TELEGRAM_ID должен быть положительным числом")
    return value


def _api_base() -> str:
    value = os.getenv("NYAN_WALLET_API", DEFAULT_API_BASE).strip().rstrip("/")
    parsed = urlparse(value)
    if parsed.scheme not in {"https", "http"} or not parsed.netloc:
        raise MaintenanceBotError("NYAN_WALLET_API содержит некорректный URL")
    if parsed.scheme != "https" and parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise MaintenanceBotError("NYAN_WALLET_API должен использовать HTTPS")
    return value


def _bot_token() -> str:
    token = os.getenv("BOT_TOKEN", "").strip()
    if not token:
        raise MaintenanceBotError("BOT_TOKEN отсутствует в окружении")
    return token


def _decode_json(raw: bytes, context: str) -> dict[str, Any]:
    if len(raw) > MAX_RESPONSE_BYTES:
        raise MaintenanceBotError(f"{context}: ответ API слишком большой")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MaintenanceBotError(f"{context}: API вернул некорректный JSON") from exc
    if not isinstance(value, dict):
        raise MaintenanceBotError(f"{context}: ожидался JSON-объект")
    return value


def _http_detail(exc: urllib.error.HTTPError) -> str:
    try:
        raw = exc.read(MAX_RESPONSE_BYTES + 1)
    except Exception:
        return f"HTTP {exc.code}"
    if len(raw) > MAX_RESPONSE_BYTES:
        return f"HTTP {exc.code}"
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        text = raw.decode("utf-8", errors="replace").strip()
        return text[:500] or f"HTTP {exc.code}"
    if isinstance(value, dict) and isinstance(value.get("detail"), str):
        detail = value["detail"].strip()
        if detail:
            return detail[:500]
    return f"HTTP {exc.code}"


def _retry_delay(exc: urllib.error.HTTPError, attempt: int) -> float:
    raw = exc.headers.get("Retry-After") if exc.headers else None
    if raw:
        try:
            value = float(raw)
        except ValueError:
            value = 0.0
        if value > 0:
            return min(value, RETRY.max_delay)
    return RETRY.delay(attempt)


def _request_json(
    *,
    url: str,
    method: str,
    context: str,
    body: bytes | None = None,
    headers: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    last_error: BaseException | None = None

    for attempt in range(1, RETRY.attempts + 1):
        request = urllib.request.Request(
            url,
            data=body,
            headers=dict(headers or {}),
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
                return _decode_json(response.read(MAX_RESPONSE_BYTES + 1), context)

        except urllib.error.HTTPError as exc:
            last_error = exc
            detail = _http_detail(exc)
            if exc.code not in RETRYABLE_HTTP or attempt == RETRY.attempts:
                raise MaintenanceBotError(f"{context}: {detail}") from exc
            delay = _retry_delay(exc, attempt)
            logger.warning(
                "maintenance_api_retry context=%s attempt=%d/%d status=%d delay=%.2fs",
                context, attempt, RETRY.attempts, exc.code, delay,
            )
            time.sleep(delay)

        except (urllib.error.URLError, TimeoutError, socket.timeout, ConnectionError) as exc:
            last_error = exc
            if attempt == RETRY.attempts:
                raise MaintenanceBotError(
                    f"{context}: API недоступен после {RETRY.attempts} попыток"
                ) from exc
            delay = RETRY.delay(attempt)
            logger.warning(
                "maintenance_api_retry context=%s attempt=%d/%d error=%s delay=%.2fs",
                context, attempt, RETRY.attempts, type(exc).__name__, delay,
            )
            time.sleep(delay)

        except OSError as exc:
            raise MaintenanceBotError(f"{context}: ошибка ввода-вывода: {exc}") from exc

    raise MaintenanceBotError(f"{context}: запрос не выполнен") from last_error


def _state(payload: Mapping[str, Any], context: str) -> MaintenanceState:
    raw = payload.get("maintenance")
    if not isinstance(raw, dict):
        raise MaintenanceBotError(f"{context}: отсутствует maintenance")

    enabled = raw.get("enabled")
    title = raw.get("title")
    message = raw.get("message")
    updated_at = raw.get("updated_at")

    if not isinstance(enabled, bool):
        raise MaintenanceBotError(f"{context}: enabled имеет неверный тип")
    if not isinstance(title, str) or not title.strip():
        raise MaintenanceBotError(f"{context}: title пуст или имеет неверный тип")
    if not isinstance(message, str) or not message.strip():
        raise MaintenanceBotError(f"{context}: message пуст или имеет неверный тип")
    if updated_at is not None and not isinstance(updated_at, str):
        raise MaintenanceBotError(f"{context}: updated_at имеет неверный тип")

    return {
        "enabled": enabled,
        "title": title.strip(),
        "message": message.strip(),
        "updated_at": updated_at,
    }


def fetch_status() -> MaintenanceState:
    context = "Не удалось получить статус"
    payload = _request_json(
        url=f"{_api_base()}/api/maintenance/status",
        method="GET",
        context=context,
    )
    if payload.get("ok") is not True:
        raise MaintenanceBotError(f"{context}: API не подтвердил запрос")
    return _state(payload, context)


def signed_request(payload: Mapping[str, Any]) -> MaintenanceState:
    context = "Не удалось изменить режим"
    token = _bot_token()
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    timestamp = str(int(time.time()))
    signature = hmac.new(
        token.encode("utf-8"),
        timestamp.encode("utf-8") + b"\n" + body,
        hashlib.sha256,
    ).hexdigest()

    response = _request_json(
        url=f"{_api_base()}/api/internal/maintenance/toggle",
        method="POST",
        context=context,
        body=body,
        headers={
            "Content-Type": "application/json",
            "X-Nyan-Timestamp": timestamp,
            "X-Nyan-Signature": signature,
        },
    )
    if response.get("ok") is not True:
        raise MaintenanceBotError(f"{context}: API не подтвердил изменение")
    return _state(response, context)


async def maintenance_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    message = update.effective_message
    if user is None or message is None:
        logger.warning("maintenance_command_missing_update_context")
        return

    try:
        owner_id = _owner_id()
    except MaintenanceBotError as exc:
        logger.error("maintenance_configuration_error error=%s", exc)
        await message.reply_text(f"Ошибка конфигурации maintenance: {exc}")
        return

    if user.id != owner_id:
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

    action = args[0].strip().lower()

    if action == "status":
        try:
            state = await asyncio.to_thread(fetch_status)
        except MaintenanceBotError as exc:
            logger.warning("maintenance_status_failed error=%s", exc)
            await message.reply_text(str(exc))
            return
        except Exception:
            logger.exception("maintenance_status_unexpected_error")
            await message.reply_text("Не удалось получить статус: внутренняя ошибка бота.")
            return

        status = "ВКЛЮЧЕН" if state["enabled"] else "ВЫКЛЮЧЕН"
        await message.reply_text(
            f"Режим технических работ: {status}\n"
            f"Заголовок: {state['title']}\n"
            f"Текст: {state['message']}"
        )
        return

    if action not in {"on", "off"}:
        await message.reply_text("Используйте /maintenance on, /maintenance off или /maintenance status.")
        return

    enabled = action == "on"
    custom_message = " ".join(args[1:]).strip() if enabled else ""
    if len(custom_message) > MAX_MESSAGE_LENGTH:
        await message.reply_text(
            f"Текст режима обслуживания не должен превышать {MAX_MESSAGE_LENGTH} символов."
        )
        return

    payload: dict[str, Any] = {
        "enabled": enabled,
        "title": DEFAULT_TITLE,
        "message": custom_message or DEFAULT_MESSAGE,
        "owner_telegram_id": owner_id,
    }

    try:
        state = await asyncio.to_thread(signed_request, payload)
    except MaintenanceBotError as exc:
        logger.warning("maintenance_toggle_failed error=%s", exc)
        await message.reply_text(str(exc))
        return
    except Exception:
        logger.exception("maintenance_toggle_unexpected_error")
        await message.reply_text("Не удалось изменить режим: внутренняя ошибка бота.")
        return

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
