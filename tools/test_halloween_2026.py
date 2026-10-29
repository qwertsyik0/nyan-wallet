"""Isolated Halloween regression checks. Never uses the production database."""

import hashlib
import hmac
import importlib.util
import json
import os
import sys
import tempfile
import time
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode

from fastapi import HTTPException
from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, func, select
from sqlalchemy.orm import Mapped, mapped_column


ROOT = Path(__file__).resolve().parents[1]
TEMP = tempfile.TemporaryDirectory(prefix="nyan-halloween-test-")
os.environ["BOT_TOKEN"] = "test-secret-for-halloween"
os.environ["DATABASE_URL"] = "sqlite:///" + str(Path(TEMP.name) / "db.sqlite")
os.environ["OWNER_TELEGRAM_ID"] = "900000"

package = types.ModuleType("server")
package.__path__ = [str(ROOT / "server")]
sys.modules["server"] = package


def load(name, file):
    spec = importlib.util.spec_from_file_location(name, ROOT / "server" / file)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


core = load("server.backend_app", "backend_app.py")


class BlockedUser(core.Base):
    __tablename__ = "blocked_users"
    telegram_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.telegram_id"), primary_key=True)


bans = types.ModuleType("server.user_bans")
bans.BlockedUser = BlockedUser
sys.modules["server.user_bans"] = bans


class WalletNotification(core.Base):
    __tablename__ = "wallet_notifications"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.telegram_id"))
    kind: Mapped[str] = mapped_column(String(50))
    title: Mapped[str] = mapped_column(String(100))
    body: Mapped[str] = mapped_column(String(500))
    is_read: Mapped[bool] = mapped_column(Boolean)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


advanced = types.ModuleType("server.advanced_features")
advanced.WalletNotification = WalletNotification
sys.modules["server.advanced_features"] = advanced
halloween = load("server.halloween_2026", "halloween_2026.py")
halloween.register_halloween_2026(core.app)
core.Base.metadata.create_all(core.engine)

clock = [halloween.START_AT - timedelta(minutes=1)]
core.now_utc = lambda: clock[0]


def token(uid):
    fields = {"auth_date": str(int(time.time())),
              "user": json.dumps({"id": uid, "username": f"nyan_{uid}", "first_name": "Тестер"})}
    string = "\n".join(f"{key}={value}" for key, value in sorted(fields.items()))
    key = hmac.new(b"WebAppData", os.environ["BOT_TOKEN"].encode(), hashlib.sha256).digest()
    fields["hash"] = hmac.new(key, string.encode(), hashlib.sha256).hexdigest()
    return urlencode(fields)


def status(uid=1001):
    return halloween.halloween_status(x_telegram_init_data=token(uid))


counter = [0]


def idempotency_key():
    counter[0] += 1
    return f"halloween_test_key_{counter[0]:08d}"


def answer(room, text, uid=1001, key=None):
    return halloween.halloween_answer(halloween.AnswerInput(room=room, answer=text,
                                    request_key=key or idempotency_key()), x_telegram_init_data=token(uid))


def buy(item, uid=1001, key=None):
    return halloween.halloween_buy(halloween.BuyInput(item=item, request_key=key or idempotency_key()),
                                    x_telegram_init_data=token(uid))


def use(room, item, uid=1001):
    return halloween.halloween_use(halloween.UseInput(room=room, item=item), x_telegram_init_data=token(uid))


def fail(call, code):
    try:
        call()
    except HTTPException as exc:
        assert exc.status_code == code, (code, exc.status_code, exc.detail)
    else:
        raise AssertionError(f"Expected HTTP {code}")


assert "/api/halloween-2026/status" in core.app.openapi()["paths"]
for uid in range(1000, 1200):
    sign, expected = halloween._puzzle(uid, 4)
    first = int(sign["lines"][0].split()[-1].rstrip("."))
    second = int(sign["lines"][1].split()[-1].rstrip("."))
    truth_counts = {choice: int(choice == first) + int(choice != second) + int(choice != first)
                    for choice in (1, 2, 3)}
    assert [choice for choice, count in truth_counts.items() if count == 1] == [int(expected)]
    cipher, word = halloween._puzzle(uid, 3)
    decoded = "".join(halloween.ALPHABET[(halloween.ALPHABET.index(ch) - cipher["shift"]) % len(halloween.ALPHABET)]
                      for ch in cipher["cipher"])
    assert decoded == word
assert status()["started"] is False and status()["pumpkins"] == 5
fail(lambda: answer(1, "17"), 409)
fail(lambda: halloween.halloween_status(x_telegram_init_data=None), 401)

clock[0] = halloween.START_AT + timedelta(minutes=1)
assert status()["active"] and status()["rooms"][0]["accessible"]
assert not status()["rooms"][1]["accessible"]
fail(lambda: answer(2, "1111"), 409)

key = idempotency_key()
first = buy("loupe", key=key)
again = buy("loupe", key=key)
assert first["state"]["pumpkins"] == 0 and again["duplicate"]
assert again["state"]["inventory"]["loupe"] == 1
fail(lambda: buy("eye"), 409)
assert use(1, "loupe")["state"]["inventory"]["loupe"] == 0
assert use(1, "loupe")["duplicate"]

# Repeat a rejected answer under the same key: an HTTP retry must not use two attempts.
wrong_key = idempotency_key()
wrong = "wrong"
assert not answer(1, wrong, key=wrong_key)["correct"]
assert not answer(1, wrong, key=wrong_key)["correct"]
assert status()["rooms"][0]["attempts"] == 1
assert not answer(1, wrong)["correct"]
locked = answer(1, wrong)
assert not locked["correct"] and locked["retry_at"]
fail(lambda: answer(1, halloween._puzzle(1001, 1)[1]), 429)
clock[0] += timedelta(minutes=6)

for room in range(1, 6):
    challenge, expected = halloween._puzzle(1001, room)
    assert challenge and expected
    for item in ("loupe", "candle", "eye"):
        assert halloween._hint(1001, room, item)
    result = answer(room, expected)
    assert result["correct"] and result["reward"] == halloween.REWARDS[room]
    assert answer(room, expected)["already_completed"]
    assert result["state"]["rooms"][room - 1]["fragment"]

assert status()["badge"]
assert status()["wallet_earned"] == 400
assert status()["pumpkins"] == 70  # Started with 5, spent 5, won 70.
assert buy("key")["state"]["inventory"]["key"] == 1
fail(lambda: buy("key"), 409)
fail(lambda: halloween.halloween_unlock(x_telegram_init_data=token(1001)), 409)

clock[0] = halloween.SECRET_AT
assert halloween.halloween_unlock(x_telegram_init_data=token(1001))["state"]["secret_unlocked"]
assert halloween.halloween_unlock(x_telegram_init_data=token(1001))["duplicate"]
assert status()["rooms"][5]["accessible"]
result = answer(6, halloween._puzzle(1001, 6)[1])
assert result["correct"] and result["state"]["wallet_earned"] == 500
assert result["state"]["final_badge"] and result["state"]["first_witness"]

with core.SessionLocal() as session:
    assert session.get(core.User, 1001).balance == 500
    assert session.scalar(select(func.count()).select_from(core.Transaction)) == 6
    assert session.scalar(select(func.sum(core.Transaction.amount))) == 500
    assert session.scalar(select(func.count()).select_from(halloween.HalloweenBadge)) == 1
    assert session.scalar(select(func.count()).select_from(WalletNotification)) == 1
    assert session.scalar(select(func.count()).select_from(halloween.HalloweenPurchase)) == 2
    assert session.scalar(select(func.count()).select_from(halloween.HalloweenEffect)) == 1

clock[0] = halloween.END_AT
assert status()["finished"]
fail(lambda: answer(6, halloween._puzzle(1001, 6)[1], uid=1002), 409)

clock[0] = halloween.START_AT + timedelta(minutes=1)
with core.SessionLocal.begin() as session:
    session.add(core.User(telegram_id=1003, username="blocked", first_name="Блок", last_name=None,
                          balance=0, created_at=clock[0], last_seen_at=clock[0]))
    session.add(BlockedUser(telegram_id=1003))
fail(lambda: answer(1, halloween._puzzle(1003, 1)[1], uid=1003), 403)

# The configured owner alone may enter the secret room even before the event
# opens, without completing rooms 1–5 or buying a key. Others remain locked.
clock[0] = halloween.START_AT - timedelta(minutes=1)
owner_status = status(900000)
assert owner_status["owner_early_access"] is True
assert owner_status["rooms"][5]["accessible"] is True
assert owner_status["active"] is False
assert status(1002)["owner_early_access"] is False
assert status(1002)["rooms"][5]["accessible"] is False
fail(lambda: halloween.halloween_unlock(x_telegram_init_data=token(1002)), 409)
assert halloween.halloween_unlock(x_telegram_init_data=token(900000))["state"]["secret_unlocked"]
owner_secret = answer(6, halloween._puzzle(900000, 6)[1], uid=900000)
assert owner_secret["correct"] and owner_secret["reward"] == 100
assert owner_secret["state"]["final_badge"] and not owner_secret["state"]["first_witness"]
assert status(1001)["final_badge"] and status(1001)["first_witness"]
assert answer(6, halloween._puzzle(900000, 6)[1], uid=900000)["already_completed"]
with core.SessionLocal() as session:
    assert session.get(core.User, 900000).balance == 100
    assert halloween.first_witness_id(session) == 1001
    assert session.get(halloween.HalloweenInventory, (900000, "key")) is None
    assert session.scalar(select(func.count()).select_from(core.Transaction).where(core.Transaction.telegram_id == 900000)) == 1

clock[0] = halloween.SECRET_AT + timedelta(minutes=1)
for room in range(1, 6):
    assert answer(room, halloween._puzzle(1002, room)[1], uid=1002)["correct"]
assert buy("key", uid=1002)["state"]["inventory"]["key"] == 1
assert halloween.halloween_unlock(x_telegram_init_data=token(1002))["state"]["secret_unlocked"]
second = answer(6, halloween._puzzle(1002, 6)[1], uid=1002)
assert second["correct"] and second["state"]["final_badge"] and not second["state"]["first_witness"]
assert status(1001)["first_witness"] and not status(900000)["first_witness"]

print("OK: signed auth, one-time grants, first regular witness, later regular completion, owner-only early access, event windows, clues, idempotent buys/answers, five-minute retry, ban, balance")
