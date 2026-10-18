"""Isolated ballot integration tests: no real Telegram, Postgres or wallets."""
from __future__ import annotations

import importlib.util
import sys
import types
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import BigInteger, ForeignKey, String, create_engine
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
    username: Mapped[str | None] = mapped_column(String(64))
    first_name: Mapped[str] = mapped_column(String(100))


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
core.BOT_TOKEN = "only-a-test-token"
core.OWNER_TELEGRAM_ID = 1
core.is_owner = lambda uid: uid == 1


def verify(raw: str, *, require_subscription=False):
    if not raw.startswith("test-user-"):
        raise HTTPException(status_code=401, detail="Не подписано")
    try:
        return {"id": int(raw.removeprefix("test-user-"))}
    except ValueError:
        raise HTTPException(status_code=401, detail="Некорректная подпись")


core.verify_init_data = verify
sys.modules["server.backend_app"] = core

bans = types.ModuleType("server.user_bans")
bans.BlockedUser = BlockedUser
sys.modules["server.user_bans"] = bans


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


elections = load_module("server.elections", ROOT / "server/elections.py")
vote = load_module("server.elections_voting", ROOT / "server/elections_voting.py")
Base.metadata.create_all(engine)

app = FastAPI()
elections.register_elections(app)
vote.register_elections_voting(app)
client = TestClient(app)

now = datetime.now(timezone.utc)
with SessionLocal.begin() as session:
    for uid in range(1, 8):
        session.add(User(
            telegram_id=uid, username=f"user{uid}", first_name=f"User {uid}"
        ))
    session.add(BlockedUser(telegram_id=7))
    session.add(elections.ElectionSeason(
        id=10, title="Выборы Нян", phase="campaign",
        created_by=1, created_at=now, updated_at=now,
    ))
    parties = [
        (10, 2, "Народный Союз Нян", "НСН"),
        (11, 3, "Партия Лап", "ПЛ"),
        (12, 4, "Союз Айристократов Парижа", "САП"),
        (13, 5, "Антонианство Шаматовский Дом", "АШД"),
    ]
    for party_id, chair_id, name, abbr in parties:
        session.add(elections.ElectionParty(
            id=party_id, season_id=10, chair_id=chair_id,
            name=name, name_key=name.casefold(),
            short_name=abbr, short_key=abbr.casefold(),
            program="Оригинальная программа партии: мероприятия и правила сообщества.",
            status="approved", submitted_at=now,
        ))
    session.add(elections.ElectionMembership(
        season_id=10, telegram_id=2, party_id=10, joined_at=now,
    ))


def get(uid: int, path="/voting/status"):
    return client.get(
        "/api/elections" + path,
        headers={"X-Telegram-Init-Data": f"test-user-{uid}"},
    )


def post(uid: int, path: str, body=None):
    return client.post(
        "/api/elections" + path, json={} if body is None else body,
        headers={"X-Telegram-Init-Data": f"test-user-{uid}"},
    )


def success(res, code=200):
    assert res.status_code == code, (res.status_code, res.text)
    return res.json()


assert client.get("/api/elections/voting/status").status_code == 401
assert success(get(2))["ballot"] == []
preview = success(get(1))
assert preview["phase"] == "campaign"
assert preview["preview"] is True
assert {p["id"] for p in preview["ballot"]} == {10, 11}
assert "program" in preview["ballot"][0]
success(post(2, "/owner/voting/open"), 403)
success(post(2, "/voting/cast", {"party_id": 10}), 409)
success(post(1, "/owner/voting/open"))
success(post(1, "/owner/voting/open"), 409)

opened = success(get(2))
assert opened["phase"] == "voting"
assert {p["id"] for p in opened["ballot"]} == {10, 11}
assert "total_votes" not in opened and "results" not in opened
success(post(6, "/voting/cast", {"party_id": 12}), 422)
success(post(7, "/voting/cast", {"party_id": 10}), 403)
success(post(999, "/voting/cast", {"party_id": 10}), 403)
success(post(6, "/voting/cast", {"party_id": "10"}), 422)

# Party members may choose another party; their affiliation does not dictate the vote.
assert success(post(2, "/voting/cast", {"party_id": 11}))["accepted"]
assert success(get(2))["my_vote_party_id"] == 11
assert success(post(2, "/voting/cast", {"party_id": 11}))["already_voted"]
success(post(2, "/voting/cast", {"party_id": 10}), 409)
assert success(post(1, "/voting/cast", {"party_id": 10}))["accepted"]
assert success(get(1))["total_votes"] == 2

# A ballot is snapshotted on opening: later edits cannot rewrite ballots.
with SessionLocal.begin() as session:
    party = session.get(elections.ElectionParty, 10)
    party.program = "Подменённая позднее программа"
snapshot = next(p for p in success(get(2))["ballot"] if p["id"] == 10)
assert "Оригинальная программа" in snapshot["program"]
assert "Подменённая" not in snapshot["program"]

success(post(2, "/owner/voting/close"), 403)
closed = success(post(1, "/owner/voting/close"))
assert closed["phase"] == "results" and closed["total_votes"] == 2
success(post(1, "/owner/voting/close"), 409)
success(post(1, "/owner/voting/open"), 409)
success(post(6, "/voting/cast", {"party_id": 10}), 409)
result = success(get(3))
assert result["phase"] == "results" and result["total_votes"] == 2
assert {p["party_id"]: p["votes"] for p in result["results"]} == {10: 1, 11: 1}
with SessionLocal() as session:
    assert session.get(vote.ElectionVote, (10, 2)).party_id == 11
    assert session.get(vote.ElectionVote, (10, 1)).party_id == 10
    assert session.get(vote.ElectionBallotControl, 10).closed_by == 1

print("OK: signed ballots, excluded parties, one immutable vote, anti-ban, owner control, closed results")
