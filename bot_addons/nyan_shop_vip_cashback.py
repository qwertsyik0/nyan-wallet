"""Bridge verified Nyan Shop purchases to Nyan Wallet cashback.

Call `record_confirmed_shop_purchase` ONLY after authoritative payment
confirmation. Replace the old Shop cashback step; never call both.

Environment on the Shop bot:
  NYAN_SHOP_CASHBACK_SECRET: same >=32-char secret as the Wallet backend
  NYAN_WALLET_CASHBACK_URL: wallet API origin, default worker bridge
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import urllib.error
import urllib.request
from datetime import datetime, timezone

DEFAULT_API = "https://nyan-wallet-bridge.qwertsyik.workers.dev"


def record_confirmed_shop_purchase(
    *, telegram_id: int, order_id: str, paid_kopecks: int,
    purchased_at: datetime | None = None,
) -> dict:
    """Return amount of cashback. Retry with same order_id is idempotent.

    paid_kopecks is integer RUB kopecks (1 ₽ = 100 kopecks).
    The wallet determines whether to credit standard 5% or active VIP 8%
    using purchased_at, not the user's current VIP status.
    """
    secret = os.getenv("NYAN_SHOP_CASHBACK_SECRET", "").strip()
    if len(secret) < 32:
        raise RuntimeError("NYAN_SHOP_CASHBACK_SECRET is not configured")
    if not isinstance(telegram_id, int) or telegram_id <= 0:
        raise ValueError("telegram_id must be positive integer")
    if not isinstance(paid_kopecks, int) or paid_kopecks <= 0:
        raise ValueError("paid_kopecks must be positive integer")
    timestamp = (purchased_at or datetime.now(timezone.utc)).astimezone(timezone.utc)
    body = json.dumps({
        "telegram_id": telegram_id,
        "order_id": order_id,
        "paid_kopecks": paid_kopecks,
        "purchased_at": timestamp.isoformat(),
    }, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    signature = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    url = os.getenv("NYAN_WALLET_CASHBACK_URL", DEFAULT_API).rstrip("/")
    if not url.startswith("https://"):
        raise RuntimeError("The Nyan Wallet cashback endpoint must use HTTPS")
    request = urllib.request.Request(
        url + "/api/integrations/nyan-shop/cashback", data=body,
        method="POST",
        headers={"Content-Type": "application/json", "X-Nyan-Shop-Signature": signature},
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"Wallet cashback rejected purchase: HTTP {exc.code}") from exc
    if not isinstance(payload, dict) or not payload.get("ok"):
        raise RuntimeError("Wallet cashback service returned an invalid response")
    return payload
