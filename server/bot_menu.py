from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request

from . import backend_app as core

logger = logging.getLogger("nyan_wallet.bot_menu")

MINI_APP_URL = os.getenv("MINI_APP_URL", "https://qwertsyik0.github.io/nyan-wallet/").strip() or "https://qwertsyik0.github.io/nyan-wallet/"


def _set_chat_menu_button(*, chat_id: int | None, text: str, url: str) -> None:
    if not core.BOT_TOKEN:
        return

    payload: dict[str, object] = {
        "menu_button": {
            "type": "web_app",
            "text": text,
            "web_app": {"url": url},
        }
    }
    if chat_id is not None:
        payload["chat_id"] = int(chat_id)

    request = urllib.request.Request(
        f"https://api.telegram.org/bot{core.BOT_TOKEN}/setChatMenuButton",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=8) as response:
        data = json.loads(response.read().decode("utf-8"))
        if not data.get("ok"):
            raise RuntimeError(data.get("description") or "Telegram rejected menu button update")


def sync_bot_menu_buttons() -> None:
    """Keep the public bot menu non-admin; reserve Manage for the owner only."""

    try:
        _set_chat_menu_button(chat_id=None, text="Nyan Wallet", url=MINI_APP_URL)
        if core.OWNER_TELEGRAM_ID is not None:
            _set_chat_menu_button(
                chat_id=int(core.OWNER_TELEGRAM_ID),
                text="Управлять",
                url=MINI_APP_URL,
            )
        logger.info("Telegram bot menu buttons synchronized")
    except (urllib.error.URLError, TimeoutError, RuntimeError, ValueError) as exc:
        # Bot menu sync must never prevent the Wallet API from starting.
        logger.warning("Telegram bot menu sync failed: %s", exc)
