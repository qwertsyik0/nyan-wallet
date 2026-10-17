"""FastAPI integration checks for the first Nyan Elections milestone.

A test-only backend stub avoids importing the production package initializer,
which requires PostgreSQL, bot credentials and startup jobs.
"""

from __future__ import annotations

import base64
import importlib.util
import io
import json
import os
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
GROUP_1 = "https://t.me/+aBcDeFGh12345678"
GROUP_2 = "https://t.me/+zyxwvuts12345678"
os.environ["NYAN_ELECTIONS_GROUP_INVITES"] = json.dumps({
    "Партия Лапы": GROUP_1, "Партия Звёзд": GROUP_2,
}, ensure_ascii=False)

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
assert ok(get("", 2))["my_party_group_url"] is None  # pending parties cannot get invite
assert ok(get("", 4))["my_party_group_url"] is None
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
assert ok(get("", 2))["my_party_group_url"] == GROUP_1
assert ok(get("", 3))["my_party_group_url"] == GROUP_2
assert ok(get("", 1))["my_party_group_url"] is None
assert ok(get("", 4))["my_party_group_url"] is None
assert all("my_party_group_url" not in item and "group_url" not in item for item in ok(get("", 4))["parties"])
prior_mapping = os.environ["NYAN_ELECTIONS_GROUP_INVITES"]
os.environ["NYAN_ELECTIONS_GROUP_INVITES"] = json.dumps({"Партия Лапы": "https://example.com/unsafe"})
assert ok(get("", 2))["my_party_group_url"] is None
os.environ["NYAN_ELECTIONS_GROUP_INVITES"] = prior_mapping

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
assert ok(get("", 4))["my_party_group_url"] == GROUP_2
ok(post(f"/parties/{p2}/join", 5), 403)
ok(post(f"/parties/{p2}/join", 2), 409)  # chairs can't abandon their own party
ok(post("/parties/leave", 3), 409)
ok(post("/parties/leave", 4))
assert ok(get("", 4))["my_party_group_url"] is None
assert ok(get("", 4))["my_party_id"] is None
ok(post("/parties/leave", 4), 404)
ok(post("/owner/phase", 1, {"next_phase": "campaign"}))
ok(post(f"/parties/{p1}/join", 4))
# Games registration: party membership, explicit confirmation, strict auth,
# no automatic reward, and reconfirmation after switching party.
assert client.get("/api/elections/games/status").status_code == 401
assert client.post("/api/elections/games/confirm").status_code == 401
assert ok(get("/games/status", 4))["confirmed"] is False
assert ok(get("/games/status", 4))["reward"] == 500
assert ok(post("/games/confirm", 1), 409)
assert ok(post("/games/confirm", 5), 403)
assert ok(post("/games/confirm", 4))["confirmed"] is True
assert ok(post("/games/confirm", 4))["already_confirmed"] is True
assert ok(get("/games/status", 4))["confirmed"] is True
ok(get("/owner/games/signups", 2), 403)
assert client.get("/api/elections/owner/games/signups").status_code == 401
roster = ok(get("/owner/games/signups", 1))["signups"]
assert len(roster) == 1 and roster[0]["telegram_id"] == 4
assert roster[0]["party"] == "Партия Лапы"
ok(post(f"/parties/{p2}/join", 4))
assert ok(get("/games/status", 4))["confirmed"] is False
with SessionLocal() as session:
    assert session.query(elections.ElectionGamesSignup).count() == 0
assert ok(get("/owner/games/signups", 1))["signups"] == []
assert ok(post("/games/confirm", 4))["already_confirmed"] is False
assert ok(get("/games/status", 4))["confirmed"] is True
# Leave and rejoin the same party must never resurrect the old signup.
ok(post("/parties/leave", 4))
assert ok(get("/games/status", 4))["confirmed"] is False
assert ok(get("/owner/games/signups", 1))["signups"] == []
ok(post(f"/parties/{p2}/join", 4))
assert ok(get("/games/status", 4))["confirmed"] is False
ok(post("/games/confirm", 4))
with SessionLocal() as session:
    assert session.query(elections.ElectionGamesSignup).count() == 1
ok(post("/owner/phase", 1, {"next_phase": "voting"}), 422)

# Unimplemented critical stages must fail closed, not accidentally open live ballots.
ok(post("/vote", 4, {"party_id": p1}), 404)
assert get("/results", 4).status_code == 404

with SessionLocal() as session:
    people = session.scalars(select(elections.ElectionMembership)).all()
    assert len(people) == 3
    assert {p.telegram_id for p in people} == {2, 3, 4}
    assert {p.party_id for p in people} == {p1, p2}

# Owner is a neutral moderator: no creating or replacing party, including
# when a season is open for everyone else.
with SessionLocal.begin() as session:
    session.get(elections.ElectionSeason, 1).phase = "registration"
with SessionLocal() as session:
    existing_parties = {p.id for p in session.scalars(select(elections.ElectionParty)).all()}
    existing_notifications = session.query(WalletNotification).count()
    existing_members = session.query(elections.ElectionMembership).count()
    old_delivery_count = len(delivered)
ok(post("/parties", 1, party("Партия Владельца", "ПВ")), 403)
ok(post("/owner/parties/replace", 1, party("Замена Владельца", "ЗВ")), 403)
ok(post("/owner/parties/replace", 2, party("Чужая замена", "ЧЗ")), 403)
assert ok(get("", 1))["is_owner"] is True
assert ok(get("/owner/pending", 1))["parties"] == []
with SessionLocal() as session:
    assert {p.id for p in session.scalars(select(elections.ElectionParty)).all()} == existing_parties
    assert session.query(WalletNotification).count() == existing_notifications
    assert session.query(elections.ElectionMembership).count() == existing_members
assert len(delivered) == old_delivery_count

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
    session.query(elections.ElectionGamesSignup).delete()
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

# A user's accidental recruitment -> campaign transition is corrected
# exactly once, only in season #2. Existing parties and memberships survive.
with SessionLocal.begin() as session:
    session.query(elections.ElectionPhaseUndo20261017).delete()
    session.add(elections.ElectionSeason(
        id=2, title="Первый сезон", phase="campaign", created_by=1,
        created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc)
    ))
    session.add(elections.ElectionParty(
        id=101, season_id=2, chair_id=2,
        name="Тестовая партия", name_key="тестовая партия", short_name="ТП",
        short_key="тп", program="Полноценная предвыборная программа для проверки возврата.",
        status="approved", submitted_at=datetime.now(timezone.utc)
    ))
    session.add(elections.ElectionMembership(
        season_id=2, party_id=101, telegram_id=2, joined_at=datetime.now(timezone.utc)
    ))
with SessionLocal() as session:
    baseline_parties = session.query(elections.ElectionParty).count()
    baseline_members = session.query(elections.ElectionMembership).count()
assert elections.undo_accidental_campaign_20261017_once() == "campaign_reverted_to_recruitment"
assert ok(get("", 2))["season"]["phase"] == "recruitment"
assert ok(get("", 2))["my_party_id"] == 101
with SessionLocal() as session:
    assert session.query(elections.ElectionParty).count() == baseline_parties
    assert session.query(elections.ElectionMembership).count() == baseline_members
    audit = session.get(elections.ElectionPhaseUndo20261017, 1)
    assert audit.season_id == 2
    assert audit.status == "campaign_reverted_to_recruitment"
# Personal NSN letters target current members only, include a clickable
# profile and party group, and record each attempt to suppress duplicates.
assert elections.dispatch_nsn_member_letters_20261017()["reason"] == "approved_nsn_party_not_found"
with SessionLocal.begin() as session:
    session.add(elections.ElectionParty(
        id=102, season_id=2, chair_id=3,
        name="Народный Союз Нян", name_key="народный союз нян", short_name="НСН",
        short_key="нсн", program="Программа партии для проверки рассылки.",
        status="approved", submitted_at=datetime.now(timezone.utc)
    ))
    for telegram_id in (3, 4):
        session.add(elections.ElectionMembership(
            season_id=2, party_id=102, telegram_id=telegram_id,
            joined_at=datetime.now(timezone.utc)
        ))
prior_mapping = os.environ["NYAN_ELECTIONS_GROUP_INVITES"]
os.environ["NYAN_ELECTIONS_GROUP_INVITES"] = json.dumps({
    **json.loads(prior_mapping), "Народный Союз Нян": "https://t.me/+NsnGroupAbc123456",
}, ensure_ascii=False)
nsn_delivery = []
def fake_nsn_letter(uid, username, firstname, party_name, invite):
    nsn_delivery.append((uid, username, firstname, party_name, invite))
    return uid == 3  # Simulate a blocked bot for one recipient.
elections._send_nsn_member_letter = fake_nsn_letter
counts = elections.dispatch_nsn_member_letters_20261017()
assert counts["matched"] == 2 and counts["attempted"] == 2
assert counts["sent"] == 1 and counts["failed"] == 1
assert {x[0] for x in nsn_delivery} == {3, 4}
assert all(x[3] == "Народный Союз Нян" for x in nsn_delivery)
assert all(x[4] == "https://t.me/+NsnGroupAbc123456" for x in nsn_delivery)
html_letter = elections._nsn_member_letter_text(3, "user3", "User 3", "Народный Союз Нян", "https://t.me/+NsnGroupAbc123456")
assert '<a href="https://t.me/user3">@user3</a>' in html_letter
assert '<a href="https://t.me/+NsnGroupAbc123456">' in html_letter
assert 'tg://user?id=3' in elections._nsn_member_letter_text(
    3, None, 'Пример', "Народный Союз Нян", "https://t.me/+NsnGroupAbc123456"
)
with SessionLocal() as session:
    attempts = session.scalars(select(elections.ElectionNSNLetter20261017)).all()
    assert len(attempts) == 2
    assert {a.status for a in attempts} == {"sent", "failed"}
    assert session.query(elections.ElectionMembership).count() == baseline_members + 2
assert elections.dispatch_nsn_member_letters_20261017()["skipped"] == 2
assert len(nsn_delivery) == 2, "Resending must not duplicate successful or failed DMs"
with SessionLocal.begin() as session:
    moved = session.scalar(select(elections.ElectionMembership).where(
        elections.ElectionMembership.season_id == 2,
        elections.ElectionMembership.telegram_id == 4,
    ))
    moved.party_id = 101
assert elections.dispatch_nsn_member_letters_20261017()["matched"] == 1
assert len(nsn_delivery) == 2

# One-time group invitation across every approved party, not just NSN.
# NSN users already reached by the earlier private campaign should not
# receive a second identical invitation.
os.environ["NYAN_ELECTIONS_GROUP_INVITES"] = json.dumps({
    **json.loads(os.environ["NYAN_ELECTIONS_GROUP_INVITES"]),
    "Тестовая партия": "https://t.me/+TestParty12345678",
}, ensure_ascii=False)
group_deliveries = []
def fake_party_group_message(uid, username, firstname, party_name, invite_url):
    group_deliveries.append((uid, party_name, invite_url))
    return uid != 4  # Telegram blocked the bot for one member.
elections._send_party_group_letter = fake_party_group_message
before_group_notices = SessionLocal().query(WalletNotification).count()
stats = elections.dispatch_all_party_group_letters_20261017()
assert stats["approved_parties"] == 2 and stats["mapped_parties"] == 2
assert stats["matched"] == 3 and stats["already_notified"] == 1
assert stats["attempted"] == 2 and stats["sent"] == 1 and stats["failed"] == 1
assert {item[0] for item in group_deliveries} == {2, 4}
assert all(item[1] == "Тестовая партия" for item in group_deliveries)
assert all(item[2] == "https://t.me/+TestParty12345678" for item in group_deliveries)
letter = elections._party_group_letter_text(
    2, "user2", "User 2", "Тестовая партия", "https://t.me/+TestParty12345678"
)
assert '<a href="https://t.me/user2">@user2</a>' in letter
assert '<a href="https://t.me/+TestParty12345678">' in letter
assert 'tg://user?id=2' in elections._party_group_letter_text(
    2, None, "<Псевдоним>", "Тестовая партия", "https://t.me/+TestParty12345678"
)
assert "&lt;Псевдоним&gt;" in elections._party_group_letter_text(
    2, None, "<Псевдоним>", "Тестовая партия", "https://t.me/+TestParty12345678"
)
with SessionLocal() as session:
    records = session.scalars(select(elections.ElectionPartyGroupLetter20261017)).all()
    assert len(records) == 2
    assert {rec.status for rec in records} == {"sent", "failed"}
    assert session.query(WalletNotification).count() == before_group_notices + 2
repeat = elections.dispatch_all_party_group_letters_20261017()
assert repeat["attempted"] == 0 and repeat["already_notified"] == 1
assert repeat["skipped"] == 2 and len(group_deliveries) == 2

# Missing or unsafe group configurations cause a guarded skip, not a
# wrong invitation to members of other parties.
os.environ["NYAN_ELECTIONS_GROUP_INVITES"] = json.dumps({
    "Народный Союз Нян": "https://t.me/+NsnGroupAbc123456",
    "Тестовая партия": "https://example.net/unsafe"
}, ensure_ascii=False)
unmapped = elections.dispatch_all_party_group_letters_20261017()
assert unmapped["approved_parties"] == 2 and unmapped["mapped_parties"] == 1
assert unmapped["matched"] == 3 and len(unmapped["unmapped_parties"]) == 1
assert unmapped["unmapped_parties"][0]["name"] == "Тестовая партия"
assert len(group_deliveries) == 2

os.environ["NYAN_ELECTIONS_GROUP_INVITES"] = prior_mapping

# The intentional campaign launch must affect only the audited season #2,
# only after all four parties are approved, and never alter membership or
# re-run a phase transition on a subsequent restart.
assert elections.open_campaign_20261017_once() == "skipped_unexpected_party_count"
with SessionLocal() as session:
    assert session.get(elections.ElectionCampaignOpen20261017, 1) is None
    assert session.get(elections.ElectionSeason, 2).phase == "recruitment"
with SessionLocal.begin() as session:
    for uid in (6, 7):
        session.add(User(telegram_id=uid, first_name=f"User {uid}", username=f"user{uid}"))
    for pid, chair in ((103, 6), (104, 7)):
        session.add(elections.ElectionParty(
            id=pid, season_id=2, chair_id=chair,
            name=f"Тестовая партия {pid}", name_key=f"тестовая партия {pid}",
            short_name=f"ТП{pid}", short_key=f"тп{pid}",
            program="Полноценная программа для проверки открытия агитации.",
            status="approved", submitted_at=datetime.now(timezone.utc)
        ))
        session.add(elections.ElectionMembership(
            season_id=2, party_id=pid, telegram_id=chair,
            joined_at=datetime.now(timezone.utc),
        ))
with SessionLocal() as session:
    party_ids_before = {p.id for p in session.scalars(select(elections.ElectionParty)).all()}
    membership_before = {
        (m.telegram_id, m.party_id) for m in session.scalars(select(elections.ElectionMembership)).all()
    }
assert elections.open_campaign_20261017_once() == "campaign_opened"
assert elections.open_campaign_20261017_once() == "already_processed"
assert ok(get("", 2))["season"]["phase"] == "campaign"
with SessionLocal() as session:
    assert {p.id for p in session.scalars(select(elections.ElectionParty)).all()} == party_ids_before
    assert {(m.telegram_id, m.party_id) for m in session.scalars(select(elections.ElectionMembership)).all()} == membership_before
    audit = session.get(elections.ElectionCampaignOpen20261017, 1)
    assert audit and audit.season_id == 2 and audit.status == "campaign_opened"

assert elections.undo_accidental_campaign_20261017_once() == "already_processed"
assert ok(get("", 2))["season"]["phase"] == "campaign"

# On a different season, never revert campaign, even if the one-shot audit
# is missing due to a fresh database.
with SessionLocal.begin() as session:
    session.query(elections.ElectionPhaseUndo20261017).delete()
    session.add(elections.ElectionSeason(
        id=3, title="Другой сезон", phase="campaign", created_by=1,
        created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc)
    ))
assert elections.undo_accidental_campaign_20261017_once() == "skipped_unexpected_season"
assert ok(get("", 2))["season"]["phase"] == "campaign"
assert elections.undo_accidental_campaign_20261017_once() == "already_processed"

print("OK: sanitized emblem upload, metadata removal, owner-only rollback audit and safe reset")

assert "startapp=games" in (ROOT / "elections.html").read_text(encoding="utf-8")
assert 'id="game-owner-section"' in (ROOT / "elections-games.html").read_text(encoding="utf-8")
assert 'loadOwnerRoster()' in (ROOT / "elections-games.js").read_text(encoding="utf-8")
print("OK: elections registration, game roster authorization and invalidation, phase guard and security")
