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
from typing import Any, Mapping
from urllib.parse import urlparse

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

logger = logging.getLogger("nyan_wallet.maintenance_bot")

DEFAULT_API_BASE = "https://nyan-wallet-api.onrender.com"
DEFAULT_OWNER_TELEGRAM_ID = 6289461565
DEFAULT_TITLE = "Nyan Wallet становится лучше"
DEFAULT_MESSAGE = (
    "Сейчас мы проводим технические работы: добавляем новые функции, "
    "улучшаем стабильность и готовим обновления для вас. "
    "Кошелёк скоро снова будет доступен в обычном режиме."
)

MAX_CUSTOM_MESSAGE_LENGTH = 800
MAX_RESPONSE_BYTES = 64 * 1024
REQUEST_TIMEOUT_SECONDS = 10.0
RETRYABLE_HTTP_CODES = frozenset({429, 502, 503, 504})


class MaintenanceBotError(RuntimeError):
    """Expected operational failure while talking to the Nyan Wallet API."""


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    attempts: int = 5
    base_delay_seconds: float = 0.75
    max_delay_seconds: float = 6.0
    jitter_seconds: float = 0.25

    def delay_for(self, attempt_index: int) -> float:
        exponential = self.base_delay_seconds * (2 ** max(0, attempt_index - 1))
        return min(exponential, self.max_delay_seconds) + random.uniform(0.0, self.jitter_seconds)


RETRY_POLICY = RetryPolicy()


def _parse_owner_id(raw: str | None) -> int:
    value = (raw or str(DEFAULT_OWNER_TELEGRAM_ID)).strip()
    try:
        owner_id = int(value)
    except ValueError as exc:
        raise RuntimeError("OWNER_TELEGRAM_ID должен быть положительным целым числом") from exc

    if owner_id <= 0:
        raise RuntimeError("OWNER_TELEGRAM_ID должен быть положительным целым числом")
    return owner_id


def _normalize_api_base(raw: str | None) -> str:
    value = (raw or DEFAULT_API_BASE).strip().rstrip("/")
    parsed = urlparse(value)

    if parsed.scheme not in {"https", "http"} or not parsed.netloc:
        raise RuntimeError("NYAN_WALLET_API должен быть корректным HTTP(S) URL")

    if parsed.scheme != "https" and parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise RuntimeError("NYAN_WALLET_API должен использовать HTTPS вне локальной разработки")

    return value


API_BASE = _normalize_api_base(os.getenv("NYAN_WALLET_API"))
OWNER_TELEGRAM_ID = _parse_owner_id(os.getenv("OWNER_TELEGRAM_ID"))
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()


def _decode_json_object(raw: bytes, *, context: str) -> dict[str, Any]:
    if len(raw) > MAX_RESPONSE_BYTES:
        raise MaintenanceBotError(f"{context}: ответ API слишком большой")

    try:
        decoded = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise MaintenanceBotError(f"{context}: API вернул ответ не в UTF-8") from exc

    try:
        payload = json.loads(decoded)
    except json.JSONDecodeError as exc:
        raise MaintenanceBotError(f"{context}: API вернул некорректный JSON") from exc

    if not isinstance(payload, dict):
        raise MaintenanceBotError(f"{context}: ожидался JSON-объект")
    return payload


def _extract_http_error_detail(exc: urllib.error.HTTPError) -> str:
    try:
        raw = exc.read(MAX_RESPONSE_BYTES + 1)
    except Exception:
        return f"HTTP {exc.code}"

    if len(raw) > MAX_RESPONSE_BYTES:
        return f"HTTP {exc.code}"

    try:
        payload = json.loads(raw.decode("utf-8", errors="strict"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        text = raw.decode("utf-8", errors="replace").strip()
        return text[:500] or f"HTTP {exc.code}"

    if isinstance(payload, dict):
        detail = payload.get("detail")
        if isinstance(detail, str) and detail.strip():
            return detail.strip()[:500]

    return f"HTTP {exc.code}"


def _retry_after_seconds(exc: urllib.error.HTTPError, *, attempt_index: int) -> float:
    raw = exc.headers.get("Retry-After") if exc.headers else None
    if raw:
        try:
            retry_after = float(raw)
        except ValueError:
            retry_after = 0.0
        if retry_after > 0:
            return min(retry_after, RETRY_POLICY.max_delay_seconds)
    return RETRY_POLICY.delay_for(attempt_index)


def _request_json(
    *,
    url: str,
    method: str,
    body: bytes | None = None,
    headers: Mapping[str, str] | None = None,
    context: str,
) -> dict[str, Any]:
    last_error: BaseException | None = None

    for attempt in range(1, RETRY_POLICY.attempts + 1):
        request = urllib.request.Request(
            url,
            data=body,
            headers=dict(headers or {}),
            method=method,
        )

        try:
            with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
                raw = response.read(MAX_RESPONSE_BYTES + 1)
                return _decode_json_object(raw, context=context)

        except urllib.error.HTTPError as exc:
            last_error = exc
            detail = _extract_http_error_detail(exc)

            if exc.code not in RETRYABLE_HTTP_CODES or attempt >= RETRY_POLICY.attempts:
                raise MaintenanceBotError(f"{context}: {detail}") from exc

            delay = _retry_after_seconds(exc, attempt_index=attempt)
            logger.warning(
                "maintenance_api_retry context=%s attempt=%d/%d http_status=%d delay=%.2fs",
                context,
                attempt,
                RETRY_POLICY.attempts,
                exc.code,
                delay,
            )
            time.sleep(delay)

        except (urllib.error.URLError, TimeoutError, socket.timeout, ConnectionError) as exc:
            last_error = exc

            if attempt >= RETRY_POLICY.attempts:
                raise MaintenanceBotError(
                    f"{context}: API временно недоступен после {RETRY_POLICY.attempts} попыток"
                ) from exc

            delay = RETRY_POLICY.delay_for(attempt)
            logger.warning(
                "maintenance_api_retry context=%s attempt=%d/%d network_error=%s delay=%.2fs",
                context,
                attempt,
                RETRY_POLICY.attempts,
                type(exc).__name__,
                delay,
            )
            time.sleep(delay)

        except OSError as exc:
            raise MaintenanceBotError(f"{context}: ошибка ввода-вывода: {exc}") from exc

    raise MaintenanceBotError(f"{context}: запрос не выполнен") from last_error


def _validate_state(payload: Mapping[str, Any], *, context: str) -> dict[str, Any]:
    state = payload.get("maintenance")
    if not isinstance(state, dict):
        raise MaintenanceBotError(f"{context}: в ответе отсутствует maintenance")

    enabled = state.get("enabled")
    title = state.get("title")
    message = state.get("message")

    if not isinstance(enabled, bool):
        raise MaintenanceBotError(f"{context}: maintenance.enabled должен быть bool")
    if not isinstance(title, str) or not title.strip():
        raise MaintenanceBotError(f"{context}: maintenance.title должен быть непустой строкой")
    if not isinstance(message, str) or not message.strip():
        raise MaintenanceBotError(f"{context}: maintenance.message должен быть непустой строкой")

    return {
        "enabled": enabled,
        "title": title.strip(),
        "message": message.strip(),
        "updated_at": state.get("updated_at"),
    }


def fetch_status() -> dict[str, Any]:
    payload = _request_json(
        url=f"{API_BASE}/api/maintenance/status",
        method="GET",
        context="Не удалось получить статус",
    )

    if payload.get("ok") is not True:
        raise MaintenanceBotError("Не удалось получить статус: API не подтвердил запрос")

    return _validate_state(payload, context="Не удалось получить статус")


def signed_request(payload: Mapping[str, Any]) -> dict[str, Any]:
    if not BOT_TOKEN:
        raise MaintenanceBotError("BOT_TOKEN отсутствует")

    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    timestamp = str(int(time.time()))
    signature = hmac.new(
        BOT_TOKEN.encode("utf-8"),
        timestamp.encode("utf-8") + b"\n" + body,
        hashlib.sha256,
    ).hexdigest()

    response = _request_json(
        url=f"{API_BASE}/api/internal/maintenance/toggle",
        method="POST",
        body=body,
        headers={
            "Content-Type": "application/json",
            "X-Nyan-Timestamp": timestamp,
            "X-Nyan-Signature": signature,
        },
        context="Не удалось изменить режим",
    )

    if response.get("ok") is not True:
        raise MaintenanceBotError("Не удалось изменить режим: API не подтвердил изменение")

    state = _validate_state(response, context="Не удалось изменить режим")
    return {"ok": True, "maintenance": state}


async def maintenance_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    message = update.effective_message

    if user is None or message is None:
        logger.warning("maintenance_command_without_effective_user_or_message")
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

    action = args[0].strip().lower()

    if action == "status":
        try:
            state = await asyncio.to_thread(fetch_status)
        except MaintenanceBotError as exc:
            logger.warning("maintenance_status_command_failed error=%s", exc)
            await message.reply_text(str(exc))
            return
        except Exception:
            logger.exception("maintenance_status_command_unexpected_error")
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

    if len(custom_message) > MAX_CUSTOM_MESSAGE_LENGTH:
        await message.reply_text(
            f"Текст режима обслуживания не должен превышать {MAX_CUSTOM_MESSAGE_LENGTH} символов."
        )
        return

    payload: dict[str, Any] = {
        "enabled": enabled,
        "title": DEFAULT_TITLE,
        "message": custom_message or DEFAULT_MESSAGE,
        "owner_telegram_id": OWNER_TELEGRAM_ID,
    }

    try:
        data = await asyncio.to_thread(signed_request, payload)
    except MaintenanceBotError as exc:
        logger.warning("maintenance_toggle_command_failed error=%s", exc)
        await message.reply_text(str(exc))
        return
    except Exception:
        logger.exception("maintenance_toggle_command_unexpected_error")
        await message.reply_text("Не удалось изменить режим: внутренняя ошибка бота.")
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
