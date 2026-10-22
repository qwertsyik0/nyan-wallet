"""Isolated quote reward tests: real Telegram HMAC, balance and idempotency.

Does not import the production `server` package initializer or access live data.
"""

from __future__ import annotations

import hashlib
import hmac
import importlib.util
import json
import os
import sys
import tempfile
import time
import types
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode

from fastapi.testclient import TestClient
from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, Text, func, select
from sqlalchemy.orm import Mapped, mapped_column


ROOT = Path(__file__).resolve().parents[1]
TEMP = tempfile.TemporaryDirectory(prefix="nyan-quote-test-")
os.environ["BOT_TOKEN"] = "quote-hmac-test-token"
os.environ["DATABASE_URL"] = "sqlite:///" + str(Path(TEMP.name) / "wallet.db")

# Loading `server` itself would run production jobs; load only core + quote.
pkg = types.ModuleType("server")
pkg.__path__ = [str(ROOT / "server")]
sys.modules["server"] = pkg


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


core = load_module("server.backend_app", ROOT / "server/backend_app.py")


class BlockedUser(core.Base):
    __tablename__ = "blocked_users"
    telegram_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.telegram_id"), primary_key=True
    )


class WalletNotification(core.Base):
    __tablename__ = "wallet_notifications"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.telegram_id"))
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    is_read: Mapped[bool] = mapped_column(Boolean, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


bans = types.ModuleType("server.user_bans")
bans.BlockedUser = BlockedUser
sys.modules["server.user_bans"] = bans
advanced = types.ModuleType("server.advanced_features")
advanced.WalletNotification = WalletNotification
sys.modules["server.advanced_features"] = advanced

quote = load_module("server.quote_reflection", ROOT / "server/quote_reflection.py")
quote.register_quote_reflection(core.app)
core.Base.metadata.create_all(core.engine)
client = TestClient(core.app)


def signed_data(user_id: int, *, age: int = 0):
    payload = {
        "auth_date": str(int(time.time()) - age),
        "user": json.dumps({"id": user_id, "first_name": "Тест"}, ensure_ascii=False),
    }
    check_string = "\n".join(f"{k}={v}" for k, v in sorted(payload.items()))
    secret = hmac.new(b"WebAppData", os.environ["BOT_TOKEN"].encode(), hashlib.sha256).digest()
    payload["hash"] = hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()
    return urlencode(payload)


def get(user_id: int):
    return client.get("/api/quote-reflection/status", headers={"X-Telegram-Init-Data": signed_data(user_id)})


def post(user_id: int, answer: str):
    return client.post("/api/quote-reflection/submit", json={"answer": answer},
                       headers={"X-Telegram-Init-Data": signed_data(user_id)})


assert client.get("/api/quote-reflection/status").status_code == 401
assert client.post("/api/quote-reflection/submit", json={"answer": "unseen_effort"}).status_code == 401
assert client.get("/api/quote-reflection/status", headers={"X-Telegram-Init-Data": "user=1001"}).status_code == 401
forged = signed_data(1001).replace("1001", "9999")
assert client.get("/api/quote-reflection/status", headers={"X-Telegram-Init-Data": forged}).status_code == 401
assert client.get("/api/quote-reflection/status", headers={"X-Telegram-Init-Data": signed_data(1001, age=7200)}).status_code == 401
assert post(1001, "not_an_option").status_code == 400
assert get(1001).json()["completed"] is False

# Existing +200 from another event is deliberately not an exclusion condition.
with core.SessionLocal.begin() as session:
    session.add(core.User(telegram_id=1001, username="existing", first_name="Тест",
                          last_name=None, balance=200, created_at=core.now_utc(),
                          last_seen_at=core.now_utc()))
    session.add(core.Transaction(telegram_id=1001, amount=200,
                                 operation_type="election_reward",
                                 description="Прошлое участие в выборах",
                                 created_at=core.now_utc()))

response = post(1001, "unseen_effort")
assert response.status_code == 200, response.text
assert response.json()["already_completed"] is False
assert response.json()["balance"] == 400
assert get(1001).json()["completed"] is True
repeat = post(1001, "one_mistake")
assert repeat.status_code == 200, repeat.text
assert repeat.json()["already_completed"] is True
assert repeat.json()["balance"] == 400

for uid, answer in zip((1002, 1003, 1004), ("other_opinion", "hidden_loneliness", "one_mistake")):
    result = post(uid, answer)
    assert result.status_code == 200, result.text
    assert result.json()["balance"] == 200

# Simultaneous refresh/submit on a new account must reward only once.
with ThreadPoolExecutor(max_workers=5) as executor:
    results = list(executor.map(lambda _: post(1005, "hidden_loneliness"), range(5)))
assert all(r.status_code == 200 for r in results), [(r.status_code, r.text) for r in results]
assert sum(not r.json()["already_completed"] for r in results) == 1

with core.SessionLocal.begin() as session:
    session.add(core.User(telegram_id=1006, username=None, first_name="Бан",
                          last_name=None, balance=0, created_at=core.now_utc(),
                          last_seen_at=core.now_utc()))
    session.add(BlockedUser(telegram_id=1006))
assert post(1006, "one_mistake").status_code == 403

with core.SessionLocal() as session:
    records = session.scalars(select(quote.QuoteReflectionAnswer)).all()
    assert len(records) == 5
    assert len({r.telegram_id for r in records}) == 5
    rewards = session.scalars(select(core.Transaction).where(
        core.Transaction.operation_type == "quote_reflection_reward")).all()
    assert len(rewards) == 5
    assert all(r.amount == 200 and r.description == quote.REWARD_REASON for r in rewards)
    assert session.get(core.User, 1001).balance == 400
    assert session.get(core.User, 1005).balance == 200
    assert session.get(core.User, 1006).balance == 0
    notifications = session.scalar(select(func.count()).select_from(WalletNotification))
    assert notifications == 5

preflight = client.options("/api/quote-reflection/submit", headers={
    "Origin": "https://qwertsyik0.github.io", "Access-Control-Request-Method": "POST",
    "Access-Control-Request-Headers": "X-Telegram-Init-Data,Content-Type",
})
assert preflight.status_code == 200, preflight.text

print("PASS: signed Telegram data, all four answers, existing rewards, replay, concurrent submits, bans, history and CORS")
TEMP.cleanup()
