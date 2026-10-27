"""Fortune financial regression test on a disposable SQLite database only."""

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
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlencode

from fastapi import HTTPException
from sqlalchemy import BigInteger, ForeignKey, func, select
from sqlalchemy.orm import Mapped, mapped_column


ROOT = Path(__file__).resolve().parents[1]
TEMP = tempfile.TemporaryDirectory(prefix="nyan-fortune-tests-")
os.environ["BOT_TOKEN"] = "nyan-fortune-test-token"
os.environ["OWNER_TELEGRAM_ID"] = "999999"
os.environ["DATABASE_URL"] = "sqlite:///" + str(Path(TEMP.name) / "test.db")
os.environ["NYAN_TELEGRAM_RELAY_SECRET"] = "f" * 64

package = types.ModuleType("server")
package.__path__ = [str(ROOT / "server")]
sys.modules["server"] = package


def load(name: str, file: str):
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
relay = load("server.telegram_relay", "telegram_relay.py")
fortune = load("server.fortune", "fortune.py")
relay.register_telegram_relay(core.app)
fortune.register_fortune(core.app)
core.Base.metadata.create_all(core.engine)


def token(uid):
    fields = {"auth_date": str(int(time.time())),
              "user": json.dumps({"id": uid, "first_name": "Nyan Test"})}
    string = "\n".join(f"{key}={value}" for key, value in sorted(fields.items()))
    secret = hmac.new(b"WebAppData", os.environ["BOT_TOKEN"].encode(), hashlib.sha256).digest()
    fields["hash"] = hmac.new(secret, string.encode(), hashlib.sha256).hexdigest()
    return urlencode(fields)


def rejects(fn, code):
    try:
        fn()
    except HTTPException as error:
        assert error.status_code == code, (error.status_code, error.detail)
    else:
        raise AssertionError(f"Expected HTTP {code}")


def status(uid=1001):
    return fortune.fortune_status(x_telegram_init_data=token(uid))


def spin(uid=1001, key="a" * 32):
    return fortune.fortune_spin(fortune.SpinRequest(request_key=key), x_telegram_init_data=token(uid))


assert "/api/fortune" in core.app.openapi()["paths"]
assert "/api/fortune/spin" in core.app.openapi()["paths"]
rejects(lambda: fortune.fortune_status(x_telegram_init_data=None), 401)
assert status()["available"]
assert tuple(status()["sectors"]) == (10, 25, 50, 100, 0, 200, 25, 500)
rejects(lambda: spin(key="a" * 15 + "!"), 422)

with patch.object(fortune.secrets, "randbelow", return_value=5):
    first = spin()
assert first["spin"]["sector_index"] == 5 and first["spin"]["reward"] == 200
assert first["spin"]["balance_after"] == 200
assert not first["duplicate"]

with patch.object(fortune.secrets, "randbelow", side_effect=AssertionError("RNG invoked on replay")):
    again = spin()
assert again["duplicate"] and again["spin"] == first["spin"]
rejects(lambda: spin(key="b" * 32), 409)
assert not status()["available"]

with core.SessionLocal() as session:
    user = session.get(core.User, 1001)
    assert user.balance == 200
    tx = session.scalars(select(core.Transaction).where(core.Transaction.telegram_id == 1001)).all()
    assert len(tx) == 1 and tx[0].amount == 200 and tx[0].operation_type == "fortune_spin"
    notices = session.scalars(select(relay.TelegramRelayMessage)).all()
    assert len(notices) == 2  # one user + one owner; both from the same ledger write
    assert any("+200 🐾" in notice.body for notice in notices)

with core.SessionLocal.begin() as session:
    old = session.get(fortune.FortuneSpin, first["spin"]["id"])
    old.spun_at = core.now_utc() - timedelta(hours=25)
assert status()["available"]

with patch.object(fortune.secrets, "randbelow", return_value=4):
    zero = spin(key="c" * 32)
assert zero["spin"]["reward"] == 0
assert zero["spin"]["balance_after"] == 200
assert status()["last_spin"]["id"] == zero["spin"]["id"]
assert spin(key="c" * 32)["duplicate"]

with core.SessionLocal() as session:
    assert session.get(core.User, 1001).balance == 200
    assert session.scalar(select(func.count()).select_from(core.Transaction)) == 1
    assert session.scalar(select(func.count()).select_from(relay.TelegramRelayMessage)) == 2

with core.SessionLocal.begin() as session:
    user = core.User(telegram_id=1002, username=None, first_name="Banned", last_name=None,
                     balance=300, created_at=core.now_utc(), last_seen_at=core.now_utc())
    session.add(user)
    session.flush()
    session.add(BlockedUser(telegram_id=1002))
assert status(1002)["blocked"]
rejects(lambda: spin(uid=1002), 403)

with core.SessionLocal.begin() as session:
    user = core.User(telegram_id=1003, username=None, first_name="Max", last_name=None,
                     balance=fortune.MAX_BALANCE - 100, created_at=core.now_utc(), last_seen_at=core.now_utc())
    session.add(user)
with patch.object(fortune.secrets, "randbelow", return_value=7):
    rejects(lambda: spin(uid=1003), 409)
with core.SessionLocal() as session:
    assert session.get(core.User, 1003).balance == fortune.MAX_BALANCE - 100
    assert session.scalar(select(func.count()).select_from(fortune.FortuneSpin).where(
        fortune.FortuneSpin.telegram_id == 1003)) == 0

print("OK: 24h cooldown, auth, retry, payout, zero sector, ban, balance cap, relay outbox")
