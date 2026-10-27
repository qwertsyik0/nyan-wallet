"""One-time Nyan Shop curator applications, reviewed only by the wallet owner.

No wallet privileges, salaries or balances are modified by this module.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, mapped_column

from . import backend_app as core


router = APIRouter()
_REGISTERED = False
REVIEW_URL = "https://qwertsyik0.github.io/nyan-wallet/curator-review.html"
BOT_USERNAME = (os.getenv("NYAN_BOT_USERNAME") or "nyancash_bot").strip().lstrip("@")
REVIEW_DEEP_LINK = f"https://t.me/{BOT_USERNAME}?startapp=curator_review"
ANSWER_KEYS = (
    "experience", "admin_control", "pr_control", "payroll",
    "friend_violation", "fake_pr_reports", "staff_conflict", "overpayment",
    "owner_absent", "blackmail", "owner_disagreement", "motivation",
)
STATUSES = {"pending", "interview", "rejected"}


class CuratorApplication(core.Base):
    __tablename__ = "curator_applications"
    __table_args__ = (UniqueConstraint("telegram_id", name="uq_curator_app_telegram_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telegram_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.telegram_id", ondelete="CASCADE"), nullable=False, index=True,
    )
    display_name: Mapped[str] = mapped_column(String(64), nullable=False)
    age: Mapped[int] = mapped_column(Integer, nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False)
    availability: Mapped[str] = mapped_column(String(100), nullable=False)
    answers_json: Mapped[str] = mapped_column(Text, nullable=False)
    accepted_rules_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending", index=True)
    owner_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    owner_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    candidate_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ApplyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    display_name: str = Field(min_length=2, max_length=64)
    age: int = Field(ge=13, le=99)
    timezone: str = Field(min_length=2, max_length=64)
    availability: str = Field(min_length=2, max_length=100)
    answers: dict[str, str] = Field(min_length=len(ANSWER_KEYS), max_length=len(ANSWER_KEYS))
    rules_accepted: Literal[True]


class ReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision: Literal["interview", "rejected"]
    score: int = Field(ge=0, le=100)
    owner_note: str | None = Field(default=None, max_length=1500)
    candidate_note: str | None = Field(default=None, max_length=500)


def _clean(raw: str, *, low: int, high: int, label: str) -> str:
    value = " ".join(raw.split())
    if len(value) < low or len(value) > high:
        raise HTTPException(status_code=422, detail=f"{label}: требуется от {low} до {high} символов")
    return value


def _clean_answer(raw: str) -> str:
    # Keep paragraphs in substantive answers; normalize only excess spacing.
    value = "\n".join(" ".join(line.split()) for line in raw.splitlines() if line.strip())
    if not 40 <= len(value) <= 1800:
        raise HTTPException(status_code=422, detail="Каждый развёрнутый ответ: от 40 до 1800 символов")
    return value


def _answers(payload: ApplyRequest) -> dict[str, str]:
    if set(payload.answers) != set(ANSWER_KEYS):
        raise HTTPException(status_code=422, detail="Пожалуйста, ответьте на все 15 вопросов")
    return {key: _clean_answer(payload.answers[key]) for key in ANSWER_KEYS}


def _auth(value: str | None, *, owner: bool = False) -> dict:
    user = core.verify_init_data(value or "", require_subscription=False)
    if owner:
        core.require_owner(user)
    return user


def _public(row: CuratorApplication) -> dict:
    return {
        "id": row.id, "status": row.status,
        "created_at": row.created_at.isoformat(),
        "reviewed_at": row.reviewed_at.isoformat() if row.reviewed_at else None,
        "candidate_note": row.candidate_note,
    }


def _owner_row(row: CuratorApplication, user: core.User, *, full: bool = False) -> dict:
    data = {
        **_public(row), "telegram_id": row.telegram_id,
        "username": user.username, "first_name": user.first_name,
        "display_name": row.display_name, "age": row.age,
        "timezone": row.timezone, "availability": row.availability,
        "owner_score": row.owner_score, "owner_note": row.owner_note,
    }
    if full:
        data["answers"] = json.loads(row.answers_json)
        data["accepted_rules_at"] = row.accepted_rules_at.isoformat()
    return data


def _enqueue(session, key: str, chat_id: int | None, body: str) -> None:
    """Durably enqueue only once; share the application database transaction."""
    if not chat_id:
        return
    from .telegram_relay import TelegramRelayMessage, _new_message, relay_enabled
    if relay_enabled():
        session.add(TelegramRelayMessage(**_new_message(key, chat_id, body)))


@router.get("/api/recruitment/curator/me")
def my_application(x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data")):
    user = _auth(x_telegram_init_data)
    with core.SessionLocal() as session:
        row = session.scalar(select(CuratorApplication).where(CuratorApplication.telegram_id == user["id"]))
        return {"ok": True, "application": _public(row) if row else None}


@router.post("/api/recruitment/curator/apply", status_code=201)
def submit_application(
    payload: ApplyRequest,
    x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data"),
):
    user = _auth(x_telegram_init_data)
    answers = _answers(payload)
    display_name = _clean(payload.display_name, low=2, high=64, label="Имя")
    timezone = _clean(payload.timezone, low=2, high=64, label="Часовой пояс")
    availability = _clean(payload.availability, low=2, high=100, label="Время работы")
    # The existing wallet profile is used only as an authenticated Telegram identity.
    core.get_or_create_user(user)
    timestamp = core.now_utc()
    try:
        with core.SessionLocal.begin() as session:
            if session.scalar(select(CuratorApplication.id).where(CuratorApplication.telegram_id == user["id"])):
                raise HTTPException(status_code=409, detail="Вы уже отправили анкету. Повторная подача запрещена")
            row = CuratorApplication(
                telegram_id=user["id"], display_name=display_name, age=payload.age,
                timezone=timezone, availability=availability,
                answers_json=json.dumps(answers, ensure_ascii=False),
                accepted_rules_at=timestamp, status="pending", created_at=timestamp,
            )
            session.add(row)
            session.flush()
            result = _public(row)
            name = f"@{user['username']}" if user.get("username") else display_name
            _enqueue(
                session, f"curator:application:{row.id}:owner", core.OWNER_TELEGRAM_ID,
                "📋 Новая анкета на куратора Nyan Shop\n"
                f"Заявка №{row.id}\nКандидат: {name}\nTelegram ID: {user['id']}\n"
                f"Ответы и оценка: {REVIEW_DEEP_LINK}",
            )
    except IntegrityError as exc:
        # Database uniqueness also prevents two concurrent first submissions.
        raise HTTPException(status_code=409, detail="Вы уже отправили анкету. Повторная подача запрещена") from exc
    return {"ok": True, "application": result}


@router.get("/api/owner/recruitment/curator")
def list_applications(
    status: str = Query(default="pending", max_length=20),
    x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data"),
):
    _auth(x_telegram_init_data, owner=True)
    if status not in STATUSES | {"all"}:
        raise HTTPException(status_code=400, detail="Неизвестный статус")
    with core.SessionLocal() as session:
        query = (
            select(CuratorApplication, core.User)
            .join(core.User, core.User.telegram_id == CuratorApplication.telegram_id)
            .order_by(CuratorApplication.id.desc()).limit(200)
        )
        if status != "all":
            query = query.where(CuratorApplication.status == status)
        return {"ok": True, "applications": [
            _owner_row(row, user) for row, user in session.execute(query)
        ]}


@router.get("/api/owner/recruitment/curator/{application_id}")
def get_application(
    application_id: int,
    x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data"),
):
    _auth(x_telegram_init_data, owner=True)
    with core.SessionLocal() as session:
        result = session.execute(
            select(CuratorApplication, core.User)
            .join(core.User, core.User.telegram_id == CuratorApplication.telegram_id)
            .where(CuratorApplication.id == application_id)
        ).first()
        if not result:
            raise HTTPException(status_code=404, detail="Анкета не найдена")
        return {"ok": True, "application": _owner_row(*result, full=True)}


@router.post("/api/owner/recruitment/curator/{application_id}/review")
def review_application(
    application_id: int,
    payload: ReviewRequest,
    x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data"),
):
    _auth(x_telegram_init_data, owner=True)
    owner_note = _clean(payload.owner_note, low=1, high=1500, label="Заметка") if payload.owner_note and payload.owner_note.strip() else None
    candidate_note = _clean(payload.candidate_note, low=1, high=500, label="Сообщение кандидату") if payload.candidate_note and payload.candidate_note.strip() else None
    with core.SessionLocal.begin() as session:
        row = session.scalar(select(CuratorApplication).where(CuratorApplication.id == application_id).with_for_update())
        if row is None:
            raise HTTPException(status_code=404, detail="Анкета не найдена")
        if row.status != "pending":
            raise HTTPException(status_code=409, detail="Анкета уже рассмотрена. Изменение решения закрыто")
        row.status = payload.decision
        row.owner_score = payload.score
        row.owner_note = owner_note
        row.candidate_note = candidate_note
        row.reviewed_at = core.now_utc()
        status_text = ("Вас приглашают на собеседование" if payload.decision == "interview"
                       else "Ваша анкета не прошла отбор")
        _enqueue(
            session, f"curator:application:{row.id}:result", row.telegram_id,
            "🐾 Nyan Shop · Отбор куратора\n" + status_text
            + (f"\nКомментарий: {candidate_note}" if candidate_note else ""),
        )
        result = _public(row)
    return {"ok": True, "application": result}


def register_curator_recruitment(app) -> None:
    global _REGISTERED
    if _REGISTERED:
        return
    CuratorApplication.__table__.create(bind=core.engine, checkfirst=True)
    app.include_router(router)
    _REGISTERED = True
