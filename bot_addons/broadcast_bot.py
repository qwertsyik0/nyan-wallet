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
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any, Literal

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, WebAppInfo
from telegram.error import BadRequest, Forbidden, NetworkError, RetryAfter, TelegramError
from telegram.ext import (
    Application,
    ApplicationHandlerStop,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

logger = logging.getLogger("nyan_wallet.broadcast_bot")

DEFAULT_API_BASE = "https://nyan-wallet-api.onrender.com"
DEFAULT_OWNER_ID = 6289461565
PAGE_SIZE = 500
HTTP_TIMEOUT_SECONDS = 12.0
MAX_HTTP_RESPONSE_BYTES = 256 * 1024
SEND_DELAY_SECONDS = 0.055
NETWORK_RETRIES = 3

Audience = Literal["all", "active_7d", "active_30d"]
AUDIENCE_LABELS: dict[Audience, str] = {
    "all": "Все пользователи",
    "active_7d": "Активные 7 дней",
    "active_30d": "Активные 30 дней",
}
AUDIENCE_CYCLE: dict[Audience, Audience] = {
    "all": "active_7d",
    "active_7d": "active_30d",
    "active_30d": "all",
}


class BroadcastBotError(RuntimeError):
    pass


@dataclass(slots=True)
class ButtonSpec:
    text: str
    url: str
    kind: Literal["url", "web_app"]
    row: int


@dataclass(slots=True)
class BroadcastDraft:
    owner_id: int
    mode: str = "awaiting_content"
    source_chat_id: int | None = None
    source_message_ids: list[int] = field(default_factory=list)
    source_markup: InlineKeyboardMarkup | None = None
    keep_source_markup: bool = True
    media_group_id: str | None = None
    album_generation: int = 0
    buttons: list[ButtonSpec] = field(default_factory=list)
    current_row: int = 0
    audience: Audience = "all"


@dataclass(frozen=True, slots=True)
class BroadcastSnapshot:
    source_chat_id: int
    source_message_ids: tuple[int, ...]
    source_markup: InlineKeyboardMarkup | None
    keep_source_markup: bool
    buttons: tuple[ButtonSpec, ...]
    audience: Audience


@dataclass(slots=True)
class BroadcastJob:
    job_id: str
    owner_id: int
    audience: Audience
    total: int = 0
    processed: int = 0
    sent: int = 0
    blocked: int = 0
    failed: int = 0
    started_at: float = field(default_factory=time.monotonic)
    cancel_event: asyncio.Event = field(default_factory=asyncio.Event)
    progress_message_id: int | None = None


_drafts: dict[int, BroadcastDraft] = {}
_active_job: BroadcastJob | None = None


def _owner_id() -> int:
    raw = os.getenv("OWNER_TELEGRAM_ID", str(DEFAULT_OWNER_ID)).strip()
    try:
        value = int(raw)
    except ValueError as exc:
        raise BroadcastBotError("OWNER_TELEGRAM_ID должен быть положительным числом") from exc
    if value <= 0:
        raise BroadcastBotError("OWNER_TELEGRAM_ID должен быть положительным числом")
    return value


def _api_base() -> str:
    value = os.getenv("NYAN_WALLET_API", DEFAULT_API_BASE).strip().rstrip("/")
    parsed = urllib.parse.urlparse(value)
    if parsed.scheme not in {"https", "http"} or not parsed.netloc:
        raise BroadcastBotError("NYAN_WALLET_API содержит некорректный URL")
    if parsed.scheme != "https" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise BroadcastBotError("NYAN_WALLET_API должен использовать HTTPS")
    return value


def _bot_token() -> str:
    token = os.getenv("BOT_TOKEN", "").strip()
    if not token:
        raise BroadcastBotError("BOT_TOKEN отсутствует в окружении")
    return token


def _signed_json_request(payload: dict[str, Any]) -> dict[str, Any]:
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    timestamp = str(int(time.time()))
    signature = hmac.new(
        _bot_token().encode("utf-8"),
        timestamp.encode("utf-8") + b"\n" + body,
        hashlib.sha256,
    ).hexdigest()
    request = urllib.request.Request(
        f"{_api_base()}/api/internal/broadcast/recipients",
        data=body,
        headers={
            "Content-Type": "application/json",
            "X-Nyan-Timestamp": timestamp,
            "X-Nyan-Signature": signature,
        },
        method="POST",
    )

    last_error: BaseException | None = None
    for attempt in range(1, 5):
        try:
            with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
                raw = response.read(MAX_HTTP_RESPONSE_BYTES + 1)
            if len(raw) > MAX_HTTP_RESPONSE_BYTES:
                raise BroadcastBotError("API вернул слишком большой ответ")
            data = json.loads(raw.decode("utf-8"))
            if not isinstance(data, dict) or data.get("ok") is not True:
                raise BroadcastBotError("API не подтвердил список получателей")
            return data
        except urllib.error.HTTPError as exc:
            last_error = exc
            try:
                raw_detail = exc.read(4096).decode("utf-8", errors="replace")
                parsed_detail = json.loads(raw_detail)
                detail = str(parsed_detail.get("detail") or f"HTTP {exc.code}")
            except Exception:
                detail = f"HTTP {exc.code}"
            if exc.code not in {429, 502, 503, 504} or attempt == 4:
                raise BroadcastBotError(f"Не удалось получить получателей: {detail}") from exc
            retry_after = exc.headers.get("Retry-After") if exc.headers else None
            try:
                delay = float(retry_after) if retry_after else 0.0
            except ValueError:
                delay = 0.0
            time.sleep(delay if delay > 0 else min(0.7 * (2 ** (attempt - 1)) + random.random() * 0.2, 5.0))
        except (urllib.error.URLError, TimeoutError, socket.timeout, ConnectionError) as exc:
            last_error = exc
            if attempt == 4:
                raise BroadcastBotError("API списка получателей временно недоступен") from exc
            time.sleep(min(0.7 * (2 ** (attempt - 1)) + random.random() * 0.2, 5.0))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise BroadcastBotError("API вернул некорректный ответ") from exc

    raise BroadcastBotError("Не удалось получить список получателей") from last_error


def _fetch_recipient_page(
    *,
    owner_id: int,
    audience: Audience,
    after_telegram_id: int,
) -> tuple[list[int], int, bool]:
    data = _signed_json_request(
        {
            "owner_telegram_id": owner_id,
            "audience": audience,
            "after_telegram_id": after_telegram_id,
            "limit": PAGE_SIZE,
        }
    )
    raw = data.get("recipients")
    if not isinstance(raw, list) or not all(isinstance(item, int) and item > 0 for item in raw):
        raise BroadcastBotError("API вернул некорректный список получателей")
    next_after = data.get("next_after_telegram_id")
    has_more = data.get("has_more")
    if not isinstance(next_after, int) or next_after < 0 or not isinstance(has_more, bool):
        raise BroadcastBotError("API вернул некорректную пагинацию")
    return raw, next_after, has_more


async def _all_recipients(owner_id: int, audience: Audience) -> list[int]:
    recipients: list[int] = []
    after = 0
    seen: set[int] = set()

    while True:
        page, next_after, has_more = await asyncio.to_thread(
            _fetch_recipient_page,
            owner_id=owner_id,
            audience=audience,
            after_telegram_id=after,
        )
        recipients.extend(page)
        if not has_more:
            return recipients
        if next_after <= after or next_after in seen:
            raise BroadcastBotError("API списка получателей вернул зацикленную пагинацию")
        seen.add(next_after)
        after = next_after


def _result_markup(draft: BroadcastDraft | BroadcastSnapshot) -> InlineKeyboardMarkup | None:
    rows: list[list[InlineKeyboardButton]] = []
    if draft.keep_source_markup and draft.source_markup is not None:
        rows.extend([list(row) for row in draft.source_markup.inline_keyboard])

    grouped: dict[int, list[InlineKeyboardButton]] = {}
    for spec in draft.buttons:
        if spec.kind == "web_app":
            button = InlineKeyboardButton(spec.text, web_app=WebAppInfo(url=spec.url))
        else:
            button = InlineKeyboardButton(spec.text, url=spec.url)
        grouped.setdefault(spec.row, []).append(button)
    for row in sorted(grouped):
        rows.append(grouped[row])
    return InlineKeyboardMarkup(rows) if rows else None


def _source_button_count(markup: InlineKeyboardMarkup | None) -> int:
    return sum(len(row) for row in markup.inline_keyboard) if markup else 0


def _menu_text(draft: BroadcastDraft) -> str:
    source_count = _source_button_count(draft.source_markup) if draft.keep_source_markup else 0
    return (
        "Черновик рассылки готов.\n\n"
        f"Сообщений в блоке: {len(draft.source_message_ids)}\n"
        f"Кнопок исходника: {source_count}\n"
        f"Добавлено кнопок: {len(draft.buttons)}\n"
        f"Аудитория: {AUDIENCE_LABELS[draft.audience]}\n\n"
        "Можно добавить URL/Mini App кнопки, посмотреть предпросмотр или запустить рассылку."
    )


def _menu_markup(draft: BroadcastDraft) -> InlineKeyboardMarkup:
    source_count = _source_button_count(draft.source_markup)
    source_state = "вкл" if draft.keep_source_markup else "выкл"
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("🌐 URL-кнопка", callback_data="bc:add_url"),
                InlineKeyboardButton("📱 Mini App", callback_data="bc:add_webapp"),
            ],
            [
                InlineKeyboardButton("↩️ Новая строка", callback_data="bc:new_row"),
                InlineKeyboardButton("🗑 Мои кнопки", callback_data="bc:clear_buttons"),
            ],
            [
                InlineKeyboardButton(
                    f"Кнопки исходника: {source_count} · {source_state}",
                    callback_data="bc:toggle_source",
                )
            ],
            [
                InlineKeyboardButton(
                    f"👥 {AUDIENCE_LABELS[draft.audience]}",
                    callback_data="bc:audience",
                )
            ],
            [
                InlineKeyboardButton("👁 Предпросмотр", callback_data="bc:preview"),
                InlineKeyboardButton("🚀 Начать", callback_data="bc:start"),
            ],
            [InlineKeyboardButton("✖ Отменить черновик", callback_data="bc:cancel_draft")],
        ]
    )


async def _copy_source(*, bot, chat_id: int, snapshot: BroadcastDraft | BroadcastSnapshot) -> None:
    if snapshot.source_chat_id is None or not snapshot.source_message_ids:
        raise BroadcastBotError("Источник рассылки не выбран")

    ids = list(snapshot.source_message_ids)
    markup = _result_markup(snapshot)

    if len(ids) == 1:
        await bot.copy_message(
            chat_id=chat_id,
            from_chat_id=snapshot.source_chat_id,
            message_id=ids[0],
            reply_markup=markup,
        )
        return

    if hasattr(bot, "copy_messages"):
        copied = await bot.copy_messages(
            chat_id=chat_id,
            from_chat_id=snapshot.source_chat_id,
            message_ids=ids,
        )
        if markup and copied:
            await bot.edit_message_reply_markup(
                chat_id=chat_id,
                message_id=copied[-1].message_id,
                reply_markup=markup,
            )
        return

    for index, message_id in enumerate(ids):
        await bot.copy_message(
            chat_id=chat_id,
            from_chat_id=snapshot.source_chat_id,
            message_id=message_id,
            reply_markup=markup if index == len(ids) - 1 else None,
        )


async def _show_menu(bot, owner_id: int, draft: BroadcastDraft) -> None:
    await bot.send_message(
        chat_id=owner_id,
        text=_menu_text(draft),
        reply_markup=_menu_markup(draft),
    )


async def _preview(bot, owner_id: int, draft: BroadcastDraft) -> None:
    try:
        await _copy_source(bot=bot, chat_id=owner_id, snapshot=draft)
    except TelegramError as exc:
        raise BroadcastBotError(f"Telegram не смог скопировать этот тип сообщения: {exc}") from exc


async def _finalize_album(application: Application, owner_id: int, generation: int) -> None:
    await asyncio.sleep(1.2)
    draft = _drafts.get(owner_id)
    if draft is None or draft.mode != "awaiting_content" or draft.album_generation != generation:
        return
    if not draft.source_message_ids:
        return

    draft.mode = "ready"
    try:
        await _preview(application.bot, owner_id, draft)
    except BroadcastBotError as exc:
        _drafts.pop(owner_id, None)
        await application.bot.send_message(chat_id=owner_id, text=f"Не удалось подготовить альбом: {exc}")
        return
    await _show_menu(application.bot, owner_id, draft)


async def broadcast_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    message = update.effective_message
    if user is None or message is None:
        return
    if user.id != _owner_id():
        return

    draft = BroadcastDraft(owner_id=user.id)
    _drafts[user.id] = draft
    replied = message.reply_to_message

    if replied is not None:
        if replied.media_group_id:
            await message.reply_text(
                "Это часть альбома. Используйте /broadcast без ответа, затем пришлите альбом целиком."
            )
            raise ApplicationHandlerStop
        draft.source_chat_id = replied.chat_id
        draft.source_message_ids = [replied.message_id]
        draft.source_markup = replied.reply_markup
        draft.mode = "ready"
        try:
            await _preview(context.bot, user.id, draft)
        except BroadcastBotError as exc:
            _drafts.pop(user.id, None)
            await message.reply_text(str(exc))
            raise ApplicationHandlerStop
        await _show_menu(context.bot, user.id, draft)
        raise ApplicationHandlerStop

    await message.reply_text(
        "Режим рассылки включён.\n\n"
        "Пришлите сообщение, фото, видео, GIF, документ, голосовое, кружок, стикер "
        "или альбом. Форматирование, spoiler и Premium custom emoji сохраняются "
        "через серверное копирование Telegram.\n\n"
        "После этого я покажу предпросмотр и дам добавить URL или Mini App кнопки."
    )
    raise ApplicationHandlerStop


def _parse_button(text: str, *, kind: Literal["url", "web_app"]) -> ButtonSpec:
    if "|" not in text:
        raise BroadcastBotError("Формат: Текст кнопки | https://ссылка")
    label, raw_url = (part.strip() for part in text.split("|", 1))
    if not label or not raw_url:
        raise BroadcastBotError("Текст кнопки и ссылка обязательны")
    if len(label) > 64:
        raise BroadcastBotError("Текст кнопки должен быть не длиннее 64 символов")
    if len(raw_url) > 2048:
        raise BroadcastBotError("Ссылка слишком длинная")

    parsed = urllib.parse.urlparse(raw_url)
    if kind == "web_app":
        if parsed.scheme != "https" or not parsed.netloc:
            raise BroadcastBotError("Mini App кнопка должна вести на HTTPS URL")
    else:
        if parsed.scheme not in {"https", "http", "tg"}:
            raise BroadcastBotError("URL-кнопка должна использовать https://, http:// или tg://")
        if parsed.scheme in {"https", "http"} and not parsed.netloc:
            raise BroadcastBotError("Некорректная ссылка")

    return ButtonSpec(text=label, url=raw_url, kind=kind, row=0)


async def broadcast_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    message = update.effective_message
    if user is None or message is None or user.id != _owner_id():
        return

    draft = _drafts.get(user.id)
    if draft is None:
        return

    if draft.mode in {"awaiting_button_url", "awaiting_button_webapp"}:
        if not message.text:
            await message.reply_text("Для кнопки пришлите текст: Название | https://ссылка")
            raise ApplicationHandlerStop
        kind: Literal["url", "web_app"] = "web_app" if draft.mode == "awaiting_button_webapp" else "url"
        try:
            spec = _parse_button(message.text, kind=kind)
        except BroadcastBotError as exc:
            await message.reply_text(str(exc))
            raise ApplicationHandlerStop
        spec.row = draft.current_row
        draft.buttons.append(spec)
        draft.mode = "ready"
        await message.reply_text(f"Кнопка «{spec.text}» добавлена.")
        await _show_menu(context.bot, user.id, draft)
        raise ApplicationHandlerStop

    if draft.mode != "awaiting_content":
        return

    if message.media_group_id:
        if draft.media_group_id not in {None, message.media_group_id}:
            await message.reply_text("Сначала дождитесь обработки предыдущего альбома.")
            raise ApplicationHandlerStop
        draft.media_group_id = message.media_group_id
        draft.source_chat_id = message.chat_id
        if message.message_id not in draft.source_message_ids:
            draft.source_message_ids.append(message.message_id)
        if message.reply_markup is not None:
            draft.source_markup = message.reply_markup
        draft.album_generation += 1
        context.application.create_task(
            _finalize_album(context.application, user.id, draft.album_generation)
        )
        raise ApplicationHandlerStop

    draft.source_chat_id = message.chat_id
    draft.source_message_ids = [message.message_id]
    draft.source_markup = message.reply_markup
    draft.mode = "ready"
    try:
        await _preview(context.bot, user.id, draft)
    except BroadcastBotError as exc:
        _drafts.pop(user.id, None)
        await message.reply_text(str(exc))
        raise ApplicationHandlerStop
    await _show_menu(context.bot, user.id, draft)
    raise ApplicationHandlerStop


def _snapshot(draft: BroadcastDraft) -> BroadcastSnapshot:
    if draft.source_chat_id is None or not draft.source_message_ids:
        raise BroadcastBotError("Сначала выберите сообщение для рассылки")
    return BroadcastSnapshot(
        source_chat_id=draft.source_chat_id,
        source_message_ids=tuple(draft.source_message_ids),
        source_markup=draft.source_markup,
        keep_source_markup=draft.keep_source_markup,
        buttons=tuple(
            ButtonSpec(text=item.text, url=item.url, kind=item.kind, row=item.row)
            for item in draft.buttons
        ),
        audience=draft.audience,
    )


def _retry_seconds(exc: RetryAfter) -> float:
    value = exc.retry_after
    if isinstance(value, timedelta):
        return max(0.0, value.total_seconds())
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        return 1.0


async def _deliver_one(bot, recipient: int, snapshot: BroadcastSnapshot) -> str:
    for attempt in range(1, NETWORK_RETRIES + 1):
        try:
            await _copy_source(bot=bot, chat_id=recipient, snapshot=snapshot)
            return "sent"
        except RetryAfter as exc:
            await asyncio.sleep(_retry_seconds(exc) + 0.25)
        except Forbidden:
            return "blocked"
        except BadRequest as exc:
            lowered = str(exc).lower()
            if "blocked" in lowered or "chat not found" in lowered or "user is deactivated" in lowered:
                return "blocked"
            logger.warning("broadcast_bad_request recipient=%s error=%s", recipient, exc)
            return "failed"
        except NetworkError as exc:
            if attempt == NETWORK_RETRIES:
                logger.warning("broadcast_network_failed recipient=%s error=%s", recipient, exc)
                return "failed"
            await asyncio.sleep(0.6 * attempt)
        except TelegramError as exc:
            logger.warning("broadcast_telegram_failed recipient=%s error=%s", recipient, exc)
            return "failed"
        except Exception:
            logger.exception("broadcast_unexpected_failed recipient=%s", recipient)
            return "failed"
    return "failed"


def _progress_text(job: BroadcastJob, *, finished: bool = False) -> str:
    elapsed = max(0.0, time.monotonic() - job.started_at)
    state = "Завершена" if finished else ("Останавливается" if job.cancel_event.is_set() else "Выполняется")
    return (
        f"Рассылка: {state}\n"
        f"Аудитория: {AUDIENCE_LABELS[job.audience]}\n"
        f"Обработано: {job.processed}/{job.total}\n"
        f"Доставлено: {job.sent}\n"
        f"Бот заблокирован/чат недоступен: {job.blocked}\n"
        f"Ошибок: {job.failed}\n"
        f"Время: {elapsed:.1f} сек."
    )


async def _update_progress(application: Application, job: BroadcastJob, *, finished: bool = False) -> None:
    markup = None
    if not finished and not job.cancel_event.is_set():
        markup = InlineKeyboardMarkup(
            [[InlineKeyboardButton("⛔ Остановить рассылку", callback_data="bc:cancel_job")]]
        )
    try:
        if job.progress_message_id is None:
            sent = await application.bot.send_message(
                chat_id=job.owner_id,
                text=_progress_text(job, finished=finished),
                reply_markup=markup,
            )
            job.progress_message_id = sent.message_id
        else:
            await application.bot.edit_message_text(
                chat_id=job.owner_id,
                message_id=job.progress_message_id,
                text=_progress_text(job, finished=finished),
                reply_markup=markup,
            )
    except BadRequest as exc:
        if "message is not modified" not in str(exc).lower():
            logger.warning("broadcast_progress_edit_failed error=%s", exc)
    except TelegramError as exc:
        logger.warning("broadcast_progress_failed error=%s", exc)


async def _run_broadcast(
    application: Application,
    job: BroadcastJob,
    snapshot: BroadcastSnapshot,
) -> None:
    global _active_job
    try:
        recipients = await _all_recipients(job.owner_id, job.audience)
        job.total = len(recipients)
        await _update_progress(application, job)
        last_progress = time.monotonic()

        for recipient in recipients:
            if job.cancel_event.is_set():
                break
            result = await _deliver_one(application.bot, recipient, snapshot)
            job.processed += 1
            if result == "sent":
                job.sent += 1
            elif result == "blocked":
                job.blocked += 1
            else:
                job.failed += 1

            now = time.monotonic()
            if job.processed % 20 == 0 or now - last_progress >= 3.0:
                await _update_progress(application, job)
                last_progress = now
            await asyncio.sleep(SEND_DELAY_SECONDS)

        await _update_progress(application, job, finished=True)
    except BroadcastBotError as exc:
        await application.bot.send_message(chat_id=job.owner_id, text=f"Рассылка остановлена: {exc}")
    except Exception:
        logger.exception("broadcast_job_failed job_id=%s", job.job_id)
        await application.bot.send_message(
            chat_id=job.owner_id,
            text="Рассылка остановлена из-за внутренней ошибки. Подробности записаны в лог.",
        )
    finally:
        if _active_job is job:
            _active_job = None


async def broadcast_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    global _active_job
    query = update.callback_query
    user = update.effective_user
    if query is None or user is None:
        return
    if user.id != _owner_id():
        await query.answer("Недоступно", show_alert=True)
        raise ApplicationHandlerStop

    action = (query.data or "").removeprefix("bc:")
    await query.answer()

    if action == "cancel_job":
        if _active_job is not None:
            _active_job.cancel_event.set()
            await _update_progress(context.application, _active_job)
        raise ApplicationHandlerStop

    draft = _drafts.get(user.id)
    if draft is None:
        await query.edit_message_text("Черновик уже закрыт. Используйте /broadcast.")
        raise ApplicationHandlerStop

    if action == "add_url":
        draft.mode = "awaiting_button_url"
        await context.bot.send_message(
            chat_id=user.id,
            text="Пришлите кнопку в формате:\nНазвание кнопки | https://example.com",
        )
    elif action == "add_webapp":
        draft.mode = "awaiting_button_webapp"
        await context.bot.send_message(
            chat_id=user.id,
            text=(
                "Пришлите Mini App кнопку в формате:\n"
                "Открыть Nyan Wallet | https://qwertsyik0.github.io/nyan-wallet/"
            ),
        )
    elif action == "new_row":
        draft.current_row += 1
        await query.edit_message_text(
            _menu_text(draft) + "\n\nСледующая кнопка будет на новой строке.",
            reply_markup=_menu_markup(draft),
        )
    elif action == "clear_buttons":
        draft.buttons.clear()
        draft.current_row = 0
        await query.edit_message_text(_menu_text(draft), reply_markup=_menu_markup(draft))
    elif action == "toggle_source":
        draft.keep_source_markup = not draft.keep_source_markup
        await query.edit_message_text(_menu_text(draft), reply_markup=_menu_markup(draft))
    elif action == "audience":
        draft.audience = AUDIENCE_CYCLE[draft.audience]
        await query.edit_message_text(_menu_text(draft), reply_markup=_menu_markup(draft))
    elif action == "preview":
        try:
            await _preview(context.bot, user.id, draft)
        except BroadcastBotError as exc:
            await context.bot.send_message(chat_id=user.id, text=str(exc))
    elif action == "cancel_draft":
        _drafts.pop(user.id, None)
        await query.edit_message_text("Черновик рассылки удалён.")
    elif action == "start":
        if _active_job is not None:
            await context.bot.send_message(
                chat_id=user.id,
                text="Уже идёт другая рассылка. Дождитесь её завершения или используйте /broadcast_cancel.",
            )
            raise ApplicationHandlerStop
        try:
            snapshot = _snapshot(draft)
            await _preview(context.bot, user.id, draft)
        except BroadcastBotError as exc:
            await context.bot.send_message(chat_id=user.id, text=str(exc))
            raise ApplicationHandlerStop

        job = BroadcastJob(
            job_id=f"{int(time.time())}-{user.id}",
            owner_id=user.id,
            audience=draft.audience,
        )
        _active_job = job
        _drafts.pop(user.id, None)
        await query.edit_message_text(
            "Рассылка поставлена в очередь. Получаю актуальный список пользователей."
        )
        context.application.create_task(_run_broadcast(context.application, job, snapshot))

    raise ApplicationHandlerStop


async def broadcast_cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    global _active_job
    user = update.effective_user
    message = update.effective_message
    if user is None or message is None or user.id != _owner_id():
        return
    if _active_job is None:
        await message.reply_text("Активной рассылки сейчас нет.")
    else:
        _active_job.cancel_event.set()
        await message.reply_text("Остановка запрошена. Уже доставленные сообщения не удаляются.")
    raise ApplicationHandlerStop


async def broadcast_status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    message = update.effective_message
    if user is None or message is None or user.id != _owner_id():
        return
    if _active_job is None:
        await message.reply_text("Активной рассылки сейчас нет.")
    else:
        await message.reply_text(_progress_text(_active_job))
    raise ApplicationHandlerStop


def register_broadcast_handlers(app: Application) -> None:
    app.add_handler(CommandHandler("broadcast", broadcast_command), group=-20)
    app.add_handler(CommandHandler("broadcast_cancel", broadcast_cancel_command), group=-20)
    app.add_handler(CommandHandler("broadcast_status", broadcast_status_command), group=-20)
    app.add_handler(CallbackQueryHandler(broadcast_callback, pattern=r"^bc:"), group=-20)
    app.add_handler(
        MessageHandler(filters.ALL & ~filters.COMMAND, broadcast_message_handler),
        group=-20,
    )
