"""Isolated interactive idea/auth/moderation/financial tests (no live DB)."""

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
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode

from fastapi.testclient import TestClient
from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, Text, func, select
from sqlalchemy.orm import Mapped, mapped_column



ROOT = Path(__file__).resolve().parents[1]
TEMP = tempfile.TemporaryDirectory(prefix="nyan-interactive-ideas-test-")
os.environ["BOT_TOKEN"] = "nyan-interactive-ideas-test-token"
os.environ["OWNER_TELEGRAM_ID"] = "999999"
os.environ["DATABASE_URL"] = "sqlite:///" + str(Path(TEMP.name) / "test.db")
os.environ["NYAN_TELEGRAM_RELAY_SECRET"] = "test" * 16

package = types.ModuleType("server")
package.__path__ = [str(ROOT / "server")]
sys.modules["server"] = package


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / "server" / filename)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


core = load("server.backend_app", "backend_app.py")


class BlockedUser(core.Base):
    __tablename__ = "blocked_users"
    telegram_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.telegram_id"), primary_key=True)


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

relay = load("server.telegram_relay", "telegram_relay.py")
ideas = load("server.interactive_ideas", "interactive_ideas.py")
core.Base.metadata.create_all(core.engine)
relay.register_telegram_relay(core.app)
ideas.register_interactive_ideas(core.app)
client = TestClient(core.app)


def signed_init(uid: int, age: int = 0):
    values = {"auth_date": str(int(time.time()) - age),
              "user": json.dumps({"id": uid, "first_name": "Участник"}, ensure_ascii=False)}
    text = "\n".join(f"{key}={value}" for key, value in sorted(values.items()))
    key = hmac.new(b"WebAppData", os.environ["BOT_TOKEN"].encode(), hashlib.sha256).digest()
    values["hash"] = hmac.new(key, text.encode(), hashlib.sha256).hexdigest()
    return urlencode(values)


def signed_widget(uid: int, age: int = 0):
    values = {"id": uid, "first_name": "Участник", "username": f"idea_{uid}",
              "auth_date": int(time.time()) - age}
    text = "\n".join(f"{key}={value}" for key, value in sorted(values.items()))
    key = hashlib.sha256(os.environ["BOT_TOKEN"].encode()).digest()
    values["hash"] = hmac.new(key, text.encode(), hashlib.sha256).hexdigest()
    return values


def widget_session(uid):
    response = client.post("/api/interactive-ideas/auth/widget", json=signed_widget(uid))
    assert response.status_code == 200, response.text
    return "browser:" + response.json()["session"]


def header(auth):
    return {"X-Telegram-Init-Data": auth}


def headers(auth):
    return auth if isinstance(auth, dict) else header(auth)


def send(auth, title="квест загадочного острова", description="Участники изучают карту, находят улики и решают задачи, чтобы победить в финале."):
    return client.post("/api/interactive-ideas", headers=headers(auth),
                       json={"title": title, "description": description})


def review(auth, ident, decision, note=None):
    return client.post(f"/api/interactive-ideas/{ident}/review", headers=headers(auth),
                       json={"decision": decision, "note": note})


assert client.get("/api/interactive-ideas/me").status_code == 401
assert send("not-a-real-signature").status_code == 401
assert client.post("/api/interactive-ideas/auth/widget", json={**signed_widget(1001), "id": 9001}).status_code == 401
assert client.post("/api/interactive-ideas/auth/widget", json=signed_widget(1001, age=1000)).status_code == 401
assert client.post("/api/interactive-ideas/auth/widget", json={**signed_widget(1001), "hash": "x" * 64}).status_code == 401

author = widget_session(1001)
admin = header(signed_init(999999))
assert client.get("/api/interactive-ideas/me", headers=header(author)).json()["can_submit"] is True
assert send(author, title="пусто", description="коротко").status_code in (400, 422)
assert client.get("/api/interactive-ideas/moderation", headers=header(author)).status_code == 403

response = send(author)
assert response.status_code == 200, response.text
first_id = response.json()["idea"]["id"]
assert response.json()["idea"]["status"] == "pending"
assert client.get("/api/interactive-ideas/me", headers=header(author)).json()["can_submit"] is False
assert send(author).status_code == 409
pending = client.get("/api/interactive-ideas/moderation", headers=admin)
assert pending.status_code == 200
assert any(idea["id"] == first_id for idea in pending.json()["ideas"])
assert review(author, first_id, "approve").status_code == 403
assert review(admin, first_id, "approve", "хорошая механика").status_code == 200
assert review(admin, first_id, "approve").status_code == 409
assert send(author).status_code == 409
approved = client.get("/api/interactive-ideas/me", headers=header(author)).json()["idea"]
assert approved["status"] == "approved" and approved["rewarded_at"]

# A previous +500 reward for an election must not block this distinct +500.
with core.SessionLocal.begin() as session:
    timestamp = core.now_utc()
    session.add(core.User(telegram_id=1002, username="existing", first_name="Тест",
                          last_name=None, balance=500, created_at=timestamp, last_seen_at=timestamp))
    session.add(core.Transaction(telegram_id=1002, amount=500, operation_type="election_reward",
                                 description="Награда за выборы", created_at=timestamp))

second_author = header(signed_init(1002))
second_id = send(second_author).json()["idea"]["id"]
assert review(admin, second_id, "approve").status_code == 200

rejected_author = widget_session(1003)
third_id = send(rejected_author).json()["idea"]["id"]
rejected = review(admin, third_id, "reject", "идея пока не подходит")
assert rejected.status_code == 200
assert client.get("/api/interactive-ideas/me", headers=header(rejected_author)).json()["idea"]["status"] == "rejected"
assert send(rejected_author).status_code == 409  # Forever, including after rejection.
assert review(admin, third_id, "reject").status_code == 409

tampered = author[:-4] + "1111"
assert client.get("/api/interactive-ideas/me", headers=header(tampered)).status_code == 401
assert client.get("/api/interactive-ideas/me", headers=header(signed_init(1003, age=7200))).status_code == 401

with core.SessionLocal.begin() as session:
    timestamp = core.now_utc()
    session.add(core.User(telegram_id=1004, username=None, first_name="Бан",
                          last_name=None, balance=0, created_at=timestamp, last_seen_at=timestamp))
    session.add(BlockedUser(telegram_id=1004))
assert send(header(signed_init(1004))).status_code == 403


def racing_submit(_):
    return send(header(signed_init(1005)))


with ThreadPoolExecutor(max_workers=5) as executor:
    results = list(executor.map(racing_submit, range(5)))
assert sum(result.status_code == 200 for result in results) == 1, [(r.status_code, r.text) for r in results]
assert sum(result.status_code == 409 for result in results) == 4
with core.SessionLocal.begin() as session:
    session.add(BlockedUser(telegram_id=1005))
with core.SessionLocal() as session:
    last_id = session.scalar(select(ideas.InteractiveIdea.id)
                             .where(ideas.InteractiveIdea.telegram_id == 1005))
assert review(admin, last_id, "approve").status_code == 403
assert review(admin, last_id, "reject").status_code == 200

with core.SessionLocal() as session:
    records = session.scalars(select(ideas.InteractiveIdea)).all()
    assert len(records) == 4
    assert len({r.telegram_id for r in records}) == 4
    rewards = session.scalars(select(core.Transaction)
                              .where(core.Transaction.operation_type == "interactive_idea_reward")).all()
    assert len(rewards) == 2
    assert all(tx.amount == 500 and "одобрение идеи интерактива" in tx.description for tx in rewards)
    assert session.get(core.User, 1001).balance == 500
    assert session.get(core.User, 1002).balance == 1000
    assert session.get(core.User, 1003).balance == 0
    assert session.get(core.User, 1004).balance == 0
    assert session.scalar(select(func.count()).select_from(WalletNotification)) == 2
    outbox = session.scalars(select(relay.TelegramRelayMessage)).all()
    assert any(message.source_key.startswith("transaction:") and message.chat_id == 1001 for message in outbox)
    assert any(message.chat_id == 999999 and "Новая идея" in message.body for message in outbox)

preflight = client.options("/api/interactive-ideas", headers={
    "Origin": "https://qwertsyik0.github.io",
    "Access-Control-Request-Method": "POST",
    "Access-Control-Request-Headers": "X-Telegram-Init-Data,Content-Type",
})
assert preflight.status_code == 200

print("PASS: widget HMAC, Mini App HMAC, owner-only moderation, 500 paws, reject forever, history, race, bans, relay and CORS")
TEMP.cleanup()
