"""Private-role Spy game for Nyan Shop Telegram voice chats.

The owner opens a round and queues a single group invitation via the existing
Telegram relay. Participants sign up using verified Telegram Mini App initData.
When the owner closes registration, a secret location and exactly one spy are
chosen atomically. A role can only be read by its own Telegram account.
"""

from __future__ import annotations

import json
import os
import secrets
from datetime import datetime

from fastapi import APIRouter, Header, HTTPException, Response
from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, Text, func, select, text
from sqlalchemy.orm import Mapped, mapped_column

from . import backend_app as core
from .telegram_relay import TelegramRelayMessage, relay_enabled


router = APIRouter()
_REGISTERED = False
_GAME_LOCK = 2026110201
DEEP_LINK = "https://t.me/nyancash_bot?startapp=nyan_spy"
LOCATIONS = (
    "заброшенный отель", "космическая станция", "киностудия", "больница",
    "ночной поезд", "музей", "цирк", "подводная лодка", "аэропорт",
    "секретная лаборатория", "школа", "парк аттракционов", "круизный лайнер",
    "полицейский участок", "ресторан", "библиотека", "замок", "зоопарк",
    "торговый центр", "съёмочная площадка", "банк", "театр", "маяк",
    "шахта", "отель", "остров", "аквапарк", "метро", "суд", "бункер",
)


class NyanSpyRound(core.Base):
    __tablename__ = "nyan_spy_rounds"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    location: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class NyanSpyParticipant(core.Base):
    __tablename__ = "nyan_spy_participants"

    round_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("nyan_spy_rounds.id", ondelete="CASCADE"), primary_key=True,
    )
    telegram_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.telegram_id", ondelete="CASCADE"), primary_key=True,
    )
    role: Mapped[str | None] = mapped_column(String(12), nullable=True)
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


def _user(init_data: str | None) -> dict:
    return core.verify_init_data(init_data or "")


def _owner(init_data: str | None) -> dict:
    user = _user(init_data)
    core.require_owner(user)
    return user


def _latest(session, lock: bool = False) -> NyanSpyRound | None:
    query = select(NyanSpyRound).order_by(NyanSpyRound.id.desc()).limit(1)
    if lock:
        query = query.with_for_update()
    return session.scalar(query)


def _serialize(session, user_id: int) -> dict:
    current = _latest(session)
    output = {"ok": True, "is_owner": core.is_owner(user_id), "phase": "idle"}
    if current is None:
        return output

    participant = session.get(NyanSpyParticipant, (current.id, user_id))
    count = session.scalar(
        select(func.count(NyanSpyParticipant.telegram_id))
        .where(NyanSpyParticipant.round_id == current.id)
    ) or 0
    output.update({
        "phase": current.status,
        "round_id": current.id,
        "players": int(count),
        "joined": participant is not None,
    })
    if current.status == "playing" and participant is not None:
        if participant.role == "spy":
            output["role"] = "spy"
        elif participant.role == "local":
            output["role"] = "local"
            output["location"] = current.location
    return output


def _lock_game(session) -> None:
    # Serialize open, join, close and finish even with multiple Uvicorn workers.
    session.execute(text("SELECT pg_advisory_xact_lock(:lock)"), {"lock": _GAME_LOCK})


def _group_id() -> int:
    value = int(os.getenv("NYAN_SPY_GROUP_ID", "4385786308").strip())
    # Telegram /c/ group IDs are displayed without the -100 supergroup prefix.
    return int("-100" + str(value)) if value > 0 else value


@router.get("/api/nyan-spy/status")
def spy_status(
    response: Response,
    x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data"),
):
    response.headers["Cache-Control"] = "no-store, private"
    tg = _user(x_telegram_init_data)
    with core.SessionLocal() as session:
        return _serialize(session, int(tg["id"]))


@router.post("/api/nyan-spy/join")
def spy_join(
    response: Response,
    x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data"),
):
    response.headers["Cache-Control"] = "no-store, private"
    tg = _user(x_telegram_init_data)
    core.get_or_create_user(tg)
    user_id = int(tg["id"])
    with core.SessionLocal.begin() as session:
        _lock_game(session)
        round_ = _latest(session, lock=True)
        if round_ is None or round_.status != "registration":
            raise HTTPException(status_code=409, detail="Регистрация сейчас закрыта")
        if session.get(NyanSpyParticipant, (round_.id, user_id)) is None:
            session.add(NyanSpyParticipant(
                round_id=round_.id, telegram_id=user_id,
                role=None, joined_at=core.now_utc(),
            ))
    return {"ok": True, "joined": True}


@router.post("/api/owner/nyan-spy/open")
def spy_open(
    response: Response,
    x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data"),
):
    response.headers["Cache-Control"] = "no-store, private"
    _owner(x_telegram_init_data)
    if not relay_enabled():
        raise HTTPException(status_code=503, detail="Telegram-рассылка сейчас недоступна")

    with core.SessionLocal.begin() as session:
        _lock_game(session)
        current = _latest(session, lock=True)
        if current is not None and current.status in ("registration", "playing"):
            raise HTTPException(status_code=409, detail="Сначала заверши текущую игру")

        round_ = NyanSpyRound(status="registration", created_at=core.now_utc())
        session.add(round_)
        session.flush()
        rich = {
            "text": (
                "🕵️ ШПИОН СРЕДИ НАС\n\n"
                "Кто-то из нас не знает секретную локацию. "
                "Записывайся в игру — после закрытия регистрации роли выпадут случайно.\n\n"
                "Нажми кнопку и займи место!"
            ),
            "buttons": [{"text": "🕵️ Записаться в игру", "url": DEEP_LINK}],
        }
        session.add(TelegramRelayMessage(
            source_key=f"nyan-spy-invite:{round_.id}",
            chat_id=_group_id(),
            body="NYAN_TG_RICH_V1:" + json.dumps(rich, ensure_ascii=False),
            state="pending", attempts=0, created_at=core.now_utc(),
        ))
        game_id = round_.id
    return {"ok": True, "round_id": game_id, "queued": True}


@router.post("/api/owner/nyan-spy/close")
def spy_close(
    response: Response,
    x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data"),
):
    response.headers["Cache-Control"] = "no-store, private"
    _owner(x_telegram_init_data)
    with core.SessionLocal.begin() as session:
        _lock_game(session)
        round_ = _latest(session, lock=True)
        if round_ is None or round_.status != "registration":
            raise HTTPException(status_code=409, detail="Нет открытой регистрации")
        players = list(session.scalars(
            select(NyanSpyParticipant)
            .where(NyanSpyParticipant.round_id == round_.id)
            .with_for_update()
        ).all())
        if len(players) < 3:
            raise HTTPException(status_code=409, detail="Нужно минимум 3 участника")

        # The owner can play: the secret is not chosen until this very moment.
        spy_id = secrets.choice([p.telegram_id for p in players])
        round_.location = secrets.choice(LOCATIONS)
        round_.closed_at = core.now_utc()
        round_.status = "playing"
        for player in players:
            player.role = "spy" if player.telegram_id == spy_id else "local"

        # No secret or role is returned, including to the owner.
        return {"ok": True, "round_id": round_.id, "players": len(players), "phase": "playing"}


@router.post("/api/owner/nyan-spy/finish")
def spy_finish(
    response: Response,
    x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data"),
):
    response.headers["Cache-Control"] = "no-store, private"
    _owner(x_telegram_init_data)
    with core.SessionLocal.begin() as session:
        _lock_game(session)
        round_ = _latest(session, lock=True)
        if round_ is None or round_.status not in ("registration", "playing"):
            raise HTTPException(status_code=409, detail="Нет активной игры")
        round_.status = "finished"
        return {"ok": True, "round_id": round_.id, "phase": "finished"}


def register_nyan_spy(app) -> None:
    global _REGISTERED
    if _REGISTERED:
        return
    NyanSpyRound.__table__.create(bind=core.engine, checkfirst=True)
    NyanSpyParticipant.__table__.create(bind=core.engine, checkfirst=True)
    app.include_router(router)
    _REGISTERED = True
