"""FastAPI integration checks for the first Nyan Elections milestone.

A test-only backend stub avoids importing the production package initializer,
which requires PostgreSQL, bot credentials and startup jobs.
"""

from __future__ import annotations

import base64
import importlib.util
import io
import sys
import types
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException
from PIL import Image
from fastapi.testclient import TestClient
from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, create_engine, select
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
core.OWNER_TELEGRAM_ID = 1
core.BOT_TOKEN = "fake-test-token"


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

class WalletNotification(Base):
    __tablename__ = "wallet_notifications"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.telegram_id"), nullable=False)
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    body: Mapped[str] = mapped_column(String(1000), nullable=False)
    is_read: Mapped[bool] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

def fake_notify(session, telegram_id, kind, title, body):
    session.add(WalletNotification(
        telegram_id=telegram_id, kind=kind, title=title, body=body,
        is_read=False, created_at=datetime.now(timezone.utc),
    ))

advanced = types.ModuleType("server.advanced_features")
advanced.notify = fake_notify
sys.modules["server.advanced_features"] = advanced

spec = importlib.util.spec_from_file_location(
    "server.elections", ROOT / "server" / "elections.py"
)
assert spec and spec.loader
elections = importlib.util.module_from_spec(spec)
sys.modules["server.elections"] = elections
spec.loader.exec_module(elections)

delivered = []
def fake_send(chat_id, message, button_label):
    delivered.append((chat_id, message, button_label))
    return True
elections._send_party_telegram_notice = fake_send

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
image_buffer = io.BytesIO()
Image.new("RGB", (128, 128), (200, 100, 140)).save(image_buffer, "PNG")
image_data = "data:image/png;base64," + base64.b64encode(image_buffer.getvalue()).decode("ascii")
p2 = ok(post("/parties", 3, {**party("Партия Звёзд", "ПЗ"), "emblem_data": image_data}))["party_id"]
assert len(delivered) == 2
assert all(chat_id == 1 and "Рассмотреть заявку" in button for chat_id, _msg, button in delivered)
with SessionLocal() as session:
    notify_owner = session.scalars(select(WalletNotification).where(
        WalletNotification.telegram_id == 1
    )).all()
    assert len(notify_owner) == 2
    assert all(item.kind == "elections" for item in notify_owner)
ok(post("/parties", 4, {**party("Bad Picture", "BP"), "emblem_data": "data:image/png;base64,invalid"}), 422)
stored = client.get(f"/api/elections/parties/{p2}/emblem")
assert stored.status_code == 200, stored.text
assert stored.headers["content-type"].startswith("image/webp")
with Image.open(io.BytesIO(stored.content)) as result:
    assert result.format == "WEBP" and result.size == (128, 128)
assert client.get(f"/api/elections/parties/{p2+100}/emblem").status_code == 404
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
p3 = ok(post("/parties", 4, party("Партия Города", "ПГ")))["party_id"]
ok(post(f"/owner/parties/{p3}/review", 1, {"decision": "reject"}), 422)
ok(post(f"/owner/parties/{p3}/review", 1, {"decision": "reject", "note": "Не хватает конкретных предложений"}))
ok(post(f"/owner/parties/{p3}/review", 1, {"decision": "reject", "note": "Повтор"}), 409)
ok(post(f"/owner/parties/{p1}/review", 1, {"decision": "approve"}), 409)
with SessionLocal() as session:
    applicant2 = session.scalars(select(WalletNotification).where(
        WalletNotification.telegram_id == 2, WalletNotification.title == "Партия одобрена"
    )).all()
    applicant4 = session.scalars(select(WalletNotification).where(
        WalletNotification.telegram_id == 4, WalletNotification.title == "Партия отклонена"
    )).all()
    assert len(applicant2) == 1
    assert len(applicant4) == 1
    assert "Не хватает конкретных предложений" in applicant4[0].body
assert len(delivered) == 6
assert any(c == 4 and "отклонена" in m and "Не хватает конкретных предложений" in m for c,m,_ in delivered)
assert any(c == 2 and "одобрена" in m for c,m,_ in delivered)

public = ok(get("", 4))
assert len(public["parties"]) == 2
assert next(item for item in public["parties"] if item["id"] == p2)["emblem_url"] == f"/api/elections/parties/{p2}/emblem"
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

# The owner can replace their party during registration but not erase
# third-party membership. Replacement must be atomic if the new name clashes.
with SessionLocal.begin() as session:
    session.get(elections.ElectionSeason, 1).phase = "registration"
ok(post("/owner/parties/replace", 1, party("Не существует", "НС")), 409)
old = ok(post("/parties", 1, party("Старая партия", "СП")))["party_id"]
ok(post("/parties", 1, party("Лишняя партия", "ЛП")), 409)
ok(post("/owner/parties/replace", 2, party("Чужая замена", "ЧЗ")), 403)
assert ok(get("", 1))["owned_party"]["id"] == old
ok(post(f"/owner/parties/{old}/review", 1, {"decision": "approve"}))
with SessionLocal() as session:
    assert session.scalar(select(elections.ElectionMembership).where(
        elections.ElectionMembership.party_id == old,
        elections.ElectionMembership.telegram_id == 1,
    )) is not None
ok(post("/owner/parties/replace", 1, party("Партия Лапы", "СП")), 409)
assert ok(get("", 1))["owned_party"]["id"] == old
with SessionLocal.begin() as session:
    session.add(elections.ElectionMembership(
        season_id=1, party_id=old, telegram_id=5,
        joined_at=datetime.now(timezone.utc),
    ))
blocked = post("/owner/parties/replace", 1, party("Новый Союз", "НС"))
assert blocked.status_code == 409 and "участники" in blocked.json()["detail"]
assert ok(get("", 1))["owned_party"]["id"] == old
with SessionLocal.begin() as session:
    outsider = session.scalar(select(elections.ElectionMembership).where(
        elections.ElectionMembership.party_id == old,
        elections.ElectionMembership.telegram_id == 5,
    ))
    session.delete(outsider)
replacement = ok(post("/owner/parties/replace", 1, {
    **party("Новый Союз", "НС"), "emblem_data": image_data,
}))
new_party = replacement["party_id"]
assert replacement["replaced_party_id"] == old and new_party != old
assert ok(get("", 1))["owned_party"]["id"] == new_party
assert ok(get("", 1))["owned_party"]["status"] == "pending"
with SessionLocal() as session:
    assert session.get(elections.ElectionParty, old) is None
    assert session.get(elections.ElectionParty, new_party) is not None
    assert session.get(elections.ElectionPartyEmblem, new_party) is not None
    assert session.scalar(select(elections.ElectionMembership).where(
        elections.ElectionMembership.party_id == old
    )) is None
    assert session.get(elections.ElectionParty, p1) is not None
    assert session.get(elections.ElectionParty, p2) is not None
ok(post(f"/owner/parties/{new_party}/review", 1, {
    "decision":"reject", "note":"Тест успешной замены завершён."
}))
assert ok(get("", 1))["owned_party"]["status"] == "rejected"

# One-off production rollback must refuse any season containing party records.
with SessionLocal.begin() as session:
    session.query(elections.ElectionInitialRollback).delete()
    current = session.get(elections.ElectionSeason, 1)
    current.phase = "registration"
assert elections.rollback_first_empty_season_once() == "skipped_contains_party_data"
with SessionLocal() as session:
    assert session.get(elections.ElectionSeason, 1) is not None

# Clearing a *test* season verifies the one-time empty-season rollback and audit.
with SessionLocal.begin() as session:
    session.query(elections.ElectionMembership).delete()
    session.query(elections.ElectionPartyEmblem).delete()
    session.query(elections.ElectionParty).delete()
    session.query(elections.ElectionInitialRollback).delete()
assert elections.rollback_first_empty_season_once() == "empty_initial_season_rolled_back"
assert elections.rollback_first_empty_season_once() == "already_processed"
assert ok(get("", 1))["season"] is None
assert ok(get("", 1))["initial_rollback"] == "empty_initial_season_rolled_back"
assert ok(get("", 2))["season"] is None
assert "initial_rollback" not in ok(get("", 2))

print("OK: sanitized emblem upload, metadata removal, owner-only rollback audit and safe reset")

print("OK: elections registration, moderation, exclusive membership, phase guard and security")
