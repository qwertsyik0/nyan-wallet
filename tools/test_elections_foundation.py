"""FastAPI integration checks for the first Nyan Elections milestone.

A test-only backend stub avoids importing the production package initializer,
which requires PostgreSQL, bot credentials and startup jobs.
"""

from __future__ import annotations

import importlib.util
import sys
import types
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import BigInteger, DateTime, ForeignKey, String, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from sqlalchemy.pool import StaticPool

ROOT = Path(__file__).resolve().parents[1]

engine = create_engine(
    "sqlite+pysqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    telegram_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    first_name: Mapped[str] = mapped_column(String(100), nullable=False)


class BlockedUser(Base):
    __tablename__ = "blocked_users"
    telegram_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.telegram_id"), primary_key=True
    )


pkg = types.ModuleType("server")
pkg.__path__ = [str(ROOT / "server")]
sys.modules["server"] = pkg

core = types.ModuleType("server.backend_app")
core.Base = Base
core.User = User
core.engine = engine
core.SessionLocal = SessionLocal
core.is_owner = lambda uid: uid == 1


def fake_verify(raw: str, *, require_subscription: bool = False):
    if not raw.startswith("test-user-"):
        raise HTTPException(status_code=401, detail="Telegram initData отсутствует")
    try:
        user_id = int(raw.removeprefix("test-user-"))
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="Некорректная подпись") from exc
    return {"id": user_id}


core.verify_init_data = fake_verify
sys.modules["server.backend_app"] = core

bans = types.ModuleType("server.user_bans")
bans.BlockedUser = BlockedUser
sys.modules["server.user_bans"] = bans

spec = importlib.util.spec_from_file_location(
    "server.elections", ROOT / "server" / "elections.py"
)
assert spec and spec.loader
elections = importlib.util.module_from_spec(spec)
sys.modules["server.elections"] = elections
spec.loader.exec_module(elections)

app = FastAPI()
elections.register_elections(app)
Base.metadata.create_all(engine)
with SessionLocal.begin() as session:
    for uid in (1, 2, 3, 4, 5):
        session.add(User(telegram_id=uid, first_name=f"User {uid}", username=f"user{uid}"))
    session.add(BlockedUser(telegram_id=5))

client = TestClient(app)


def post(path, uid, payload=None):
    return client.post(
        "/api/elections" + path,
        json=payload if payload is not None else {},
        headers={"X-Telegram-Init-Data": f"test-user-{uid}"},
    )


def get(path, uid):
    return client.get(
        "/api/elections" + path,
        headers={"X-Telegram-Init-Data": f"test-user-{uid}"},
    )


def ok(response, code=200):
    assert response.status_code == code, (response.status_code, response.text)
    return response.json()


def party(title, abbr):
    return {"name": title, "short_name": abbr,
            "program": "План развития сообщества: прозрачность, диалог и новые мероприятия.",
            "emblem_url": None}


assert client.get("/api/elections").status_code == 401
assert ok(get("", 2))["season"] is None
ok(post("/owner/seasons", 2, {"title": "Первая кампания"}), 403)
season = ok(post("/owner/seasons", 1, {"title": "Первая кампания"}))
assert season["phase"] == "registration"
ok(post("/owner/seasons", 1, {"title": "Второй сезон"}), 409)

p1 = ok(post("/parties", 2, party("Партия Лапы", "ПЛ")))["party_id"]
p2 = ok(post("/parties", 3, party("Партия Звёзд", "ПЗ")))["party_id"]
ok(post("/parties", 4, party("партия лапы", "XX")), 409)
ok(post("/parties", 2, party("Третья партия", "ТП")), 409)
ok(post("/parties", 5, party("Запрещённая", "ЗП")), 403)
ok(post("/parties", 4, {**party("Злой URL", "ZZ"), "emblem_url": "javascript:alert(1)"}), 422)

assert len(ok(get("/owner/pending", 1))["parties"]) == 2
ok(get("/owner/pending", 2), 403)
assert ok(get("", 4))["parties"] == []
assert len(ok(get("", 2))["applications"]) == 1

ok(post("/owner/phase", 1, {"next_phase": "recruitment"}), 409)
ok(post(f"/owner/parties/{p1}/review", 2, {"decision": "approve"}), 403)
ok(post(f"/owner/parties/{p1}/review", 1, {"decision": "approve"}))
ok(post(f"/owner/parties/{p2}/review", 1, {"decision": "approve"}))
ok(post(f"/owner/parties/{p1}/review", 1, {"decision": "approve"}), 409)

public = ok(get("", 4))
assert len(public["parties"]) == 2
assert "chair_id" not in public["parties"][0]
assert ok(get("", 2))["my_party_id"] == p1

ok(post("/owner/phase", 1, {"next_phase": "campaign"}), 409)
ok(post("/owner/phase", 1, {"next_phase": "recruitment"}))
ok(post("/parties", 4, party("Поздняя партия", "ПП")), 409)
ok(post(f"/parties/{p1}/join", 4))
ok(post(f"/parties/{p1}/join", 4), 409)
ok(post(f"/parties/{p2}/join", 4))
assert ok(get("", 4))["my_party_id"] == p2
ok(post(f"/parties/{p2}/join", 5), 403)
ok(post(f"/parties/{p2}/join", 2), 409)  # chairs can't abandon their own party
ok(post("/parties/leave", 3), 409)
ok(post("/parties/leave", 4))
assert ok(get("", 4))["my_party_id"] is None
ok(post("/parties/leave", 4), 404)
ok(post("/owner/phase", 1, {"next_phase": "campaign"}))
ok(post(f"/parties/{p1}/join", 4))
ok(post("/owner/phase", 1, {"next_phase": "voting"}), 422)

# Unimplemented critical stages must fail closed, not accidentally open live ballots.
ok(post("/vote", 4, {"party_id": p1}), 404)
assert get("/results", 4).status_code == 404

with SessionLocal() as session:
    people = session.scalars(select(elections.ElectionMembership)).all()
    assert len(people) == 3
    assert {p.telegram_id for p in people} == {2, 3, 4}
    assert {p.party_id for p in people} == {p1, p2}

print("OK: elections registration, moderation, exclusive membership, phase guard and security")
