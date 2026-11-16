"""Uniform Nyan Shop signature for python-telegram-bot outgoing messages.

Install before app.run_polling. Only actual outbound message text/captions are
modified; callbacks, commands, replies, forwards and message markup are intact.
Idempotent for multiple stacked wrappers and pre-signed texts.
"""
from __future__ import annotations

from functools import wraps

FOOTER = "♡ больше, чем магазин — @nyanshoping"
TEXT_METHODS = frozenset({
    "sendmessage", "editmessagetext", "copymessage", "copymessages",
    "sendpaidmedia", "sendpoll",
})
CAPTION_METHODS = frozenset({
    "sendphoto", "sendvideo", "sendaudio", "sendanimation",
    "senddocument", "sendvoice", "sendvideonote", "editmessagecaption",
})
# The payload for copyMessage, copyMessages, sendPoll and sendPaidMedia
# does not have a simple text/caption field; leave them unmodified.
TEXT_METHODS = frozenset({"sendmessage", "editmessagetext"})
CAPTION_METHODS = frozenset({
    "sendphoto", "sendvideo", "sendaudio", "sendanimation",
    "senddocument", "sendvoice", "editmessagecaption",
})
PATCH_MARKER = "_nyan_shop_footer_patched"


def append_footer(value: object, limit: int) -> object:
    if not isinstance(value, str):
        return value
    clean = value.rstrip()
    if not clean or clean.endswith(FOOTER):
        return value
    new = clean + "\n\n" + FOOTER
    # Telegram text/caption limit is measured after entity parsing, and raw
    # length is a conservative upper bound. Never truncate user content.
    if len(new) > limit:
        return value
    return new


def _wrap_post(base_class: type) -> bool:
    original = base_class.__dict__.get("_post")
    if original is None or getattr(original, PATCH_MARKER, False):
        return False

    @wraps(original)
    async def wrapped(self, *args, **kwargs):
        endpoint = args[0] if args else kwargs.get("endpoint")
        data = args[1] if len(args) >= 2 else kwargs.get("data")
        method = str(endpoint or "").replace("_", "").lower()
        field = (
            "text" if method in TEXT_METHODS
            else "caption" if method in CAPTION_METHODS
            else None
        )
        if field and isinstance(data, dict) and isinstance(data.get(field), str):
            updated = append_footer(data[field], 4096 if field == "text" else 1024)
            if updated != data[field]:
                data = {**data, field: updated}
                if len(args) >= 2:
                    args = (args[0], data, *args[2:])
                else:
                    kwargs = {**kwargs, "data": data}
        return await original(self, *args, **kwargs)

    setattr(wrapped, PATCH_MARKER, True)
    setattr(base_class, "_post", wrapped)
    return True


def install_nyan_shop_footer() -> None:
    from telegram import Bot
    from telegram.ext import ExtBot
    # Some PTB versions override ExtBot._post and call Bot._post,
    # so install both; append_footer is idempotent.
    _wrap_post(Bot)
    _wrap_post(ExtBot)
