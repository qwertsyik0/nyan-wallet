from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from . import backend_app as core

logger = logging.getLogger("nyan_wallet.bot_menu")

MINI_APP_URL = os.getenv("MINI_APP_URL", "https://qwertsyik0.github.io/nyan-wallet/").strip() or "https://qwertsyik0.github.io/nyan-wallet/"

# Telegram WebViews may cache the old index even after GitHub Pages is updated.
# Synchronize a versioned menu URL so opening the bot loads the latest release.
def _menu_app_url(url: str) -> str:
    parsed = urlsplit(url)
    query = [(k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=True) if k != "nyan_build"]
    build = "ui20261016v4-more-" + (os.getenv("NYAN_WALLET_UI_BUILD") or "20261015-nyanid2").strip()
    query.append(("nyan_build", build[:80]))
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(query), parsed.fragment))


MENU_APP_URL = _menu_app_url(MINI_APP_URL)


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
        _set_chat_menu_button(chat_id=None, text="Nyan Wallet", url=MENU_APP_URL)
        if core.OWNER_TELEGRAM_ID is not None:
            _set_chat_menu_button(
                chat_id=int(core.OWNER_TELEGRAM_ID),
                text="Управлять",
                url=MENU_APP_URL,
            )
        print("[bot_menu] public=Nyan Wallet owner=Управлять synchronized")
    except (urllib.error.URLError, TimeoutError, RuntimeError, ValueError) as exc:
        # Bot menu sync must never prevent the Wallet API from starting.
        logger.warning("Telegram bot menu sync failed: %s", exc)
