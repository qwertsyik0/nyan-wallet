from __future__ import annotations

import os
import re
import urllib.parse
from dataclasses import replace
from typing import Literal

from telegram import BotCommand, BotCommandScopeChat, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import BadRequest, Forbidden, NetworkError, RetryAfter, TelegramError
from telegram.ext import Application, ApplicationHandlerStop, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters

from broadcast_bot import BroadcastBotError, BroadcastDraft, ButtonSpec, _owner_id

DEFAULT_MINI_APP_URL = "https://qwertsyik0.github.io/nyan-wallet/"
PROMO_SLUG_PATTERN = re.compile(r"^[a-z0-9_-]{2,48}$", re.IGNORECASE)
_channel_drafts: dict[int, BroadcastDraft] = {}
_channel_post_init_hook_installed = False


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
    short_name = (os.getenv("NYAN_MINI_APP_SHORT_NAME") or os.getenv("TELEGRAM_WEBAPP_SHORT_NAME") or "").strip()
    start_param = urllib.parse.quote(_start_param_for_url(url), safe="_-")
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
        f"Добавлено кнопок: {len(draft.buttons)}\n\n"
        "Можно добавить URL/Mini App кнопки, посмотреть предпросмотр или опубликовать после подтверждения."
    )


def _menu_markup(draft: BroadcastDraft) -> InlineKeyboardMarkup:
    source_count = _source_button_count(draft.source_markup)
    source_state = "вкл" if draft.keep_source_markup else "выкл"
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("🌐 URL-кнопка", callback_data="ch:add_url"),
                InlineKeyboardButton("📱 Mini App", callback_data="ch:add_webapp"),
            ],
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

    try:
        _configured_channel_id()
    except BroadcastBotError as exc:
        await message.reply_text(str(exc))
        raise ApplicationHandlerStop

    draft = BroadcastDraft(owner_id=user.id)
    _channel_drafts[user.id] = draft

    if replied is not None:
        if replied.media_group_id:
            await message.reply_text("Это часть альбома. Используйте /channel_post без ответа, затем пришлите альбом целиком.")
            raise ApplicationHandlerStop
        draft.source_chat_id = replied.chat_id
        draft.source_message_ids = [replied.message_id]
        draft.source_markup = replied.reply_markup
        draft.mode = "ready"
        await _preview(context, user.id, draft)
        await _show_menu(context, user.id, draft)
        raise ApplicationHandlerStop

    await message.reply_text(
        "Режим публикации в канал включён.\n\n"
        "Пришлите текст, фото, видео, GIF, документ или альбом. Форматирование Telegram будет сохранено через копирование сообщения.\n\n"
        "Для кнопки на промо можно будет отправить: 🐾 Забрать 109 | promo:nyan109"
    )
    raise ApplicationHandlerStop


async def channel_post_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    await _start_channel_draft(update, context, replied=message.reply_to_message if message else None)


async def channel_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    message = update.effective_message
    if user is None or message is None or user.id != _owner_id():
        return
    draft = _channel_drafts.get(user.id)
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

    if action == "add_url":
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
        await query.edit_message_text("Черновик публикации удалён.")
    elif action == "confirm_publish":
        channel_id = _configured_channel_id()
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
        _channel_drafts.pop(user.id, None)
        await query.edit_message_text("Публикация отправлена в канал.")

    raise ApplicationHandlerStop


async def _ensure_channel_command_menu(application: Application) -> None:
    scope = BotCommandScopeChat(chat_id=_owner_id())
    try:
        default_commands = await application.bot.get_my_commands()
        owner_commands = await application.bot.get_my_commands(scope=scope)
        merged: dict[str, BotCommand] = {command.command: command for command in [*default_commands, *owner_commands]}
        merged["channel_post"] = BotCommand(command="channel_post", description="Создать публикацию в канал")
        await application.bot.set_my_commands(list(merged.values())[:100], scope=scope)
    except TelegramError:
        pass


def register_channel_publish_handlers(app: Application) -> None:
    global _channel_post_init_hook_installed

    app.add_handler(CommandHandler("channel_post", channel_post_command), group=-21)
    app.add_handler(CommandHandler("publish_channel", channel_post_command), group=-21)
    app.add_handler(CallbackQueryHandler(channel_callback, pattern=r"^ch:"), group=-21)
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, channel_message_handler), group=-21)

    if not _channel_post_init_hook_installed:
        previous_post_init = getattr(app, "post_init", None)

        async def _channel_post_init(application: Application) -> None:
            if previous_post_init is not None:
                await previous_post_init(application)
            await _ensure_channel_command_menu(application)

        app.post_init = _channel_post_init
        _channel_post_init_hook_installed = True
