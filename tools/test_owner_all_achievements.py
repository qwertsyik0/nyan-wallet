"""Owner cosmetics are fully available without minting achievement rewards."""

import asyncio
import importlib.util
import os
import sys
import tempfile
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, select, func
from sqlalchemy.orm import Mapped, mapped_column


ROOT = Path(__file__).resolve().parents[1]
TEMP = tempfile.TemporaryDirectory(prefix="nyan-owner-achievements-")
os.environ["BOT_TOKEN"] = "owner-achievements-test-token"
os.environ["OWNER_TELEGRAM_ID"] = "900000"
os.environ["DATABASE_URL"] = "sqlite:///" + str(Path(TEMP.name) / "wallet.sqlite")

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
advanced = types.ModuleType("server.advanced_features")
advanced.Referral = object
advanced.WalletNotification = object
advanced.settings = types.SimpleNamespace()
sys.modules["server.advanced_features"] = advanced
extended = types.ModuleType("server.extended_features")
extended.SpendRequest = object
extended.send_telegram_message = lambda *args, **kwargs: None
sys.modules["server.extended_features"] = extended


class HalloweenBadge(core.Base):
    __tablename__ = "halloween_2026_badges"
    telegram_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.telegram_id"), primary_key=True
    )
    awarded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class HalloweenRoom(core.Base):
    __tablename__ = "halloween_2026_rooms"
    telegram_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.telegram_id"), primary_key=True
    )
    room: Mapped[int] = mapped_column(Integer, primary_key=True)
    solved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


def first_witness_id(session):
    completions = session.scalars(
        select(HalloweenRoom.telegram_id)
        .where(HalloweenRoom.room == 6, HalloweenRoom.solved_at.is_not(None))
        .order_by(HalloweenRoom.solved_at.asc(), HalloweenRoom.telegram_id.asc())
    )
    return next((uid for uid in completions if not core.is_owner(uid)), None)


halloween = types.ModuleType("server.halloween_2026")
halloween.HalloweenBadge = HalloweenBadge
halloween.HalloweenRoom = HalloweenRoom
halloween.first_witness_id = first_witness_id
sys.modules["server.halloween_2026"] = halloween

ach = load("server.achievements", "achievements.py")
core.Base.metadata.create_all(core.engine)
now = datetime.now(timezone.utc)
with core.SessionLocal.begin() as session:
    for uid in (900000, 900001):
        session.add(core.User(telegram_id=uid, first_name="Тест", last_name=None,
                              username=None, balance=0, created_at=now, last_seen_at=now))
    session.add(HalloweenRoom(telegram_id=900000, room=6, solved_at=now))
    session.add(HalloweenRoom(telegram_id=900001, room=6, solved_at=now + timedelta(seconds=1)))
    session.add(HalloweenBadge(telegram_id=900000, awarded_at=now))
    session.add(HalloweenBadge(telegram_id=900001, awarded_at=now))

with core.SessionLocal() as session:
    owner = ach._serialize(session, 900000, {})
    regular = ach._serialize(session, 900001, {})
    assert owner["unlocked_count"] == owner["total"] == len(ach.ACHIEVEMENTS)
    assert all(item["unlocked"] and item["progress"] == 100 for item in owner["items"])
    assert {item["key"] for item in owner["items"] if item.get("secret")} == {
        "secret_zero", "secret_777", "secret_1000"
    }
    assert all(item["title"] != "???" for item in owner["items"])
    assert regular["unlocked_count"] == 0
    assert all(not item["unlocked"] for item in regular["items"])
    assert all(item["title"] == "???" for item in regular["items"] if item.get("secret"))
    assert [reward["key"] for reward in owner["halloween_rewards"]] == [
        "halloween_keeper_2026", "halloween_first_witness_2026"
    ]
    assert [reward["key"] for reward in regular["halloween_rewards"]] == [
        "halloween_keeper_2026", "halloween_first_witness_2026"
    ]
    assert "halloween_badge" not in owner and "halloween_badge" not in regular

# This test substitutes signed Telegram identity locally; production authentication stays unchanged.
core.verify_init_data = lambda token: {"id": int(token)}
core.get_or_create_user = lambda user: None


async def choose_badge(uid: int, key: str):
    return await ach.select_badge(ach.BadgePayload(key=key), x_telegram_init_data=str(uid))


owner_badge = asyncio.run(choose_badge(900000, "secret_777"))
assert owner_badge["selected_badge"]["title"] == "Счастливые лапки"
with core.SessionLocal() as session:
    current = ach._serialize(session, 900000, {})
    assert current["selected_badge"]["key"] == "secret_777"
    assert next(item for item in current["items"] if item["key"] == "secret_777")["selected"]

try:
    asyncio.run(choose_badge(900001, "secret_777"))
except HTTPException as exc:
    assert exc.status_code == 409
else:
    raise AssertionError("Non-owner must not select a locked secret achievement")

with core.SessionLocal() as session:
    assert session.scalar(select(func.count()).select_from(ach.AchievementUnlock)) == 0
    assert session.scalar(select(func.count()).select_from(core.Transaction)) == 0
    assert session.get(core.User, 900000).balance == 0
    assert session.get(core.User, 900001).balance == 0

print("OK: owner sees and selects all achievements, secrets revealed; regular users locked; no rewards minted")
