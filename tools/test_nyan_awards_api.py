"""Isolated NYAN AWARDS API regression tests (no Telegram/network/production DB).

Run: python tools/test_nyan_awards_api.py
"""
from __future__ import annotations

import importlib.util
import sys
import types
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import BigInteger, String, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from sqlalchemy.pool import StaticPool

ROOT = Path(__file__).resolve().parents[1]
engine = create_engine("sqlite+pysqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    telegram_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    username: Mapped[str | None] = mapped_column(String(64))


pkg = types.ModuleType("server")
pkg.__path__ = [str(ROOT / "server")]
sys.modules["server"] = pkg
core = types.ModuleType("server.backend_app")
core.Base = Base
core.engine = engine
core.SessionLocal = SessionLocal
core.now_utc = lambda: datetime.now(timezone.utc)
core.get_or_create_user = lambda tg: None


def verify(raw):
    if not raw.startswith("test-user-"):
        raise HTTPException(401, "Missing signed Telegram data")
    try:
        uid = int(raw.removeprefix("test-user-"))
    except ValueError:
        raise HTTPException(401, "Invalid signed Telegram data")
    return {"id": uid, "username": f"user{uid}", "first_name": f"User {uid}"}


core.verify_init_data = verify
core.require_owner = lambda tg: None if tg["id"] == 1 else (_ for _ in ()).throw(HTTPException(403))
sys.modules["server.backend_app"] = core
partner = types.ModuleType("server.nyan_takeover_group")
partner.group_member = lambda session, uid: uid in {1, 2, 3, 4, 5}
sys.modules["server.nyan_takeover_group"] = partner

spec = importlib.util.spec_from_file_location("server.nyan_awards_2026", ROOT / "server/nyan_awards_2026.py")
assert spec and spec.loader
awards = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = awards
spec.loader.exec_module(awards)
Base.metadata.create_all(engine)
with SessionLocal.begin() as session:
    session.add_all(User(telegram_id=uid, username=f"user{uid}") for uid in range(1, 12))

phase = ["nominations"]
awards.phase_at = lambda: phase[0]
app = FastAPI()
awards.register_nyan_awards_2026(app)
client = TestClient(app)


def call(method, route, uid=2, **body):
    result = client.request(method, route, headers={"X-Telegram-Init-Data": f"test-user-{uid}"},
                            json=body if method == "POST" else None)
    return result


def ok(method, route, uid=2, **body):
    response = call(method, route, uid, **body)
    assert response.status_code == 200, (route, response.status_code, response.text)
    return response.json()


def fail(status, method, route, uid=2, **body):
    response = call(method, route, uid, **body)
    assert response.status_code == status, (route, status, response.status_code, response.text)


# Authentication, consent and the two-category limit.
unsigned = client.get("/api/nyan-awards/status")
assert unsigned.status_code == 401
for uid in (2, 3, 4, 5):
    ok("POST", "/api/nyan-awards/nominate", uid, category="legend_nyan", nominee="me")
    ok("POST", "/api/nyan-awards/nominate", uid, category="games_legend", nominee="me")
fail(409, "POST", "/api/nyan-awards/nominate", 2, category="creator", nominee="me")
fail(403, "POST", "/api/nyan-awards/nominate", 8, category="flood_legend", nominee="me")
pending = ok("POST", "/api/nyan-awards/nominate", 6, category="admin", nominee="@user7")
fail(404, "POST", "/api/nyan-awards/confirm", 8, nomination_id=pending["nomination"]["id"], accept=True)
ok("POST", "/api/nyan-awards/confirm", 7, nomination_id=pending["nomination"]["id"], accept=True)
fail(409, "POST", "/api/nyan-awards/confirm", 7, nomination_id=pending["nomination"]["id"], accept=True)
fail(403, "GET", "/api/owner/nyan-awards/candidates", 2)
assert "results" not in ok("GET", "/api/nyan-awards/status", 2)

# Owner picks finalists, three minimum for popular ballots.
phase[0] = "review"
admin = ok("GET", "/api/owner/nyan-awards/candidates", 1)
for category in ("legend_nyan", "games_legend"):
    for nominee in [n for n in admin["candidates"] if n["category"] == category]:
        ok("POST", "/api/owner/nyan-awards/finalist", 1, nomination_id=nominee["id"], finalist=True)
fail(403, "POST", "/api/owner/nyan-awards/finalist", 2, nomination_id=1, finalist=False)
phase[0] = "voting"
ids = {n["username"]: n["id"] for n in ok("GET", "/api/owner/nyan-awards/candidates", 1)["candidates"]
        if n["category"] == "legend_nyan"}
for voter, name in ((6, "user2"), (7, "user2"), (8, "user3"), (9, "user3")):
    ok("POST", "/api/nyan-awards/vote", voter, category="legend_nyan", nomination_id=ids[name])
fail(403, "POST", "/api/nyan-awards/vote", 6, category="games_legend", nomination_id=ids["user2"])
assert "results" not in ok("GET", "/api/nyan-awards/status", 6)
assert ok("GET", "/api/nyan-awards/status", 6)["my_votes"]["legend_nyan"] == ids["user2"]

# Only tied popular ballots need human arbitration; evidence categories need a reason.
phase[0] = "ceremony_wait"
fail(422, "POST", "/api/owner/nyan-awards/winner", 1, category="face_nyan", nomination_id=1)
fail(422, "POST", "/api/owner/nyan-awards/winner", 1, category="games_legend",
     nomination_id=ids["user2"], justification="none")
game = next(n for n in ok("GET", "/api/owner/nyan-awards/candidates", 1)["candidates"]
            if n["category"] == "games_legend" and n["username"] == "user2")
ok("POST", "/api/owner/nyan-awards/winner", 1, category="games_legend",
   nomination_id=game["id"], justification="Верифицированные достижения за сезон")
ok("POST", "/api/owner/nyan-awards/winner", 1, category="legend_nyan",
   nomination_id=ids["user2"], justification="Равенство голосов")
assert "results" not in ok("GET", "/api/nyan-awards/status", 6)

phase[0] = "results"
results = ok("GET", "/api/nyan-awards/status", 6)["results"]
assert next(row for row in results if row["id"] == ids["user2"])["winner"]
assert next(row for row in results if row["id"] == game["id"])["winner"]
assert sum(row["winner"] for row in results if row["category"] == "legend_nyan") == 1
assert sum(row["winner"] for row in results if row["category"] == "games_legend") == 1
fail(409, "POST", "/api/owner/nyan-awards/winner", 1, category="legend_nyan",
     nomination_id=ids["user3"])
print("OK: real API auth, nominations, consent, caps, owner, finals, votes, secrecy, ties and laureates")
