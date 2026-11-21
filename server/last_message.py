"""The Last Message: public cooperative mystery for Nyan Wallet.

Isolated from balances, payments, existing task rewards and spend requests.
All contribution limits and the reveal threshold are enforced in PostgreSQL.
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, UniqueConstraint, func, select
from sqlalchemy.orm import Mapped, mapped_column

from . import backend_app as core
from .advanced_features import WalletNotification
from .extended_features import audit

router = APIRouter()
_REGISTERED = False
CAMPAIGN_ID = 1
GOAL = 60
MAX_FRAGMENTS_PER_USER = 2
MAX_FAILURES_PER_PUZZLE = 3

# The answer is validated only on the server. The frontend never gets answer indexes.
CHALLENGES = (
    ("echo", "То, что возвращается", "Я повторяю слова, хотя у меня нет голоса. Кто я?",
     ("эхо", "шёпот", "тень", "память"), 0),
    ("name", "То, что принадлежит тебе", "Это твоё, но другие произносят его чаще тебя.",
     ("секрет", "имя", "голос", "воспоминание"), 1),
    ("promise", "То, что легко разрушить", "Меня можно нарушить, даже не прикоснувшись.",
     ("стекло", "тишину", "обещание", "печать"), 2),
    ("hole", "То, что растёт", "Чем больше из меня берут, тем больше я становлюсь.",
     ("время", "память", "пламя", "яма"), 3),
    ("stamp", "То, что путешествует", "Я обхожу весь мир, но остаюсь в углу.",
     ("марка", "стрелка", "луна", "ключ"), 0),
    ("knowledge", "То, что не кончается", "Чем больше мной делятся, тем больше меня становится.",
     ("золото", "знания", "чернила", "бумага"), 1),
)

STORY = (
    "вы действительно думали, что собирали фрагменты, чтобы открыть это письмо?\n\n"
    "нет.\n\n"
    "вы собирали их, чтобы меня освободить.\n\n"
    "спасибо за помощь.\n\n"
    "до скорой встречи."
)


class LastMessageCampaign(core.Base):
    __tablename__ = "nyan_last_message_campaign"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    goal: Mapped[int] = mapped_column(Integer, nullable=False, default=GOAL)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class LastMessageFragment(core.Base):
    __tablename__ = "nyan_last_message_fragments"
    __table_args__ = (UniqueConstraint("telegram_id", "challenge_code", name="uq_nyan_last_message_fragment"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.telegram_id", ondelete="CASCADE"), nullable=False, index=True)
    challenge_code: Mapped[str] = mapped_column(String(24), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class LastMessageAttempt(core.Base):
    __tablename__ = "nyan_last_message_attempts"
    __table_args__ = (UniqueConstraint("telegram_id", "challenge_code", name="uq_nyan_last_message_attempt"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.telegram_id", ondelete="CASCADE"), nullable=False, index=True)
    challenge_code: Mapped[str] = mapped_column(String(24), nullable=False)
    failed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class SolvePayload(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    challenge: str
    choice: int


class ControlPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    action: Literal["pause", "resume", "reveal"]


def _auth(value: str | None) -> dict:
    return core.verify_init_data(value or "")


def _campaign(session, *, lock=False) -> LastMessageCampaign:
    query = select(LastMessageCampaign).where(LastMessageCampaign.id == CAMPAIGN_ID)
    if lock:
        query = query.with_for_update()
    state = session.scalar(query)
    if not state:
        raise HTTPException(status_code=503, detail="Событие ещё не инициализировано")
    return state


def _snapshot(session, state: LastMessageCampaign, tg: dict) -> dict:
    user_id = int(tg["id"])
    owned = list(session.scalars(select(LastMessageFragment.challenge_code).where(
        LastMessageFragment.telegram_id == user_id
    )).all())
    failures = dict(session.execute(select(
        LastMessageAttempt.challenge_code, LastMessageAttempt.failed_count
    ).where(LastMessageAttempt.telegram_id == user_id)).all())
    collected = int(session.scalar(select(func.count()).select_from(LastMessageFragment)) or 0)
    people = int(session.scalar(select(func.count(func.distinct(LastMessageFragment.telegram_id)))) or 0)
    opened = state.status == "revealed"
    puzzles = [
        {
            "id": code, "title": title, "question": question,
            "choices": list(options),
            "solved": code in owned,
            "attempts_left": max(0, MAX_FAILURES_PER_PUZZLE - int(failures.get(code, 0))),
        }
        for code, title, question, options, _ in CHALLENGES
    ]
    return {
        "ok": True,
        "status": state.status,
        "goal": state.goal,
        "collected": collected,
        "participants": people,
        "my_fragments": len(owned),
        "my_limit": MAX_FRAGMENTS_PER_USER,
        "witness": opened and bool(owned),
        "opened_at": state.opened_at.isoformat() if state.opened_at else None,
        "letter": STORY if opened else None,
        "challenges": puzzles,
        "is_owner": core.is_owner(user_id),
    }


def _reveal(session, state: LastMessageCampaign) -> None:
    if state.status == "revealed":
        return
    state.status = "revealed"
    state.opened_at = core.now_utc()
    users = session.scalars(select(LastMessageFragment.telegram_id).distinct()).all()
    for telegram_id in users:
        session.add(WalletNotification(
            telegram_id=telegram_id, kind="last_message",
            title="Последнее сообщение раскрыто",
            body="Печать сломана. Письмо открыто. Вам доступен памятный знак «Свидетель».",
            is_read=False, created_at=core.now_utc(),
        ))


@router.get("/api/last-message")
def last_message(x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data")):
    tg = _auth(x_telegram_init_data)
    with core.SessionLocal() as session:
        return _snapshot(session, _campaign(session), tg)


@router.post("/api/last-message/solve")
def solve(payload: SolvePayload, x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data")):
    tg = _auth(x_telegram_init_data)
    challenge = next((item for item in CHALLENGES if item[0] == payload.challenge), None)
    if challenge is None or type(payload.choice) is not int or not 0 <= payload.choice < len(challenge[3]):
        raise HTTPException(status_code=400, detail="Некорректный фрагмент или ответ")

    user_id = int(tg["id"])
    with core.SessionLocal.begin() as session:
        state = _campaign(session, lock=True)
        if state.status != "active":
            raise HTTPException(status_code=409, detail="Сбор фрагментов сейчас закрыт")
        existing = session.scalar(select(core.User).where(core.User.telegram_id == user_id).with_for_update())
        if existing is None:
            session.add(core.User(
                telegram_id=user_id, username=tg.get("username"),
                first_name=tg.get("first_name") or "Пользователь",
                last_name=tg.get("last_name"), balance=0,
                created_at=core.now_utc(), last_seen_at=core.now_utc(),
            ))
            session.flush()
        count = int(session.scalar(select(func.count()).select_from(LastMessageFragment).where(
            LastMessageFragment.telegram_id == user_id
        )) or 0)
        if count >= MAX_FRAGMENTS_PER_USER:
            raise HTTPException(status_code=409, detail="Вы уже нашли максимум фрагментов")
        already = session.scalar(select(LastMessageFragment).where(
            LastMessageFragment.telegram_id == user_id,
            LastMessageFragment.challenge_code == payload.challenge,
        ))
        if already:
            raise HTTPException(status_code=409, detail="Этот фрагмент уже найден")
        attempt = session.scalar(select(LastMessageAttempt).where(
            LastMessageAttempt.telegram_id == user_id,
            LastMessageAttempt.challenge_code == payload.challenge,
        ))
        if attempt and attempt.failed_count >= MAX_FAILURES_PER_PUZZLE:
            raise HTTPException(status_code=429, detail="Попытки для этой загадки закончились")
        if payload.choice != challenge[4]:
            if not attempt:
                attempt = LastMessageAttempt(telegram_id=user_id, challenge_code=payload.challenge, failed_count=0)
                session.add(attempt)
            attempt.failed_count += 1
            message = "Ответ не подошёл. Оставшиеся попытки: " + str(MAX_FAILURES_PER_PUZZLE - attempt.failed_count)
            success = False
        else:
            session.add(LastMessageFragment(
                telegram_id=user_id, challenge_code=payload.challenge,
                created_at=core.now_utc(),
            ))
            session.flush()
            total = int(session.scalar(select(func.count()).select_from(LastMessageFragment)) or 0)
            if total >= state.goal:
                _reveal(session, state)
            message = "Фрагмент найден и добавлен к общему письму"
            success = True
    return {"ok": success, "message": message}


@router.get("/api/owner/last-message")
def owner_last_message(x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data")):
    tg = _auth(x_telegram_init_data)
    core.require_owner(tg)
    with core.SessionLocal() as session:
        state = _campaign(session)
        contributions = session.execute(select(
            LastMessageFragment.telegram_id,
            func.count(LastMessageFragment.id),
        ).group_by(LastMessageFragment.telegram_id).order_by(
            func.count(LastMessageFragment.id).desc()
        ).limit(120)).all()
        return {
            "ok": True, "status": state.status, "goal": state.goal,
            "total": int(session.scalar(select(func.count()).select_from(LastMessageFragment)) or 0),
            "contributors": [{"telegram_id": uid, "fragments": count} for uid, count in contributions],
        }


@router.post("/api/owner/last-message/control")
def owner_control(payload: ControlPayload, x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data")):
    tg = _auth(x_telegram_init_data)
    core.require_owner(tg)
    with core.SessionLocal.begin() as session:
        state = _campaign(session, lock=True)
        previous = state.status
        if payload.action == "pause":
            if state.status != "active":
                raise HTTPException(status_code=409, detail="Можно приостановить только активное событие")
            state.status = "paused"
        elif payload.action == "resume":
            if state.status != "paused":
                raise HTTPException(status_code=409, detail="Нет приостановленного события")
            state.status = "active"
        elif payload.action == "reveal":
            _reveal(session, state)
        audit(session, "last_message_control", int(tg["id"]),
              f"Последнее сообщение: {previous} → {state.status}; команда {payload.action}")
        status = state.status
    return {"ok": True, "status": status}


def register_last_message(app) -> None:
    global _REGISTERED
    if _REGISTERED:
        return
    core.Base.metadata.create_all(core.engine, tables=[
        LastMessageCampaign.__table__,
        LastMessageFragment.__table__,
        LastMessageAttempt.__table__,
    ])
    with core.SessionLocal.begin() as session:
        if session.get(LastMessageCampaign, CAMPAIGN_ID) is None:
            session.add(LastMessageCampaign(
                id=CAMPAIGN_ID, status="active", goal=GOAL,
                created_at=core.now_utc(), opened_at=None,
            ))
    app.include_router(router)
    _REGISTERED = True
