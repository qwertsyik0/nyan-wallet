"""Welcome new members in partner flood; one reply photo to each join service message."""

from __future__ import annotations

import asyncio
import html
import logging
from pathlib import Path

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.error import TelegramError
from telegram.ext import Application, ContextTypes, MessageHandler, filters

GROUP_ID = -1003689150794
IMAGE = Path(__file__).resolve().with_name("nyan_partner_welcome.jpg")
LOGGER = logging.getLogger("nyan_wallet.partner_flood_welcome")


def _mention(user) -> str:
    name = html.escape(user.full_name or "лапочка", quote=True)
    return f'<a href="tg://user?id={user.id}">{name}</a>'


def _is_connect_timeout(error: BaseException) -> bool:
    """Retry only pre-connection timeouts, never ambiguous write/read failures."""
    current: BaseException | None = error
    for _ in range(10):
        if current is None:
            break
        if type(current).__name__ == "ConnectTimeout":
            return True
        current = current.__cause__ or current.__context__
    return False


async def welcome_new_members(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.message
    if not message or message.chat_id != GROUP_ID:
        return
    members = [u for u in (message.new_chat_members or ()) if not u.is_bot]
    if not members:
        return

    names = ", ".join(_mention(user) for user in members[:8])
    if len(members) > 8:
        names += f" и ещё {len(members)-8}"
    caption = (
        f"🌸 {names}, добро пожаловать во флуд! 💗\n\n"
        "располагайся, знакомься и чувствуй себя как дома ♡\n\n"
        '🐾 наш официальный спонсор — <a href="https://t.me/NyanShoping"><b>NYAN SHOP</b></a>'
    )
    buttons = InlineKeyboardMarkup([[
        InlineKeyboardButton("🛍 NYAN SHOP", url="https://t.me/NyanShoping")
    ]])
    for attempt in range(1, 4):
        try:
            with IMAGE.open("rb") as picture:
                await context.bot.send_photo(
                    chat_id=GROUP_ID,
                    photo=picture,
                    caption=caption,
                    parse_mode=ParseMode.HTML,
                    reply_to_message_id=message.message_id,
                    reply_markup=buttons,
                    connect_timeout=25,
                    read_timeout=35,
                    write_timeout=45,
                    pool_timeout=20,
                )
            LOGGER.info("Welcome sent for join event %s", message.message_id)
            return
        except TelegramError as error:
            if attempt < 3 and _is_connect_timeout(error):
                LOGGER.warning(
                    "Telegram ConnectTimeout at join event %s, retry %s/3",
                    message.message_id, attempt + 1,
                )
                await asyncio.sleep(2 * attempt)
                continue
            LOGGER.exception(
                "Cannot greet join event %s after %s attempt(s)",
                message.message_id, attempt,
            )
            return
        except OSError:
            LOGGER.exception("Cannot read welcome banner for event %s", message.message_id)
            return


def register_partner_flood_welcome(app: Application) -> None:
    app.add_handler(
        MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, welcome_new_members),
        group=-91,
    )
