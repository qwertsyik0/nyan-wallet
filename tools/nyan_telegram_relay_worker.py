#!/usr/bin/env python3
"""Deliver Nyan Wallet outbox messages from a host with Telegram connectivity.

Designed for the existing SprintHost Python installation: standard library
only, HTTPS polling to FirstVDS, no inbound web server and no database access.

Environment:
  NYAN_TELEGRAM_RELAY_SECRET  Same 32+ character secret as on FirstVDS
  NYAN_WALLET_API_URL        https://nyan-wallet-153-76-175-145.sslip.io
  BOT_TOKEN                  Existing @nyancash_bot token on SprintHost

Use --env-file FILE for a chmod-600 file containing KEY=VALUE lines.
Use --check before starting the service; it does not lease or send messages.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import socket
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


STOP = False
_ORIGINAL_GETADDRINFO = socket.getaddrinfo
RICH_MESSAGE_PREFIX = "NYAN_TG_RICH_V1:"


def _stop(*_args):
    global STOP
    STOP = True


def configure_telegram_address_family(choice: str) -> None:
    """Change only api.telegram.org resolution; wallet API routing is intact."""
    family = {"4": socket.AF_INET, "6": socket.AF_INET6}.get(choice)

    def resolve(host, port, requested_family=0, type=0, proto=0, flags=0):
        if host == "api.telegram.org" and family is not None:
            requested_family = family
        return _ORIGINAL_GETADDRINFO(host, port, requested_family, type, proto, flags)

    socket.getaddrinfo = resolve


def load_env_file(path: str) -> None:
    if not path:
        return
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):]
        key, separator, value = line.partition("=")
        if not separator or not key.strip().isidentifier():
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
            value = value[1:-1]
        os.environ.setdefault(key.strip(), value)


class RelayError(Exception):
    def __init__(self, message: str, *, permanent: bool = False):
        super().__init__(message[:250])
        self.permanent = permanent


def request_json(url: str, *, data: dict | None = None, secret: str = "") -> dict:
    headers = {"Accept": "application/json"}
    if secret:
        headers["X-Nyan-Relay-Secret"] = secret
    payload = None
    if data is not None:
        payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(
        url, data=payload, headers=headers,
        method="POST" if data is not None else "GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            answer = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            answer = json.loads(exc.read().decode("utf-8", errors="replace"))
            reason = str(answer.get("description") or answer.get("detail") or f"HTTP {exc.code}")
        except Exception:
            reason = f"HTTP {exc.code}"
        raise RelayError(reason, permanent=exc.code in (400, 401, 403, 404)) from None
    except (urllib.error.URLError, TimeoutError) as exc:
        raise RelayError(f"network: {type(exc).__name__}") from None
    except (ValueError, UnicodeError):
        raise RelayError("invalid JSON response") from None
    if not answer.get("ok"):
        raise RelayError(str(answer.get("description") or "API returned ok=false"))
    return answer


def telegram_send_payload(chat_id: int, text: str) -> dict:
    """Build Telegram request; ordinary wallet notifications remain plain text.

    Rich messages are an explicit, constrained outbox envelope used for owner
    invitations. Never interpret arbitrary user-visible text as Telegram HTML.
    """
    result = {"chat_id": int(chat_id), "text": text}
    if not text.startswith(RICH_MESSAGE_PREFIX):
        return result

    try:
        message = json.loads(text[len(RICH_MESSAGE_PREFIX):])
        if not isinstance(message, dict):
            raise ValueError("message must be an object")
        html = message["text"]
        buttons = message["buttons"]
        if not isinstance(html, str) or not 1 <= len(html) <= 3800:
            raise ValueError("invalid rich message text")
        if not isinstance(buttons, list) or not 1 <= len(buttons) <= 4:
            raise ValueError("invalid buttons")
        inline_keyboard = []
        for button in buttons:
            if not isinstance(button, dict) or set(button) != {"text", "url"}:
                raise ValueError("invalid button")
            title, url = button["text"], button["url"]
            if (not isinstance(title, str) or not 1 <= len(title) <= 64
                    or not isinstance(url, str)
                    or not url.startswith("https://t.me/")
                    or len(url) > 256):
                raise ValueError("invalid button fields")
            inline_keyboard.append([{"text": title, "url": url}])
        if set(message) != {"text", "buttons"}:
            raise ValueError("unexpected fields")
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise RelayError("invalid rich message envelope", permanent=True) from exc

    return {
        "chat_id": int(chat_id),
        "text": html,
        "parse_mode": "HTML",
        "link_preview_options": {"is_disabled": True},
        "reply_markup": {"inline_keyboard": inline_keyboard},
    }


def send_one(bot_token: str, chat_id: int, text: str) -> int | None:
    answer = request_json(
        f"https://api.telegram.org/bot{bot_token}/sendMessage",
        data=telegram_send_payload(chat_id, text),
    )
    return answer.get("result", {}).get("message_id")


def cycle(api: str, secret: str, bot_token: str) -> int:
    result = request_json(api + "/api/internal/telegram-relay/pull?limit=20", secret=secret)
    items = result.get("items") or []
    for item in items:
        if STOP:
            break
        ident = int(item["id"])
        ack = {"id": ident, "lease_token": item["lease_token"], "delivered": False}
        try:
            ack["telegram_message_id"] = send_one(bot_token, item["chat_id"], item["text"])
            ack["delivered"] = True
            print(f"delivered id={ident}", flush=True)
        except RelayError as exc:
            ack["error"] = str(exc)
            ack["permanent_failure"] = exc.permanent
            print(f"delivery_error id={ident}: {exc}", flush=True)
        try:
            request_json(api + "/api/internal/telegram-relay/ack", data=ack, secret=secret)
        except RelayError as exc:
            # An ACK can fail after Telegram has accepted the message.  It may
            # be delivered again when the lease expires (at-least-once queue).
            print(f"ack_error id={ident}: {exc}", flush=True)
        time.sleep(0.12)
    return len(items)


def main() -> int:
    parser = argparse.ArgumentParser(description="Nyan Wallet Telegram delivery relay")
    parser.add_argument("--env-file", action="append", default=[],
                        help="May be passed multiple times; first value for a key wins")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--interval", type=float, default=3.0)
    args = parser.parse_args()
    for env_file in args.env_file:
        load_env_file(env_file)

    api = os.environ.get("NYAN_WALLET_API_URL", "").rstrip("/")
    secret = os.environ.get("NYAN_TELEGRAM_RELAY_SECRET", "").strip()
    token = os.environ.get("BOT_TOKEN", "").strip()
    if not api.startswith("https://") or len(secret) < 32 or not token:
        print("Missing HTTPS API URL, relay secret or BOT_TOKEN", file=sys.stderr)
        return 2

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)
    preferred = os.environ.get("NYAN_TELEGRAM_IP_FAMILY", "auto").strip().lower()
    if preferred not in {"auto", "4", "6"}:
        print("NYAN_TELEGRAM_IP_FAMILY must be auto, 4 or 6", file=sys.stderr)
        return 2
    options = [preferred] if preferred != "auto" else ["auto", "6", "4"]
    connected = False
    for option in options:
        configure_telegram_address_family(option)
        try:
            request_json(f"https://api.telegram.org/bot{token}/getMe")
            connected = True
            print(f"Telegram reachable (address family {option})", flush=True)
            break
        except RelayError as exc:
            print(f"Telegram check ({option}) failed: {exc}", flush=True)
            if exc.permanent:
                return 1
    if not connected:
        return 1
    try:
        status = request_json(api + "/api/internal/telegram-relay/status", secret=secret)
        print("relay check OK; queued:", status.get("counts", {}), flush=True)
    except RelayError as exc:
        print(f"relay check failed: {exc}", file=sys.stderr)
        return 1

    if args.check:
        return 0
    while not STOP:
        try:
            count = cycle(api, secret, token)
            if args.once:
                return 0
            if not count:
                time.sleep(max(1.0, args.interval))
        except RelayError as exc:
            print(f"relay polling failed: {exc}", flush=True)
            if args.once:
                return 1
            time.sleep(10)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
