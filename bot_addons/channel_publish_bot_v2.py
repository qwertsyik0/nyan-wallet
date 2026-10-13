from __future__ import annotations

import asyncio
import json
import os
import re
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from telegram import (
    BotCommand,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaAnimation,
    InputMediaDocument,
    InputMediaPhoto,
    InputMediaVideo,
    Update,
    WebAppInfo,
)
from telegram.error import BadRequest, Forbidden, TelegramError
from telegram.ext import (
    Application,
    ApplicationHandlerStop,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

OWNER_ID = int(os.getenv("OWNER_TELEGRAM_ID", "0") or "0")
CHANNEL_STATE_PATH = Path(
    os.getenv(
        "NYAN_CHANNEL_PUBLISH_STATE_FILE",
        str(Path(__file__).with_name("channel_publish_channels.json")),
    )
)
HTTPS_PATTERN = re.compile(r"^https://", re.IGNORECASE)


@dataclass
class ButtonSpec:
    text: str
    url: str
    kind: Literal["url", "web_app"]
    row: int = 0


@dataclass
class SourceMessage:
    chat_id: int
    message_id: int
    media_group_id: str | None = None


@dataclass
class Draft:
    owner_id: int
    target_chat_id: int | None = None
    source: list[SourceMessage] = field(default_factory=list)
    buttons: list[ButtonSpec] = field(default_factory=list)
    button_row: int = 0
    mode: str = "awaiting_channel"


_drafts: dict[int, Draft] = {}
_registry: dict[int, dict[str, object]] = {}


def _is_owner(user_id: int | None) -> bool:
    return bool(user_id and OWNER_ID and int(user_id) == OWNER_ID)


def _load_registry() -> None:
    global _registry
    try:
        data = json.loads(CHANNEL_STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        data = {}
    items = data.get("channels") if isinstance(data, dict) else []
    result: dict[int, dict[str, object]] = {}
    if isinstance(items, list):
        for item in items:
            try:
                chat_id = int(item["id"])
            except Exception:
                continue
            result[chat_id] = {
                "id": chat_id,
                "title": str(item.get("title") or chat_id),
                "username": item.get("username"),
            }
    _registry = result


def _save_registry() -> None:
    CHANNEL_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CHANNEL_STATE_PATH.write_text(
        json.dumps({"channels": list(_registry.values())}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _remember_channel(chat) -> None:
    if chat is None or getattr(chat, "type", None) != "channel":
        return
    chat_id = int(chat.id)
    _registry[chat_id] = {
        "id": chat_id,
        "title": getattr(chat, "title", None) or str(chat_id),
        "username": getattr(chat, "username", None),
    }
    _save_registry()


def _channel_label(item: dict[str, object]) -> str:
    title = str(item.get("title") or item.get("id") or "канал")
    username = item.get("username")
    return f"{title} (@{username})" if username else title


async def _channel_is_writable(bot, chat_id: int) -> tuple[bool, object | None]:
    try:
        chat = await bot.get_chat(chat_id)
        if getattr(chat, "type", None) != "channel":
            return False, None
        member = await bot.get_chat_member(chat_id, bot.id)
        status = getattr(member, "status", "")
        can_post = getattr(member, "can_post_messages", None)
        writable = status in {"administrator", "creator"} and can_post is not False
        return writable, chat
    except TelegramError:
        return False, None


async def _available_channels(bot) -> list[dict[str, object]]:
    available: list[dict[str, object]] = []
    stale: list[int] = []
    for chat_id in list(_registry):
        writable, chat = await _channel_is_writable(bot, chat_id)
        if writable and chat is not None:
            _remember_channel(chat)
            available.append(_registry[chat_id])
        else:
            stale.append(chat_id)
    for chat_id in stale:
        _registry.pop(chat_id, None)
    if stale:
        _save_registry()
    return sorted(available, key=lambda x: str(x.get("title") or "").lower())


def _channel_picker(channels: list[dict[str, object]]) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(f"📣 {_channel_label(item)}", callback_data=f"cp2:channel:{int(item['id'])}")]
        for item in channels
    ]
    rows.append([InlineKeyboardButton("➕ Добавить канал", callback_data="cp2:add_channel")])
    rows.append([InlineKeyboardButton("✖ Отмена", callback_data="cp2:cancel")])
    return InlineKeyboardMarkup(rows)


def _menu(draft: Draft) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("🌐 URL", callback_data="cp2:add_url"),
                InlineKeyboardButton("📱 Mini App", callback_data="cp2:add_webapp"),
            ],
            [
                InlineKeyboardButton("↩️ Новая строка", callback_data="cp2:new_row"),
                InlineKeyboardButton("🗑 Очистить кнопки", callback_data="cp2:clear_buttons"),
            ],
            [InlineKeyboardButton("👁 Предпросмотр", callback_data="cp2:preview")],
            [InlineKeyboardButton("📣 Опубликовать", callback_data="cp2:publish")],
            [InlineKeyboardButton("✖ Отмена", callback_data="cp2:cancel")],
        ]
    )


def _confirm_markup() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("✅ Да, опубликовать", callback_data="cp2:confirm")],
            [InlineKeyboardButton("↩️ Назад", callback_data="cp2:back")],
            [InlineKeyboardButton("✖ Отмена", callback_data="cp2:cancel")],
        ]
    )


def _post_markup(draft: Draft) -> InlineKeyboardMarkup | None:
    if not draft.buttons:
        return None
    grouped: dict[int, list[InlineKeyboardButton]] = {}
    for spec in draft.buttons:
        if spec.kind == "web_app":
            button = InlineKeyboardButton(spec.text, web_app=WebAppInfo(spec.url))
        else:
            button = InlineKeyboardButton(spec.text, url=spec.url)
        grouped.setdefault(spec.row, []).append(button)
    return InlineKeyboardMarkup([grouped[row] for row in sorted(grouped)])


def _menu_text(draft: Draft) -> str:
    target = _registry.get(draft.target_chat_id or 0)
    channel = _channel_label(target) if target else "не выбран"
    return (
        "Новая публикация\n\n"
        f"Канал: {channel}\n"
        f"Сообщений: {len(draft.source)}\n"
        f"Кнопок: {len(draft.buttons)}\n\n"
        "Исходные кнопки никогда не копируются. "
        "В публикацию попадут только кнопки, которые вы добавили здесь."
    )


def _parse_button(text: str, kind: Literal["url", "web_app"], row: int) -> ButtonSpec:
    raw = (text or "").strip()
    if "|" not in raw:
        raise ValueError("Формат: Текст кнопки | https://example.com")
    label, url = [part.strip() for part in raw.split("|", 1)]
    if not label or len(label) > 64:
        raise ValueError("Название кнопки должно быть от 1 до 64 символов.")
    if not HTTPS_PATTERN.match(url):
        raise ValueError("Ссылка должна начинаться с https://")
    return ButtonSpec(text=label, url=url, kind=kind, row=row)


def _capture_source(message) -> list[SourceMessage]:
    if message is None:
        return []
    return [
        SourceMessage(
            chat_id=int(message.chat_id),
            message_id=int(message.message_id),
            media_group_id=getattr(message, "media_group_id", None),
        )
    ]


async def _copy_source(bot, target_chat_id: int, draft: Draft) -> None:
    if not draft.source:
        raise ValueError("Нет сообщения для публикации.")

    markup = _post_markup(draft)

    if len(draft.source) == 1:
        src = draft.source[0]
        await bot.copy_message(
            chat_id=target_chat_id,
            from_chat_id=src.chat_id,
            message_id=src.message_id,
            reply_markup=markup,
        )
        return

    copied = []
    for index, src in enumerate(draft.source):
        result = await bot.copy_message(
            chat_id=target_chat_id,
            from_chat_id=src.chat_id,
            message_id=src.message_id,
            reply_markup=markup if index == len(draft.source) - 1 else None,
        )
        copied.append(result)


async def _preview(bot, user_id: int, draft: Draft) -> None:
    if not draft.source:
        await bot.send_message(chat_id=user_id, text="Сначала пришлите сообщение для публикации.")
        return
    await bot.send_message(chat_id=user_id, text="Предпросмотр:")
    for index, src in enumerate(draft.source):
        await bot.copy_message(
            chat_id=user_id,
            from_chat_id=src.chat_id,
            message_id=src.message_id,
            reply_markup=_post_markup(draft) if index == len(draft.source) - 1 else None,
        )


async def channel_post_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not user or not _is_owner(user.id):
        return

    channels = await _available_channels(context.bot)
    draft = Draft(owner_id=user.id)
    replied = update.effective_message.reply_to_message if update.effective_message else None
    if replied is not None:
        draft.source = _capture_source(replied)

    _drafts[user.id] = draft

    if not channels:
        draft.mode = "awaiting_channel_add"
        await update.effective_message.reply_text(
            "Пока нет доступных каналов.\n\n"
            "Добавьте бота администратором канала с правом публикации, "
            "затем перешлите сюда любое сообщение из этого канала."
        )
        return

    await update.effective_message.reply_text(
        "Куда публикуем?",
        reply_markup=_channel_picker(channels),
    )


async def channel_add_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not user or not _is_owner(user.id):
        return
    draft = _drafts.get(user.id) or Draft(owner_id=user.id)
    draft.mode = "awaiting_channel_add"
    _drafts[user.id] = draft
    await update.effective_message.reply_text(
        "Перешлите сюда любое сообщение из нужного канала. "
        "Бот должен быть администратором с правом публикации."
    )


async def channel_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    message = update.effective_message
    if not user or not message or not _is_owner(user.id):
        return

    draft = _drafts.get(user.id)
    if draft is None:
        return

    if draft.mode == "awaiting_channel_add":
        source_chat = getattr(message, "forward_from_chat", None)
        origin = getattr(message, "forward_origin", None)
        origin_chat = getattr(origin, "chat", None) if origin is not None else None
        chat = source_chat or origin_chat
        if chat is None or getattr(chat, "type", None) != "channel":
            await message.reply_text("Не вижу канал. Перешлите обычное сообщение именно из канала.")
            raise ApplicationHandlerStop
        writable, resolved = await _channel_is_writable(context.bot, int(chat.id))
        if not writable or resolved is None:
            await message.reply_text("Бот не может публиковать в этот канал. Проверьте права администратора.")
            raise ApplicationHandlerStop
        _remember_channel(resolved)
        draft.mode = "awaiting_channel"
        channels = await _available_channels(context.bot)
        await message.reply_text("Канал добавлен. Куда публикуем?", reply_markup=_channel_picker(channels))
        raise ApplicationHandlerStop

    if draft.mode in {"awaiting_button_url", "awaiting_button_webapp"}:
        try:
            kind: Literal["url", "web_app"] = "url" if draft.mode == "awaiting_button_url" else "web_app"
            draft.buttons.append(_parse_button(message.text or "", kind, draft.button_row))
            draft.mode = "editing"
            await message.reply_text(_menu_text(draft), reply_markup=_menu(draft))
        except ValueError as exc:
            await message.reply_text(str(exc))
        raise ApplicationHandlerStop

    if draft.mode == "awaiting_content":
        draft.source = _capture_source(message)
        draft.mode = "editing"
        await message.reply_text(_menu_text(draft), reply_markup=_menu(draft))
        raise ApplicationHandlerStop


async def channel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user = update.effective_user
    if not query or not user or not _is_owner(user.id):
        return
    await query.answer()

    data = query.data or ""
    if not data.startswith("cp2:"):
        return
    action = data.split(":", 1)[1]

    draft = _drafts.get(user.id)
    if draft is None:
        await query.edit_message_text("Черновик закрыт. Используйте /channel_post.")
        return

    if action.startswith("channel:"):
        try:
            chat_id = int(action.split(":", 1)[1])
        except ValueError:
            return
        writable, chat = await _channel_is_writable(context.bot, chat_id)
        if not writable or chat is None:
            await query.edit_message_text("Канал больше недоступен. Запустите /channel_post заново.")
            return
        _remember_channel(chat)
        draft.target_chat_id = chat_id
        if draft.source:
            draft.mode = "editing"
            await query.edit_message_text(_menu_text(draft), reply_markup=_menu(draft))
        else:
            draft.mode = "awaiting_content"
            await query.edit_message_text(
                f"Канал выбран: {_channel_label(_registry[chat_id])}\n\n"
                "Теперь пришлите ОДНО сообщение для публикации: текст, фото, видео, GIF или документ. "
                "Кнопки исходника не будут скопированы."
            )
        return

    if action == "add_channel":
        draft.mode = "awaiting_channel_add"
        await query.edit_message_text(
            "Перешлите сообщение из нужного канала. "
            "Бот должен быть администратором с правом публикации."
        )
    elif action == "add_url":
        draft.mode = "awaiting_button_url"
        await context.bot.send_message(
            chat_id=user.id,
            text="Пришлите кнопку:\nТекст | https://example.com",
        )
    elif action == "add_webapp":
        draft.mode = "awaiting_button_webapp"
        await context.bot.send_message(
            chat_id=user.id,
            text="Пришлите Mini App кнопку:\nТекст | https://example.com",
        )
    elif action == "new_row":
        draft.button_row += 1
        await query.edit_message_text(_menu_text(draft), reply_markup=_menu(draft))
    elif action == "clear_buttons":
        draft.buttons.clear()
        draft.button_row = 0
        await query.edit_message_text(_menu_text(draft), reply_markup=_menu(draft))
    elif action == "preview":
        await _preview(context.bot, user.id, draft)
    elif action == "publish":
        if draft.target_chat_id is None:
            await query.answer("Сначала выберите канал.", show_alert=True)
            return
        if not draft.source:
            await query.answer("Сначала пришлите сообщение.", show_alert=True)
            return
        await query.edit_message_text(
            _menu_text(draft) + "\n\nОпубликовать сейчас?",
            reply_markup=_confirm_markup(),
        )
    elif action == "back":
        draft.mode = "editing"
        await query.edit_message_text(_menu_text(draft), reply_markup=_menu(draft))
    elif action == "cancel":
        _drafts.pop(user.id, None)
        await query.edit_message_text("Публикация отменена.")
    elif action == "confirm":
        if draft.target_chat_id is None or not draft.source:
            await query.edit_message_text("Черновик неполный. Запустите /channel_post заново.")
            _drafts.pop(user.id, None)
            return
        try:
            await _copy_source(context.bot, draft.target_chat_id, draft)
        except (BadRequest, Forbidden, TelegramError) as exc:
            await query.edit_message_text(f"Не удалось опубликовать: {exc}")
            return
        target = _registry.get(draft.target_chat_id)
        label = _channel_label(target) if target else str(draft.target_chat_id)
        _drafts.pop(user.id, None)
        await query.edit_message_text(f"Готово. Публикация отправлена: {label}.")


async def channel_seen_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat = update.effective_chat
    if chat is None or getattr(chat, "type", None) != "channel":
        return
    writable, resolved = await _channel_is_writable(context.bot, int(chat.id))
    if writable and resolved is not None:
        _remember_channel(resolved)


async def _ensure_commands(application: Application) -> None:
    try:
        current = await application.bot.get_my_commands()
        merged = {cmd.command: cmd for cmd in current}
        merged["channel_post"] = BotCommand("channel_post", "Создать публикацию в канал")
        merged["channel_add"] = BotCommand("channel_add", "Добавить канал")
        await application.bot.set_my_commands(list(merged.values()))
    except TelegramError:
        pass


def register_channel_publish_handlers(app: Application) -> None:
    _load_registry()
    app.add_handler(CommandHandler("channel_add", channel_add_command), group=-31)
    app.add_handler(CommandHandler("channel_post", channel_post_command), group=-31)
    app.add_handler(CommandHandler("publish_channel", channel_post_command), group=-31)
    app.add_handler(CallbackQueryHandler(channel_callback, pattern=r"^cp2:"), group=-31)
    app.add_handler(MessageHandler(filters.ChatType.CHANNEL, channel_seen_handler), group=-30)
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, channel_message_handler), group=-29)

    previous_post_init = app.post_init

    async def _post_init(application: Application) -> None:
        if previous_post_init is not None:
            await previous_post_init(application)
        await _ensure_commands(application)

    app.post_init = _post_init
