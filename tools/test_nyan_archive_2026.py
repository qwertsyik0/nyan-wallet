"""Offline regression test for Nyan Archive. Uses only an isolated SQLite DB."""

import importlib.util
import os
import sys
import tempfile
import types
from datetime import timedelta
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import func, select


ROOT = Path(__file__).resolve().parents[1]
temp = tempfile.TemporaryDirectory(prefix="nyan-archive-test-")
os.environ["DATABASE_URL"] = f"sqlite:///{temp.name}/archive.sqlite"
os.environ["BOT_TOKEN"] = "offline-archive-test-token"
os.environ["OWNER_TELEGRAM_ID"] = "900000"

package = types.ModuleType("server")
package.__path__ = [str(ROOT / "server")]
sys.modules["server"] = package


def load(name: str, path: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "server" / path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


core = load("server.backend_app", "backend_app.py")
archive = load("server.nyan_archive_2026", "nyan_archive_2026.py")
from server.advanced_features import WalletNotification

archive.register_nyan_archive_2026(core.app)
core.Base.metadata.create_all(core.engine)
clock = [archive.OPEN_AT - timedelta(hours=2)]
archive.now_utc = lambda: clock[0]
core.verify_init_data = lambda token: {"id": int(token), "first_name": "Тест"} if token else (_ for _ in ()).throw(
    HTTPException(status_code=401, detail="Telegram initData отсутствует")
)


def status(uid=None):
    return archive.archive_status(str(uid) if uid else None)


def solve(answer, uid=1001):
    return archive.archive_solve(archive.SolveInput(answer=answer), str(uid))


def expect_error(call, expected_status):
    try:
        call()
    except HTTPException as exc:
        assert exc.status_code == expected_status, exc
    else:
        raise AssertionError(f"Expected HTTP {expected_status}")


prelaunch = status()
assert prelaunch["is_open"] is False
assert prelaunch["authenticated"] is False
assert all(not r["available"] and "body" not in r and "note" not in r for r in prelaunch["records"])
owner = status(900000)
assert owner["owner_preview"] is True
assert all(r["available"] and "body" in r for r in owner["records"])
assert status(1001)["owner_preview"] is False
assert solve("зеркало", 900000)["correct"]  # owner can finish even before the public opening
assert status(900000)["solved"] is True
assert status(900000)["badge_awarded"] is True
assert status(900000)["first_prize_awarded"] is False
assert status(1001)["solved"] is False
expect_error(lambda: solve("зеркало"), 409)

clock[0] = archive.OPEN_AT
first = status(1001)
assert first["is_open"] is True
assert first["records"][0]["available"]
assert "body" in first["records"][0]
assert not any(r["available"] or "body" in r for r in first["records"][1:])
expect_error(lambda: solve("зеркало"), 409)

clock[0] = archive.OPEN_AT + timedelta(minutes=29)
assert [r["available"] for r in status()["records"]] == [True, False, False, False]
clock[0] = archive.OPEN_AT + timedelta(minutes=30)
assert [r["available"] for r in status()["records"]] == [True, True, False, False]
clock[0] = archive.OPEN_AT + timedelta(minutes=59)
assert [r["available"] for r in status()["records"]] == [True, True, False, False]
clock[0] = archive.OPEN_AT + timedelta(minutes=60)
assert [r["available"] for r in status()["records"]] == [True, True, True, False]
clock[0] = archive.OPEN_AT + timedelta(minutes=89)
assert [r["available"] for r in status()["records"]] == [True, True, True, False]
clock[0] = archive.OPEN_AT + timedelta(minutes=90)
assert all(r["available"] for r in status()["records"])

assert solve("ключ")["correct"] is False
assert solve("комната")["correct"] is False
assert solve("шкаф")["correct"] is False
expect_error(lambda: solve("зеркало"), 429)
clock[0] += timedelta(minutes=5)
assert solve("ЗЕРКАЛО")["correct"]
assert solve("отражение")["already_solved"]
completed = status(1001)
assert completed["solved"] is True
assert completed["badge_awarded"] is True
assert completed["first_prize_awarded"] is True
assert "дата посещения" in completed["ending"].lower()
assert not status(1002)["solved"]
assert solve("отражение", 1002)["correct"]
assert status(1002)["badge_awarded"] is True
assert status(1002)["first_prize_awarded"] is False

with core.SessionLocal() as session:
    assert session.scalar(select(func.count()).select_from(archive.ArchiveCompletion)) == 3
    assert session.scalar(select(func.count()).select_from(archive.ArchiveFirstPrize)) == 1
    assert session.get(archive.ArchiveFirstPrize, 1).telegram_id == 1001
    assert session.scalar(select(func.count()).select_from(core.Transaction)) == 1
    transaction = session.scalar(select(core.Transaction))
    assert transaction.telegram_id == 1001
    assert transaction.amount == 500
    assert transaction.operation_type == "nyan_archive_first"
    user = session.get(core.User, 1001)
    assert user.balance == 500
    assert session.get(core.User, 900000).balance == 0
    assert session.get(core.User, 1002).balance == 0

with core.SessionLocal.begin() as session:
    assert archive._grant_first_prize_if_pending(session, clock[0]) is None
with core.SessionLocal() as session:
    assert session.get(core.User, 1001).balance == 500

assert archive._normalize("ЁЖ!!!") == "еж"
print("Nyan Archive offline test: OK")
temp.cleanup()
