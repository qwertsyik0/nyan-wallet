"""One-click registration for host-led NYAN horror stories.

The bot opens registration in its current group, verified Telegram Mini App
users join once per round, and the durable relay notifies the owner of every
new participant. No character data or story gameplay is stored here.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from datetime import datetime

from fastapi import APIRouter, Header, HTTPException, Response
from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, func, select, text
from sqlalchemy.orm import Mapped, mapped_column

from . import backend_app as core
from .telegram_relay import TelegramRelayMessage, relay_enabled


router = APIRouter()
_REGISTERED = False
_LOCK = 2026110705
INVITE_URL = "https://t.me/nyancash_bot?startapp=nyan_story"


class NyanStoryRound(core.Base):
    __tablename__ = "nyan_story_rounds"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    group_chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class NyanStorySignup(core.Base):
    __tablename__ = "nyan_story_signups"

    round_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("nyan_story_rounds.id", ondelete="CASCADE"), primary_key=True,
    )
    telegram_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.telegram_id", ondelete="CASCADE"), primary_key=True,
    )
    username: Mapped[str] = mapped_column(String(64), nullable=False)
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


def _lock_rounds(session) -> None:
    session.execute(text("SELECT pg_advisory_xact_lock(:lock)"), {"lock": _LOCK})


def _latest(session) -> NyanStoryRound | None:
    return session.scalar(select(NyanStoryRound).order_by(NyanStoryRound.id.desc()).limit(1))


def _bot_command_chat(
    action: str, chat: str | None, timestamp: str | None, signature: str | None,
) -> int:
    try:
        chat_id, stamp = int(chat or ""), int(timestamp or "")
    except ValueError as error:
        raise HTTPException(401, "Unauthorized") from error
    if chat_id >= 0 or abs(int(time.time()) - stamp) > 120:
        raise HTTPException(401, "Unauthorized")
    secret = (core.BOT_TOKEN or "").encode("utf-8")
    message = f"nyan-story:{action}:v1:{chat_id}:{stamp}".encode("utf-8")
    expected = hmac.new(secret, message, hashlib.sha256).hexdigest()
    if not signature or not hmac.compare_digest(signature, expected):
        raise HTTPException(401, "Unauthorized")
    return chat_id


def _queue(session, *, key: str, chat_id: int, body: str) -> None:
    session.add(TelegramRelayMessage(
        source_key=key, chat_id=chat_id, body=body, state="pending",
        attempts=0, created_at=core.now_utc(),
    ))


@router.get("/api/nyan-story/status")
def story_status(
    response: Response,
    x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data"),
):
    response.headers["Cache-Control"] = "private, no-store"
    user = core.verify_init_data(x_telegram_init_data or "")
    user_id = int(user["id"])
    with core.SessionLocal() as session:
        round_ = _latest(session)
        if round_ is None:
            return {"ok": True, "phase": "idle", "username": user.get("username")}
        joined = session.get(NyanStorySignup, (round_.id, user_id)) is not None
        players = session.scalar(
            select(func.count(NyanStorySignup.telegram_id))
            .where(NyanStorySignup.round_id == round_.id)
        ) or 0
        return {
            "ok": True, "phase": round_.status, "round_id": round_.id,
            "username": user.get("username"), "joined": joined,
            "players": int(players),
        }


@router.post("/api/nyan-story/join")
def story_join(
    response: Response,
    x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data"),
):
    response.headers["Cache-Control"] = "private, no-store"
    user = core.verify_init_data(x_telegram_init_data or "")
    username = str(user.get("username") or "").strip()
    if not username:
        raise HTTPException(422, "сначала установи @username в настройках Telegram")
    if not relay_enabled() or core.OWNER_TELEGRAM_ID is None:
        raise HTTPException(503, "запись временно недоступна")

    core.get_or_create_user(user)
    user_id = int(user["id"])
    created = False
    with core.SessionLocal.begin() as session:
        _lock_rounds(session)
        round_ = _latest(session)
        if round_ is None or round_.status != "registration":
            raise HTTPException(409, "регистрация уже закрыта")
        if session.get(NyanStorySignup, (round_.id, user_id)) is None:
            session.add(NyanStorySignup(
                round_id=round_.id, telegram_id=user_id,
                username=username, joined_at=core.now_utc(),
            ))
            _queue(
                session, key=f"nyan-story-owner:{round_.id}:{user_id}",
                chat_id=int(core.OWNER_TELEGRAM_ID),
                body=(
                    "🩸 новая запись в сюжетную игру\n"
                    f"участник: @{username}\n"
                    f"telegram id: {user_id}\nнабор №{round_.id}"
                ),
            )
            created = True
        round_id = round_.id
    return {"ok": True, "joined": True, "new": created, "round_id": round_id}


@router.post("/api/internal/nyan-story/open")
def story_open_from_bot(
    x_nyan_story_chat: str | None = Header(default=None, alias="X-Nyan-Story-Chat"),
    x_nyan_story_time: str | None = Header(default=None, alias="X-Nyan-Story-Time"),
    x_nyan_story_signature: str | None = Header(default=None, alias="X-Nyan-Story-Signature"),
):
    chat_id = _bot_command_chat(
        "open", x_nyan_story_chat, x_nyan_story_time, x_nyan_story_signature,
    )
    if not relay_enabled() or core.OWNER_TELEGRAM_ID is None:
        raise HTTPException(503, "Telegram-уведомления сейчас недоступны")

    with core.SessionLocal.begin() as session:
        _lock_rounds(session)
        current = _latest(session)
        if current and current.status == "registration":
            raise HTTPException(409, "набор уже открыт; сначала закрой его через /story_close")
        round_ = NyanStoryRound(
            group_chat_id=chat_id, status="registration", created_at=core.now_utc(),
        )
        session.add(round_)
        session.flush()
        announcement = {
            "text": (
                "🩸 NYAN GAMES | СЮЖЕТНАЯ ИГРА\n\n"
                "запись открыта. придумай своего персонажа и приготовься "
                "к истории, где не всё так, как кажется.\n\n"
                "нажми кнопку, чтобы занять место."
            ),
            "buttons": [{"text": "🩸 записаться в игру", "url": INVITE_URL}],
        }
        _queue(
            session, key=f"nyan-story-invite:{round_.id}", chat_id=chat_id,
            body="NYAN_TG_RICH_V1:" + json.dumps(announcement, ensure_ascii=False),
        )
        round_id = round_.id
    return {"ok": True, "round_id": round_id, "invitation_queued": True}


@router.post("/api/internal/nyan-story/close")
def story_close_from_bot(
    x_nyan_story_chat: str | None = Header(default=None, alias="X-Nyan-Story-Chat"),
    x_nyan_story_time: str | None = Header(default=None, alias="X-Nyan-Story-Time"),
    x_nyan_story_signature: str | None = Header(default=None, alias="X-Nyan-Story-Signature"),
):
    chat_id = _bot_command_chat(
        "close", x_nyan_story_chat, x_nyan_story_time, x_nyan_story_signature,
    )
    with core.SessionLocal.begin() as session:
        _lock_rounds(session)
        current = _latest(session)
        if not current or current.status != "registration":
            raise HTTPException(409, "нет открытого набора")
        if current.group_chat_id != chat_id:
            raise HTTPException(403, "закрыть набор можно только в той же группе")
        current.status = "closed"
        current.closed_at = core.now_utc()
        players = session.scalar(
            select(func.count(NyanStorySignup.telegram_id))
            .where(NyanStorySignup.round_id == current.id)
        ) or 0
        round_id = current.id
    return {"ok": True, "round_id": round_id, "players": int(players)}


def register_nyan_story_signup(app) -> None:
    global _REGISTERED
    if _REGISTERED:
        return
    NyanStoryRound.__table__.create(bind=core.engine, checkfirst=True)
    NyanStorySignup.__table__.create(bind=core.engine, checkfirst=True)
    app.include_router(router)
    _REGISTERED = True
