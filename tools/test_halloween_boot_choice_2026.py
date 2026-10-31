"""Isolated Halloween boot choice regression; never touches production PostgreSQL."""

from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
import types
from datetime import datetime, timezone
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import BigInteger, DateTime, ForeignKey, Text, func, select
from sqlalchemy.orm import Mapped, mapped_column


ROOT = Path(__file__).resolve().parents[1]
tempdir = tempfile.TemporaryDirectory(prefix="nyan-halloween-choice-test-")
os.environ["BOT_TOKEN"] = "test-halloween-choice"
os.environ["DATABASE_URL"] = "sqlite:///" + str(Path(tempdir.name) / "wallet.sqlite")

package = types.ModuleType("server")
package.__path__ = [str(ROOT / "server")]
sys.modules["server"] = package


def load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "server" / filename)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


core = load("server.backend_app", "backend_app.py")


class BlockedUser(core.Base):
    __tablename__ = "blocked_users"
    telegram_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.telegram_id"), primary_key=True)
    reason: Mapped[str] = mapped_column(Text)
    blocked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


bans = types.ModuleType("server.user_bans")
bans.BlockedUser = BlockedUser
sys.modules["server.user_bans"] = bans
module = load("server.halloween_boot_choice_2026", "halloween_boot_choice_2026.py")
core.Base.metadata.create_all(core.engine)
now = datetime.now(timezone.utc)
with core.SessionLocal.begin() as session:
    for uid, balance in [(2001, 200), (2002, 450), (2003, 900)]:
        session.add(core.User(
            telegram_id=uid, first_name="Тест", last_name=None,
            username=None, balance=balance, created_at=now, last_seen_at=now,
        ))
    session.add(BlockedUser(telegram_id=2003, reason="test", blocked_at=now))
core.verify_init_data = lambda data: {"id": int(data), "first_name": "Няник"}
module.register_halloween_boot_choice_2026(core.app)
module.register_halloween_boot_choice_2026(core.app)


def choose(uid, option):
    return module.choose(module.ChoicePayload(choice=option), x_telegram_init_data=str(uid))


assert module.status(x_telegram_init_data="2001")["eligible"] is True
assert module.status(x_telegram_init_data="2003")["eligible"] is False

trick = choose(2001, "trick")
assert trick["amount"] == -400 and trick["balance"] == -200
assert not trick["repeated"]
again = choose(2001, "sweet")
assert again["repeated"] and again["amount"] == -400 and again["balance"] == -200
assert again["choice"] == "trick"

sweet = choose(2002, "sweet")
assert sweet["amount"] == 300 and sweet["balance"] == 750
assert choose(2002, "sweet")["repeated"]

try:
    choose(2003, "trick")
except HTTPException as error:
    assert error.status_code == 403
else:
    raise AssertionError("Banned users must be blocked")

with core.SessionLocal() as session:
    assert session.get(core.User, 2001).balance == -200
    assert session.get(core.User, 2002).balance == 750
    assert session.get(core.User, 2003).balance == 900
    assert session.scalar(select(func.count()).select_from(core.Transaction)) == 2
    assert session.scalar(select(func.count()).select_from(module.HalloweenBootChoice)) == 2
    assert sorted(session.scalars(select(core.Transaction.amount))) == [-400, 300]
assert not module.status(x_telegram_init_data="2001")["eligible"]
assert module.status(x_telegram_init_data="2001")["completed"]
print("Halloween choice: one-time credit/debit, repeated calls, bans and transactions OK")
tempdir.cleanup()
