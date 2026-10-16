from __future__ import annotations

import json
import os
import re
import urllib.parse
from dataclasses import replace
from pathlib import Path
from typing import Literal

from telegram import BotCommand, BotCommandScopeChat, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import BadRequest, Forbidden, NetworkError, RetryAfter, TelegramError
from telegram.ext import Application, ApplicationHandlerStop, CallbackQueryHandler, ChatMemberHandler, CommandHandler, ContextTypes, MessageHandler, filters

from broadcast_bot import BroadcastBotError, BroadcastDraft, ButtonSpec, _owner_id

DEFAULT_MINI_APP_URL = "https://qwertsyik0.github.io/nyan-wallet/"
ELECTIONS_MINI_APP_URL = "https://qwertsyik0.github.io/nyan-wallet/elections.html"
PROMO_SLUG_PATTERN = re.compile(r"^[a-z0-9_-]{2,48}$", re.IGNORECASE)
_channel_drafts: dict[int, BroadcastDraft] = {}
_channel_post_init_hook_installed = False
_channel_selected_targets: dict[int, int] = {}
CHANNEL_STATE_PATH = Path(
    os.getenv(
        "NYAN_CHANNEL_PUBLISH_STATE_FILE",
        str(Path(__file__).with_name("channel_publish_channels.json")),
    )
).expanduser()

CHANNEL_PENDING_PATH = Path(
    os.getenv(
        "NYAN_CHANNEL_PUBLISH_PENDING_FILE",
        str(Path(__file__).with_name("channel_publish_pending.json")),
    )
).expanduser()


def _load_pending_channel_add() -> set[int]:
    try:
        payload = json.loads(CHANNEL_PENDING_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, ValueError, TypeError):
        return set()
    values = payload.get("owners") if isinstance(payload, dict) else None
    if not isinstance(values, list):
        return set()
    result: set[int] = set()
    for value in values:
        try:
            result.add(int(value))
        except (TypeError, ValueError):
            pass
    return result


_pending_channel_add = _load_pending_channel_add()


def _save_pending_channel_add() -> None:
    try:
        CHANNEL_PENDING_PATH.parent.mkdir(parents=True, exist_ok=True)
        CHANNEL_PENDING_PATH.write_text(
            json.dumps({"owners": sorted(_pending_channel_add)}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError:
        pass


def _set_pending_channel_add(owner_id: int, enabled: bool) -> None:
    if enabled:
        _pending_channel_add.add(int(owner_id))
    else:
        _pending_channel_add.discard(int(owner_id))
    _save_pending_channel_add()


def _load_channel_registry() -> dict[int, dict[str, object]]:
    try:
        payload = json.loads(CHANNEL_STATE_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, ValueError, TypeError):
        return {}
    channels = payload.get("channels") if isinstance(payload, dict) else None
    if not isinstance(channels, list):
        return {}
    result: dict[int, dict[str, object]] = {}
    for item in channels:
        if not isinstance(item, dict):
            continue
        try:
            chat_id = int(item.get("id"))
        except (TypeError, ValueError):
            continue
        result[chat_id] = {
            "id": chat_id,
            "title": str(item.get("title") or "Канал"),
            "username": str(item.get("username") or ""),
        }
    return result


_channel_registry = _load_channel_registry()


def _save_channel_registry() -> None:
    try:
        CHANNEL_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        CHANNEL_STATE_PATH.write_text(
            json.dumps(
                {"channels": list(_channel_registry.values())},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
    except OSError:
        pass


def _remember_channel(chat) -> None:
    if chat is None or getattr(chat, "type", None) != "channel":
        return
    chat_id = int(chat.id)
    _channel_registry[chat_id] = {
        "id": chat_id,
        "title": str(getattr(chat, "title", None) or "Канал"),
        "username": str(getattr(chat, "username", None) or ""),
    }
    _save_channel_registry()


def _forget_channel(chat_id: int) -> None:
    if _channel_registry.pop(int(chat_id), None) is not None:
        _save_channel_registry()


def _channel_label(item: dict[str, object]) -> str:
    title = str(item.get("title") or "Канал").strip()
    username = str(item.get("username") or "").strip().lstrip("@")
    label = f"{title} · @{username}" if username else title
    return label[:56]


async def _channel_is_writable(bot, chat_id: int | str) -> tuple[bool, object | None]:
    try:
        chat = await bot.get_chat(chat_id)
        if getattr(chat, "type", None) != "channel":
            return False, chat
        me = await bot.get_me()
        member = await bot.get_chat_member(chat.id, me.id)
    except TelegramError:
        return False, None

    status = str(getattr(member, "status", ""))
    if status not in {"administrator", "creator"}:
        return False, chat
    can_post = getattr(member, "can_post_messages", None)
    if can_post is False:
        return False, chat
    return True, chat


async def _available_channels(bot) -> list[dict[str, object]]:
    candidates: list[int | str] = list(_channel_registry)
    try:
        configured = _configured_channel_id()
    except BroadcastBotError:
        configured = None
    if configured is not None and configured not in candidates:
        candidates.append(configured)

    available: list[dict[str, object]] = []
    seen: set[int] = set()
    for candidate in candidates:
        writable, chat = await _channel_is_writable(bot, candidate)
        if not writable or chat is None:
            try:
                numeric_id = int(candidate)
            except (TypeError, ValueError):
                numeric_id = None
            if numeric_id is not None:
                _forget_channel(numeric_id)
            continue
        _remember_channel(chat)
        chat_id = int(chat.id)
        if chat_id in seen:
            continue
        seen.add(chat_id)
        available.append(_channel_registry[chat_id])

    available.sort(key=lambda item: str(item.get("title") or "").casefold())
    return available


def _channel_picker_markup(channels: list[dict[str, object]]) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(f"📣 {_channel_label(item)}", callback_data=f"ch:select:{int(item['id'])}")]
        for item in channels
    ]
    rows.append(
        [
            InlineKeyboardButton("➕ Добавить канал", callback_data="ch:add_channel"),
            InlineKeyboardButton("🔄 Обновить", callback_data="ch:refresh_channels"),
        ]
    )
    rows.append([InlineKeyboardButton("✖ Отмена", callback_data="ch:cancel")])
    return InlineKeyboardMarkup(rows)


def _selected_channel_text(owner_id: int) -> str:
    chat_id = _channel_selected_targets.get(owner_id)
    item = _channel_registry.get(chat_id) if chat_id is not None else None
    return _channel_label(item) if item else "не выбран"


def _mini_app_base() -> str:
    value = os.getenv("MINI_APP_URL", DEFAULT_MINI_APP_URL).strip() or DEFAULT_MINI_APP_URL
    parsed = urllib.parse.urlparse(value)
    if parsed.scheme != "https" or not parsed.netloc:
        raise BroadcastBotError("MINI_APP_URL должен быть HTTPS URL")
    return value


def _promo_page_url(slug: str) -> str:
    normalized = slug.strip().lower().replace("_", "-")
    if not PROMO_SLUG_PATTERN.fullmatch(normalized):
        raise BroadcastBotError("Некорректный slug промо")
    base = _mini_app_base().rstrip("/") + "/"
    return f"{base}?promo={urllib.parse.quote(normalized, safe='-_')}"


def _configured_channel_id() -> int | str:
    raw = (
        os.getenv("TELEGRAM_CHANNEL_ID")
        or os.getenv("NYAN_TELEGRAM_CHANNEL_ID")
        or os.getenv("NYAN_CHANNEL_ID")
        or ""
    ).strip()
    if not raw:
        raise BroadcastBotError("TELEGRAM_CHANNEL_ID не настроен")
    if raw.startswith("@"):
        if not re.fullmatch(r"@[A-Za-z0-9_]{5,64}", raw):
            raise BroadcastBotError("TELEGRAM_CHANNEL_ID содержит некорректный @username канала")
        return raw
    try:
        value = int(raw)
    except ValueError as exc:
        raise BroadcastBotError("TELEGRAM_CHANNEL_ID должен быть числом или @username") from exc
    if value == 0:
        raise BroadcastBotError("TELEGRAM_CHANNEL_ID не может быть 0")
    return value


def _env_bot_username() -> str | None:
    raw = (os.getenv("NYAN_BOT_USERNAME") or os.getenv("BOT_USERNAME") or "").strip().lstrip("@")
    if not raw:
        return None
    if not re.fullmatch(r"[A-Za-z0-9_]{5,64}", raw):
        raise BroadcastBotError("NYAN_BOT_USERNAME содержит некорректное имя бота")
    return raw


async def _bot_username(bot) -> str | None:
    configured = _env_bot_username()
    if configured:
        return configured
    username = getattr(bot, "username", None)
    if isinstance(username, str) and username:
        return username.lstrip("@")
    try:
        me = await bot.get_me()
    except TelegramError:
        return None
    username = getattr(me, "username", None)
    return username.lstrip("@") if isinstance(username, str) and username else None


def _start_param_for_url(url: str) -> str:
    try:
        parsed = urllib.parse.urlparse(url)
        query = urllib.parse.parse_qs(parsed.query)

        # Preserve an explicitly requested Mini App start parameter.
        for key in ("startapp", "tgWebAppStartParam"):
            value = (query.get(key) or [""])[0].strip()
            if value and PROMO_SLUG_PATTERN.fullmatch(value):
                return value.lower().replace("-", "_")

        # Survey has its own standalone page, but must still be opened through
        # Telegram's Mini App deep link so initData is available for the reward.
        page = parsed.path.rstrip("/").lower()
        # These standalone pages must be launched through the MAIN Mini App,
        # so Telegram supplies signed initData for the recruitment/submission.
        page_routes = {
            "/wallet-survey.html": "survey",
            "/survey.html": "survey",
            "/suggestion-300.html": "suggestion_300",
            "/finance-apply.html": "finance_admin",
            "/finance-review.html": "finance_review",
            "/elections.html": "elections",
        }
        for suffix, start_param in page_routes.items():
            if page.endswith(suffix):
                return start_param

        for key in ("promo", "slug"):
            value = (query.get(key) or [""])[0]
            if value and PROMO_SLUG_PATTERN.fullmatch(value):
                return f"promo_{value.lower().replace('_', '-')}"
        path_match = re.search(r"/promo/([a-z0-9_-]{2,48})", parsed.path, re.IGNORECASE)
        if path_match:
            return f"promo_{path_match.group(1).lower().replace('_', '-')}"
    except Exception:
        pass
    return "wallet"


def _mini_app_deep_link(url: str, bot_username: str | None) -> str:
    if not bot_username:
        return url

    raw_start_param = _start_param_for_url(url)
    start_param = urllib.parse.quote(raw_start_param, safe="_-")

    # The configured named Mini App currently points at the legacy promo
    # screen. Standalone forms/review screens require the Main Mini App.
    if raw_start_param in {"survey", "suggestion_300", "finance_admin", "finance_review", "elections"}:
        return f"https://t.me/{bot_username}?startapp={start_param}"

    short_name = (os.getenv("NYAN_MINI_APP_SHORT_NAME") or os.getenv("TELEGRAM_WEBAPP_SHORT_NAME") or "").strip()
    if short_name:
        if not re.fullmatch(r"[A-Za-z0-9_]{3,64}", short_name):
            raise BroadcastBotError("NYAN_MINI_APP_SHORT_NAME содержит некорректное имя Mini App")
        return f"https://t.me/{bot_username}/{short_name}?startapp={start_param}"
    return f"https://t.me/{bot_username}?startapp={start_param}"


def _parse_channel_button(text: str, *, kind: Literal["url", "web_app"]) -> ButtonSpec:
    if "|" not in text:
        raise BroadcastBotError("Формат: Текст кнопки | https://ссылка")
    label, raw_url = (part.strip() for part in text.split("|", 1))
    if not label or not raw_url:
        raise BroadcastBotError("Текст кнопки и ссылка обязательны")
    if len(label) > 64:
        raise BroadcastBotError("Текст кнопки должен быть не длиннее 64 символов")

    if kind == "web_app" and raw_url.lower().startswith("promo:"):
        raw_url = _promo_page_url(raw_url.split(":", 1)[1])

    if len(raw_url) > 2048:
        raise BroadcastBotError("Ссылка слишком длинная")
    parsed = urllib.parse.urlparse(raw_url)
    if kind == "web_app":
        if parsed.scheme != "https" or not parsed.netloc:
            raise BroadcastBotError("Mini App кнопка должна вести на HTTPS URL или promo:slug")
    else:
        if parsed.scheme not in {"https", "http", "tg"}:
            raise BroadcastBotError("URL-кнопка должна использовать https://, http:// или tg://")
        if parsed.scheme in {"https", "http"} and not parsed.netloc:
            raise BroadcastBotError("Некорректная ссылка")
    return ButtonSpec(text=label, url=raw_url, kind=kind, row=0)


def _clone_source_button(button: InlineKeyboardButton, *, bot_username: str | None) -> InlineKeyboardButton:
    web_app = getattr(button, "web_app", None)
    if web_app is not None and getattr(web_app, "url", None):
        return InlineKeyboardButton(button.text, url=_mini_app_deep_link(web_app.url, bot_username))
    return button


def _channel_markup(draft: BroadcastDraft, *, bot_username: str | None) -> InlineKeyboardMarkup | None:
    rows: list[list[InlineKeyboardButton]] = []
    if draft.keep_source_markup and draft.source_markup is not None:
        for row in draft.source_markup.inline_keyboard:
            rows.append([_clone_source_button(button, bot_username=bot_username) for button in row])

    grouped: dict[int, list[InlineKeyboardButton]] = {}
    for spec in draft.buttons:
        if spec.kind == "web_app":
            button = InlineKeyboardButton(spec.text, url=_mini_app_deep_link(spec.url, bot_username))
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
        "Черновик публикации в канал готов.\n\n"
        f"Сообщений в блоке: {len(draft.source_message_ids)}\n"
        f"Кнопок исходника: {source_count}\n"
        f"Добавлено кнопок: {len(draft.buttons)}\n"
        f"Канал: {_selected_channel_text(draft.owner_id)}\n\n"
        "Можно добавить URL/Mini App кнопки, посмотреть предпросмотр или опубликовать после подтверждения."
    )


def _add_elections_button(draft: BroadcastDraft) -> bool:
    if any(spec.kind == "web_app" and spec.url == ELECTIONS_MINI_APP_URL for spec in draft.buttons):
        return False
    draft.buttons.append(ButtonSpec(
        text="🗳 Выборы", url=ELECTIONS_MINI_APP_URL,
        kind="web_app", row=draft.current_row,
    ))
    return True


def _menu_markup(draft: BroadcastDraft) -> InlineKeyboardMarkup:
    source_count = _source_button_count(draft.source_markup)
    source_state = "вкл" if draft.keep_source_markup else "выкл"
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("🌐 URL-кнопка", callback_data="ch:add_url"),
                InlineKeyboardButton("📱 Mini App", callback_data="ch:add_webapp"),
            ],
            [InlineKeyboardButton("🗳 Выборы", callback_data="ch:add_elections")],
            [
                InlineKeyboardButton("↩️ Новая строка", callback_data="ch:new_row"),
                InlineKeyboardButton("🗑 Мои кнопки", callback_data="ch:clear_buttons"),
            ],
            [InlineKeyboardButton(f"Кнопки исходника: {source_count} · {source_state}", callback_data="ch:toggle_source")],
            [
                InlineKeyboardButton("👁 Предпросмотр", callback_data="ch:preview"),
                InlineKeyboardButton("📣 Опубликовать", callback_data="ch:publish"),
            ],
            [InlineKeyboardButton("✖ Отмена", callback_data="ch:cancel")],
        ]
    )


def _confirm_markup() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("✅ Опубликовать", callback_data="ch:confirm_publish")],
            [
                InlineKeyboardButton("✏️ Изменить", callback_data="ch:edit"),
                InlineKeyboardButton("✖ Отмена", callback_data="ch:cancel"),
            ],
        ]
    )


async def _copy_to_chat(*, bot, chat_id: int | str, draft: BroadcastDraft, bot_username: str | None) -> None:
    if draft.source_chat_id is None or not draft.source_message_ids:
        raise BroadcastBotError("Источник публикации не выбран")
    ids = list(draft.source_message_ids)
    markup = _channel_markup(draft, bot_username=bot_username)

    if len(ids) == 1:
        await bot.copy_message(
            chat_id=chat_id,
            from_chat_id=draft.source_chat_id,
            message_id=ids[0],
            reply_markup=markup,
        )
        return

    if hasattr(bot, "copy_messages"):
        copied = await bot.copy_messages(
            chat_id=chat_id,
            from_chat_id=draft.source_chat_id,
            message_ids=ids,
        )
        if markup and copied:
            await bot.edit_message_reply_markup(chat_id=chat_id, message_id=copied[-1].message_id, reply_markup=markup)
        return

    for index, message_id in enumerate(ids):
        await bot.copy_message(
            chat_id=chat_id,
            from_chat_id=draft.source_chat_id,
            message_id=message_id,
            reply_markup=markup if index == len(ids) - 1 else None,
        )


async def _preview(context: ContextTypes.DEFAULT_TYPE, owner_id: int, draft: BroadcastDraft) -> None:
    username = await _bot_username(context.bot)
    await _copy_to_chat(bot=context.bot, chat_id=owner_id, draft=draft, bot_username=username)


async def _show_menu(context: ContextTypes.DEFAULT_TYPE, owner_id: int, draft: BroadcastDraft) -> None:
    await context.bot.send_message(chat_id=owner_id, text=_menu_text(draft), reply_markup=_menu_markup(draft))


async def _start_channel_draft(update: Update, context: ContextTypes.DEFAULT_TYPE, *, replied=None) -> None:
    user = update.effective_user
    message = update.effective_message
    if user is None or message is None or user.id != _owner_id():
        return

    channels = await _available_channels(context.bot)
    if not channels:
        await message.reply_text(
            "Не нашёл ни одного канала, где бот может публиковать. "
            "Добавьте бота администратором канала с правом публикации."
        )
        raise ApplicationHandlerStop

    draft = BroadcastDraft(owner_id=user.id)
    draft.mode = "awaiting_channel"
    _channel_drafts[user.id] = draft
    _channel_selected_targets.pop(user.id, None)

    if replied is not None:
        if replied.media_group_id:
            await message.reply_text("Это часть альбома. Используйте /channel_post без ответа, затем пришлите альбом целиком.")
            raise ApplicationHandlerStop
        draft.source_chat_id = replied.chat_id
        draft.source_message_ids = [replied.message_id]
        draft.source_markup = replied.reply_markup

    await message.reply_text(
        "Куда публикуем?",
        reply_markup=_channel_picker_markup(channels),
    )
    raise ApplicationHandlerStop


async def channel_post_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    await _start_channel_draft(update, context, replied=message.reply_to_message if message else None)


async def channel_add_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    message = update.effective_message
    if user is None or message is None or user.id != _owner_id():
        return

    draft = _channel_drafts.get(user.id) or BroadcastDraft(owner_id=user.id)
    draft.mode = "awaiting_channel_add"
    _channel_drafts[user.id] = draft
    _set_pending_channel_add(user.id, True)

    await message.reply_text(
        "Режим добавления канала включён. Отправьте @username, числовой ID "
        "или перешлите пост из нужного канала."
    )
    raise ApplicationHandlerStop


async def channel_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    message = update.effective_message
    if user is None or message is None or user.id != _owner_id():
        return

    draft = _channel_drafts.get(user.id)
    waiting_channel_add = user.id in _pending_channel_add or (draft is not None and draft.mode == "awaiting_channel_add")

    if waiting_channel_add:
        if draft is None:
            draft = BroadcastDraft(owner_id=user.id)
            draft.mode = "awaiting_channel_add"
            _channel_drafts[user.id] = draft
        candidate: int | str | None = None

        if message.forward_origin is not None:
            origin = message.forward_origin
            origin_chat = getattr(origin, "chat", None)
            if origin_chat is not None and getattr(origin_chat, "type", None) == "channel":
                candidate = int(origin_chat.id)

        if candidate is None and message.forward_from_chat is not None and message.forward_from_chat.type == "channel":
            candidate = int(message.forward_from_chat.id)

        if candidate is None and message.text:
            raw = message.text.strip()
            if raw.startswith("@") and re.fullmatch(r"@[A-Za-z0-9_]{5,64}", raw):
                candidate = raw
            elif re.fullmatch(r"-?\d{5,20}", raw):
                candidate = int(raw)

        if candidate is None:
            await message.reply_text(
                "Не смог определить канал. Перешлите сюда любой пост из канала "
                "или отправьте @username канала / его числовой ID."
            )
            raise ApplicationHandlerStop

        writable, chat = await _channel_is_writable(context.bot, candidate)
        if not writable or chat is None:
            await message.reply_text(
                "Канал найден, но бот не может публиковать туда. "
                "Проверьте, что бот добавлен администратором и у него включено право «Публиковать сообщения»."
            )
            raise ApplicationHandlerStop

        _remember_channel(chat)
        _set_pending_channel_add(user.id, False)
        channels = await _available_channels(context.bot)
        draft.mode = "awaiting_channel"
        await message.reply_text(
            f"Добавил канал: {_channel_label(_channel_registry[int(chat.id)])}\n\nКуда публикуем?",
            reply_markup=_channel_picker_markup(channels),
        )
        raise ApplicationHandlerStop

    if draft is None:
        return

    if draft.mode in {"awaiting_button_url", "awaiting_button_webapp"}:
        if not message.text:
            await message.reply_text("Для кнопки пришлите текст: Название | https://ссылка")
            raise ApplicationHandlerStop
        kind: Literal["url", "web_app"] = "web_app" if draft.mode == "awaiting_button_webapp" else "url"
        try:
            spec = _parse_channel_button(message.text, kind=kind)
        except BroadcastBotError as exc:
            await message.reply_text(str(exc))
            raise ApplicationHandlerStop
        draft.buttons.append(replace(spec, row=draft.current_row))
        draft.mode = "ready"
        await message.reply_text(f"Кнопка «{spec.text}» добавлена.")
        await _show_menu(context, user.id, draft)
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
        generation = draft.album_generation

        async def finalize_album() -> None:
            import asyncio
            await asyncio.sleep(1.2)
            current = _channel_drafts.get(user.id)
            if current is None or current.album_generation != generation or current.mode != "awaiting_content":
                return
            current.mode = "ready"
            try:
                await _preview(context, user.id, current)
                await _show_menu(context, user.id, current)
            except BroadcastBotError as exc:
                _channel_drafts.pop(user.id, None)
                await context.bot.send_message(chat_id=user.id, text=f"Не удалось подготовить альбом: {exc}")

        context.application.create_task(finalize_album())
        raise ApplicationHandlerStop

    draft.source_chat_id = message.chat_id
    draft.source_message_ids = [message.message_id]
    draft.source_markup = message.reply_markup
    draft.mode = "ready"
    try:
        await _preview(context, user.id, draft)
    except (BroadcastBotError, TelegramError) as exc:
        _channel_drafts.pop(user.id, None)
        await message.reply_text(f"Не удалось подготовить публикацию: {exc}")
        raise ApplicationHandlerStop
    await _show_menu(context, user.id, draft)
    raise ApplicationHandlerStop


async def channel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user = update.effective_user
    if query is None or user is None:
        return
    if user.id != _owner_id():
        await query.answer("Недоступно", show_alert=True)
        raise ApplicationHandlerStop
    action = (query.data or "").removeprefix("ch:")
    await query.answer()

    draft = _channel_drafts.get(user.id)
    if draft is None:
        await query.edit_message_text("Черновик уже закрыт. Используйте /channel_post.")
        raise ApplicationHandlerStop

    if action == "add_channel":
        draft.mode = "awaiting_channel_add"
        _set_pending_channel_add(user.id, True)
        await context.bot.send_message(
            chat_id=user.id,
            text=(
                "Перешлите сюда любой пост из нужного канала.\n\n"
                "Если канал публичный, можно просто отправить его @username. "
                "Также подойдёт числовой ID канала.\n\n"
                "Бот должен быть администратором с правом публикации."
            ),
        )
        raise ApplicationHandlerStop

    if action == "refresh_channels":
        channels = await _available_channels(context.bot)
        if not channels:
            await query.edit_message_text(
                "Не нашёл каналов с правом публикации.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✖ Отмена", callback_data="ch:cancel")]]),
            )
        else:
            await query.edit_message_text("Куда публикуем?", reply_markup=_channel_picker_markup(channels))
        raise ApplicationHandlerStop

    if action.startswith("select:"):
        try:
            selected_id = int(action.split(":", 1)[1])
        except (TypeError, ValueError):
            await query.answer("Некорректный канал", show_alert=True)
            raise ApplicationHandlerStop

        channels = await _available_channels(context.bot)
        selected = next((item for item in channels if int(item["id"]) == selected_id), None)
        if selected is None:
            await query.edit_message_text(
                "Этот канал больше недоступен для публикации. Выберите другой.",
                reply_markup=_channel_picker_markup(channels) if channels else None,
            )
            raise ApplicationHandlerStop

        _channel_selected_targets[user.id] = selected_id
        _set_pending_channel_add(user.id, False)
        await query.edit_message_text(f"Канал выбран: {_channel_label(selected)}")

        if draft.source_message_ids:
            draft.mode = "ready"
            await _preview(context, user.id, draft)
            await _show_menu(context, user.id, draft)
        else:
            draft.mode = "awaiting_content"
            await context.bot.send_message(
                chat_id=user.id,
                text=(
                    "Теперь пришлите текст, фото, видео, GIF, документ или альбом. "
                    "Форматирование Telegram сохранится."
                ),
            )
        raise ApplicationHandlerStop

    if action == "add_elections":
        added = _add_elections_button(draft)
        draft.mode = "ready"
        await query.edit_message_text(
            _menu_text(draft) + (
                "\n\nКнопка «🗳 Выборы» добавлена."
                if added else "\n\nКнопка «🗳 Выборы» уже в черновике."
            ),
            reply_markup=_menu_markup(draft),
        )
    elif action == "add_url":
        draft.mode = "awaiting_button_url"
        await context.bot.send_message(chat_id=user.id, text="Пришлите кнопку в формате:\nОтзывы | https://example.com")
    elif action == "add_webapp":
        draft.mode = "awaiting_button_webapp"
        await context.bot.send_message(
            chat_id=user.id,
            text=(
                "Пришлите Mini App кнопку в формате:\n"
                "🐾 Забрать 109 | promo:nyan109\n\n"
                "Также можно отправить обычный HTTPS URL Mini App. В канал он будет опубликован как Telegram deep link."
            ),
        )
    elif action == "new_row":
        draft.current_row += 1
        await query.edit_message_text(_menu_text(draft) + "\n\nСледующая кнопка будет на новой строке.", reply_markup=_menu_markup(draft))
    elif action == "clear_buttons":
        draft.buttons.clear()
        draft.current_row = 0
        await query.edit_message_text(_menu_text(draft), reply_markup=_menu_markup(draft))
    elif action == "toggle_source":
        draft.keep_source_markup = not draft.keep_source_markup
        await query.edit_message_text(_menu_text(draft), reply_markup=_menu_markup(draft))
    elif action == "preview":
        try:
            await _preview(context, user.id, draft)
        except (BroadcastBotError, TelegramError) as exc:
            await context.bot.send_message(chat_id=user.id, text=f"Предпросмотр не удался: {exc}")
    elif action == "publish":
        try:
            await _preview(context, user.id, draft)
        except (BroadcastBotError, TelegramError) as exc:
            await context.bot.send_message(chat_id=user.id, text=f"Предпросмотр не удался: {exc}")
            raise ApplicationHandlerStop
        await context.bot.send_message(
            chat_id=user.id,
            text="Предпросмотр выше. Опубликовать это сообщение в канал?",
            reply_markup=_confirm_markup(),
        )
    elif action == "edit":
        await query.edit_message_text(_menu_text(draft), reply_markup=_menu_markup(draft))
    elif action == "cancel":
        _channel_drafts.pop(user.id, None)
        _channel_selected_targets.pop(user.id, None)
        _set_pending_channel_add(user.id, False)
        await query.edit_message_text("Черновик публикации удалён.")
    elif action == "confirm_publish":
        channel_id = _channel_selected_targets.get(user.id)
        if channel_id is None:
            channels = await _available_channels(context.bot)
            await context.bot.send_message(
                chat_id=user.id,
                text="Сначала выберите канал.",
                reply_markup=_channel_picker_markup(channels) if channels else None,
            )
            raise ApplicationHandlerStop
        try:
            username = await _bot_username(context.bot)
            await _copy_to_chat(bot=context.bot, chat_id=channel_id, draft=draft, bot_username=username)
        except Forbidden as exc:
            await context.bot.send_message(chat_id=user.id, text="Не удалось опубликовать: бот не администратор канала или нет права публикации.")
            raise ApplicationHandlerStop from exc
        except BadRequest as exc:
            await context.bot.send_message(chat_id=user.id, text=f"Не удалось опубликовать: {exc}")
            raise ApplicationHandlerStop from exc
        except (RetryAfter, NetworkError, TelegramError, BroadcastBotError) as exc:
            await context.bot.send_message(chat_id=user.id, text=f"Не удалось опубликовать: {exc}")
            raise ApplicationHandlerStop from exc
        target_label = _selected_channel_text(user.id)
        _channel_drafts.pop(user.id, None)
        _channel_selected_targets.pop(user.id, None)
        await query.edit_message_text(f"Публикация отправлена: {target_label}.")

    raise ApplicationHandlerStop


async def channel_membership_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    change = update.my_chat_member
    if change is None or getattr(change.chat, "type", None) != "channel":
        return
    status = str(getattr(change.new_chat_member, "status", ""))
    can_post = getattr(change.new_chat_member, "can_post_messages", None)
    if status in {"administrator", "creator"} and can_post is not False:
        _remember_channel(change.chat)
    else:
        _forget_channel(int(change.chat.id))


async def channel_seen_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat = update.effective_chat
    if chat is None or getattr(chat, "type", None) != "channel":
        return
    writable, resolved = await _channel_is_writable(context.bot, int(chat.id))
    if writable and resolved is not None:
        _remember_channel(resolved)


async def _bootstrap_channel_registry(application: Application) -> None:
    try:
        await _available_channels(application.bot)
    except TelegramError:
        pass


async def _ensure_channel_command_menu(application: Application) -> None:
    scope = BotCommandScopeChat(chat_id=_owner_id())
    try:
        default_commands = await application.bot.get_my_commands()
        owner_commands = await application.bot.get_my_commands(scope=scope)
        merged: dict[str, BotCommand] = {command.command: command for command in [*default_commands, *owner_commands]}
        merged["channel_post"] = BotCommand(command="channel_post", description="Создать публикацию в канал")
        merged["channel_add"] = BotCommand(command="channel_add", description="Добавить канал для публикаций")
        await application.bot.set_my_commands(list(merged.values())[:100], scope=scope)
    except TelegramError:
        pass


def register_channel_publish_handlers(app: Application) -> None:
    global _channel_post_init_hook_installed

    app.add_handler(ChatMemberHandler(channel_membership_handler, ChatMemberHandler.MY_CHAT_MEMBER), group=-23)
    app.add_handler(MessageHandler(filters.ChatType.CHANNEL, channel_seen_handler), group=-22)
    app.add_handler(CommandHandler("channel_add", channel_add_command), group=-21)
    app.add_handler(CommandHandler("channel_post", channel_post_command), group=-21)
    app.add_handler(CommandHandler("publish_channel", channel_post_command), group=-21)
    app.add_handler(CallbackQueryHandler(channel_callback, pattern=r"^ch:"), group=-21)
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, channel_message_handler), group=-21)

    if not _channel_post_init_hook_installed:
        previous_post_init = getattr(app, "post_init", None)

        async def _channel_post_init(application: Application) -> None:
            if previous_post_init is not None:
                await previous_post_init(application)
            await _bootstrap_channel_registry(application)
            await _ensure_channel_command_menu(application)

        app.post_init = _channel_post_init
        _channel_post_init_hook_installed = True
