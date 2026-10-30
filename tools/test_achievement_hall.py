"""Isolated regression: event badges can be equipped and removed, never auto-equipped."""

import asyncio
import importlib.util
import os
import sys
import tempfile
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, func, select
from sqlalchemy.orm import Mapped, mapped_column


ROOT = Path(__file__).resolve().parents[1]
temporary = tempfile.TemporaryDirectory(prefix="nyan-achievement-hall-")
os.environ["BOT_TOKEN"] = "nyan-achievement-hall-test"
os.environ["OWNER_TELEGRAM_ID"] = "900000"
os.environ["DATABASE_URL"] = "sqlite:///" + str(Path(temporary.name) / "wallet.sqlite")

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
advanced = types.ModuleType("server.advanced_features")
advanced.Referral = object
advanced.WalletNotification = object
advanced.settings = types.SimpleNamespace()
sys.modules["server.advanced_features"] = advanced
extended = types.ModuleType("server.extended_features")
extended.SpendRequest = object
extended.send_telegram_message = lambda *args, **kwargs: None
sys.modules["server.extended_features"] = extended


class HalloweenRoom(core.Base):
    __tablename__ = "halloween_2026_rooms"
    telegram_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.telegram_id"), primary_key=True)
    room: Mapped[int] = mapped_column(Integer, primary_key=True)
    solved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


def first_witness_id(session):
    ids = session.scalars(
        select(HalloweenRoom.telegram_id)
        .where(HalloweenRoom.room == 6, HalloweenRoom.solved_at.is_not(None))
        .order_by(HalloweenRoom.solved_at, HalloweenRoom.telegram_id)
    )
    return next((uid for uid in ids if not core.is_owner(uid)), None)


halloween = types.ModuleType("server.halloween_2026")
halloween.HalloweenRoom = HalloweenRoom
halloween.first_witness_id = first_witness_id
sys.modules["server.halloween_2026"] = halloween

archive = load("server.nyan_archive_2026", "nyan_archive_2026.py")
ach = load("server.achievements", "achievements.py")
core.Base.metadata.create_all(core.engine)
now = datetime.now(timezone.utc)

with core.SessionLocal.begin() as session:
    for user_id in (900000, 900001, 900002):
        session.add(core.User(
            telegram_id=user_id, first_name="Тест", last_name=None,
            username=None, balance=90, created_at=now, last_seen_at=now,
        ))
    session.add(HalloweenRoom(telegram_id=900001, room=6, solved_at=now))
    session.add(archive.ArchiveCompletion(telegram_id=900001, solved_at=now))
    session.add(ach.LimitedProfileBadge(
        telegram_id=900001, badge_key="nyan_game_unmasker", title="Разоблачитель",
        edition=2, acquired_at=now + timedelta(seconds=1),
    ))

core.verify_init_data = lambda token: {"id": int(token)}
core.get_or_create_user = lambda identity: None


def select_badge(uid, key):
    return asyncio.run(ach.select_badge(ach.BadgePayload(key=key), x_telegram_init_data=str(uid)))


def state(uid):
    with core.SessionLocal() as session:
        return ach._serialize(session, uid, {})


initial = state(900001)
assert initial["selected_badge"] is None
assert {badge["key"] for badge in initial["special_badges"]} == {
    "nyan_game_unmasker", "halloween_keeper_2026",
    "halloween_first_witness_2026", "nyan_archive_watcher_2026",
}
assert all(not badge["selected"] for badge in initial["special_badges"])
assert state(900002)["special_badges"] == []

for key in (
    "halloween_keeper_2026", "halloween_first_witness_2026",
    "nyan_game_unmasker", "nyan_archive_watcher_2026",
):
    result = select_badge(900001, key)
    assert result["selected_badge"]["key"] == key
    current = state(900001)
    assert current["selected_badge"]["key"] == key
    assert [badge["key"] for badge in current["special_badges"] if badge["selected"]] == [key]
    assert select_badge(900001, "")["selected_badge"] is None
    assert state(900001)["selected_badge"] is None

assert select_badge(900000, "secret_777")["selected_badge"]["key"] == "secret_777"
assert select_badge(900000, "")["selected_badge"] is None

for key in ("nyan_archive_watcher_2026", "nyan_game_unmasker", "halloween_keeper_2026", "secret_777"):
    try:
        select_badge(900002, key)
    except HTTPException as exc:
        assert exc.status_code == 409
    else:
        raise AssertionError(f"Unowned badge {key} must not be equipable")

with core.SessionLocal() as session:
    assert session.scalar(select(func.count()).select_from(ach.AchievementBadge)) == 0
    assert session.scalar(select(func.count()).select_from(ach.AchievementUnlock)) == 0
    assert session.scalar(select(func.count()).select_from(core.Transaction)) == 0
    assert {user.balance for user in session.scalars(select(core.User))} == {90}
    assert session.scalar(select(func.count()).select_from(ach.LimitedProfileBadge)) == 1
    assert session.scalar(select(func.count()).select_from(archive.ArchiveCompletion)) == 1

print("Achievement hall: ownership, equip, switch, remove and balance safety OK")
temporary.cleanup()
