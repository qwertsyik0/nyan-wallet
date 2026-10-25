"""Owner-managed mini-interactives: one attempt and at-most-once rewards."""

from __future__ import annotations

import json
from datetime import datetime

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import (
    BigInteger, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint,
    select,
)
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Mapped, mapped_column

from . import backend_app as core
from .user_bans import BlockedUser


router = APIRouter()
_REGISTERED = False


class Activity(core.Base):
    __tablename__ = "nyan_activities"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(110), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    choices_json: Mapped[str] = mapped_column(Text, nullable=False)
    answer_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    reward: Mapped[int] = mapped_column(Integer, nullable=False)
    max_winners: Mapped[int] = mapped_column(Integer, nullable=False)
    winner_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ActivityAnswer(core.Base):
    __tablename__ = "nyan_activity_answers"
    __table_args__ = (UniqueConstraint("activity_id", "telegram_id", name="uq_nyan_activity_user"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    activity_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("nyan_activities.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    telegram_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.telegram_id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    reward_amount: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ActivityCreate(BaseModel):
    # Datetime values arrive as ISO strings in the Web App's JSON payload.
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=5, max_length=110)
    description: str = Field(min_length=10, max_length=1500)
    prompt: str = Field(min_length=5, max_length=2000)
    kind: str
    choices: list[str] = Field(default_factory=list, max_length=6)
    correct_answer: str | None = Field(default=None, max_length=500)
    reward: int = Field(ge=0, le=500)
    max_winners: int = Field(ge=1, le=500)
    ends_at: datetime | None = None


class ActivityStatus(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    action: str


class ActivitySubmit(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    answer: str = Field(min_length=1, max_length=3000)


class ActivityReview(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    decision: str


def _auth(value: str | None, owner: bool = False) -> dict:
    # Reuse the short-lived, HMAC-verified browser login already provided by
    # the independent idea page. Raw Telegram IDs are never trusted.
    if (value or "").startswith("browser:"):
        from .interactive_ideas import verify_browser_session
        user = verify_browser_session(value[len("browser:"):])
    else:
        user = core.verify_init_data(value or "")
    if owner:
        core.require_owner(user)
    return user


def _clean(value: str) -> str:
    return " ".join(value.split())


def _activity_json(row: Activity, owner: bool = False, answer: ActivityAnswer | None = None) -> dict:
    data = {
        "id": row.id, "title": row.title, "description": row.description,
        "prompt": row.prompt, "kind": row.kind, "choices": json.loads(row.choices_json),
        "reward": row.reward, "max_winners": row.max_winners,
        "winner_count": row.winner_count, "status": row.status,
        "ends_at": row.ends_at.isoformat() if row.ends_at else None,
        "created_at": row.created_at.isoformat(),
        "my_answer": _answer_json(answer) if answer else None,
    }
    if owner:
        data["correct_answer"] = row.answer_key
    return data


def _answer_json(row: ActivityAnswer) -> dict:
    return {
        "id": row.id, "activity_id": row.activity_id,
        "answer": row.answer, "status": row.status,
        "reward_amount": row.reward_amount,
        "created_at": row.created_at.isoformat(),
    }


def _ensure_user(session, tg_user: dict, timestamp: datetime) -> core.User:
    values = {
        "telegram_id": int(tg_user["id"]),
        "username": tg_user.get("username") or None,
        "first_name": tg_user.get("first_name") or "Пользователь",
        "last_name": tg_user.get("last_name") or None,
        "balance": 0, "created_at": timestamp, "last_seen_at": timestamp,
    }
    dialect = session.bind.dialect.name
    if dialect == "postgresql":
        statement = pg_insert(core.User).values(**values)
    elif dialect == "sqlite":
        statement = sqlite_insert(core.User).values(**values)
    else:
        raise RuntimeError("Неизвестная база данных")
    session.execute(statement.on_conflict_do_nothing(index_elements=["telegram_id"]))
    user = session.scalar(
        select(core.User).where(core.User.telegram_id == tg_user["id"]).with_for_update()
    )
    core.apply_telegram_profile(user, tg_user, timestamp)
    return user


def _award(session, activity: Activity, submission: ActivityAnswer,
           user: core.User, timestamp: datetime) -> None:
    # Called only with the activity + user rows locked. The unique attempt
    # constraint prevents duplicate rewards, including concurrent requests.
    if submission.status != "pending":
        raise HTTPException(status_code=409, detail="Ответ уже рассмотрен")
    if activity.winner_count >= activity.max_winners:
        raise HTTPException(status_code=409, detail="Награды закончились")
    if session.get(BlockedUser, user.telegram_id) is not None:
        raise HTTPException(status_code=403, detail="Заблокированному аккаунту награда недоступна")
    submission.status = "approved"
    submission.reviewed_at = timestamp
    submission.reward_amount = activity.reward
    activity.winner_count += 1
    if activity.reward:
        user.balance += activity.reward
        session.add(core.Transaction(
            telegram_id=user.telegram_id, amount=activity.reward,
            operation_type="interactive_activity_reward",
            description=f"награда за интерактив «{activity.title}» №{activity.id}",
            created_at=timestamp,
        ))
    if activity.winner_count >= activity.max_winners:
        activity.status = "closed"


def _validate_activity_payload(payload: ActivityCreate) -> list[str]:
    choices = [_clean(x) for x in payload.choices]
    if len(_clean(payload.title)) < 5 or len(_clean(payload.prompt)) < 5:
        raise HTTPException(status_code=400, detail="Заполни название и вопрос")
    if payload.kind not in {"choice", "text", "manual"}:
        raise HTTPException(status_code=400, detail="Неизвестный тип интерактива")
    if payload.kind == "choice":
        if not 2 <= len(choices) <= 6 or not all(2 <= len(x) <= 120 for x in choices):
            raise HTTPException(status_code=400, detail="Нужно от 2 до 6 вариантов ответа")
        if len(set(x.casefold() for x in choices)) != len(choices):
            raise HTTPException(status_code=400, detail="Повторяющиеся варианты ответа")
        if payload.correct_answer not in [str(i) for i in range(len(choices))]:
            raise HTTPException(status_code=400, detail="Не выбран правильный ответ")
    elif payload.kind == "text":
        if not payload.correct_answer or len(_clean(payload.correct_answer)) < 2:
            raise HTTPException(status_code=400, detail="Укажи правильный ответ")
        choices = []
    else:
        choices = []
    if payload.ends_at:
        if payload.ends_at.tzinfo is None:
            raise HTTPException(status_code=400, detail="Нужна дата с часовым поясом")
        if payload.ends_at <= core.now_utc():
            raise HTTPException(status_code=400, detail="Дата окончания уже прошла")
    return choices


@router.get("/api/activities")
def list_activities(
    x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data"),
):
    tg_user = _auth(x_telegram_init_data)
    owner = core.is_owner(tg_user["id"])
    timestamp = core.now_utc()
    with core.SessionLocal() as session:
        query = select(Activity).order_by(Activity.id.desc()).limit(100)
        if not owner:
            query = query.where(Activity.status.in_(("published", "closed")))
        items = session.scalars(query).all()
        ids = [item.id for item in items]
        responses = session.scalars(
            select(ActivityAnswer).where(
                ActivityAnswer.telegram_id == tg_user["id"],
                ActivityAnswer.activity_id.in_(ids),
            )
        ).all() if ids else []
        by_id = {r.activity_id: r for r in responses}
        return {
            "ok": True, "is_owner": owner,
            "activities": [
                _activity_json(item, owner, by_id.get(item.id))
                for item in items
                if owner or (
                    (item.status == "published" and
                     (item.ends_at is None or item.ends_at > timestamp))
                    or by_id.get(item.id) is not None
                )
            ],
        }


@router.get("/api/activities/{activity_id}")
def activity_detail(
    activity_id: int,
    x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data"),
):
    tg_user = _auth(x_telegram_init_data)
    owner = core.is_owner(tg_user["id"])
    with core.SessionLocal() as session:
        activity = session.get(Activity, activity_id)
        if activity is None:
            raise HTTPException(status_code=404, detail="Интерактив недоступен")
        answer = session.scalar(
            select(ActivityAnswer).where(
                ActivityAnswer.activity_id == activity_id,
                ActivityAnswer.telegram_id == tg_user["id"],
            )
        )
        if not owner and activity.status != "published" and answer is None:
            raise HTTPException(status_code=404, detail="Интерактив недоступен")
        return {"ok": True, "activity": _activity_json(activity, owner, answer)}


@router.post("/api/owner/activities")
def create_activity(
    payload: ActivityCreate,
    x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data"),
):
    _auth(x_telegram_init_data, owner=True)
    choices = _validate_activity_payload(payload)
    with core.SessionLocal.begin() as session:
        item = Activity(
            title=_clean(payload.title), description=payload.description.strip(),
            prompt=payload.prompt.strip(), kind=payload.kind,
            choices_json=json.dumps(choices, ensure_ascii=False),
            answer_key=payload.correct_answer if payload.kind != "manual" else None,
            reward=payload.reward, max_winners=payload.max_winners,
            winner_count=0, status="draft", ends_at=payload.ends_at,
            created_at=core.now_utc(),
        )
        session.add(item)
        session.flush()
        result = _activity_json(item, owner=True)
    return {"ok": True, "activity": result}


@router.post("/api/owner/activities/{activity_id}/edit")
def edit_activity(
    activity_id: int, payload: ActivityCreate,
    x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data"),
):
    # Validate exactly the same fields as creation without writing anything.
    _auth(x_telegram_init_data, owner=True)
    # Use one validator for create and edit in the frontend and preserve the
    # immutable type/answer after publishing.
    with core.SessionLocal.begin() as session:
        item = session.scalar(select(Activity).where(Activity.id == activity_id).with_for_update())
        if not item:
            raise HTTPException(status_code=404, detail="Интерактив не найден")
        if item.status != "draft":
            raise HTTPException(status_code=409, detail="Изменять можно только черновик")
        choices = _validate_activity_payload(payload)
        item.title = _clean(payload.title)
        item.description = payload.description.strip()
        item.prompt = payload.prompt.strip()
        item.kind = payload.kind
        item.choices_json = json.dumps(choices, ensure_ascii=False)
        item.answer_key = payload.correct_answer if payload.kind != "manual" else None
        item.reward = payload.reward
        item.max_winners = payload.max_winners
        item.ends_at = payload.ends_at
        session.flush()
        result = _activity_json(item, owner=True)
    return {"ok": True, "activity": result}


@router.post("/api/owner/activities/{activity_id}/status")
def set_activity_status(
    activity_id: int, payload: ActivityStatus,
    x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data"),
):
    _auth(x_telegram_init_data, owner=True)
    if payload.action not in {"publish", "close"}:
        raise HTTPException(status_code=400, detail="Некорректное действие")
    with core.SessionLocal.begin() as session:
        item = session.scalar(select(Activity).where(Activity.id == activity_id).with_for_update())
        if not item:
            raise HTTPException(status_code=404, detail="Интерактив не найден")
        if payload.action == "publish":
            if item.status != "draft":
                raise HTTPException(status_code=409, detail="Опубликовать можно только черновик")
            if item.ends_at and item.ends_at <= core.now_utc():
                raise HTTPException(status_code=409, detail="Срок интерактива истёк")
            item.status = "published"
        else:
            if item.status not in {"draft", "published"}:
                raise HTTPException(status_code=409, detail="Интерактив уже закрыт")
            item.status = "closed"
        session.flush()
        result = _activity_json(item, owner=True)
    return {"ok": True, "activity": result}


@router.post("/api/activities/{activity_id}/answer")
def submit_answer(
    activity_id: int, payload: ActivitySubmit,
    x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data"),
):
    tg_user = _auth(x_telegram_init_data)
    now = core.now_utc()
    answer_text = payload.answer.strip()
    if not answer_text:
        raise HTTPException(status_code=400, detail="Напиши ответ")
    with core.SessionLocal.begin() as session:
        item = session.scalar(select(Activity).where(Activity.id == activity_id).with_for_update())
        if not item or item.status != "published" or (item.ends_at and item.ends_at <= now):
            raise HTTPException(status_code=409, detail="Приём ответов закрыт")
        user = _ensure_user(session, tg_user, now)
        if session.get(BlockedUser, user.telegram_id) is not None:
            raise HTTPException(status_code=403, detail="Участие заблокировано")
        exists = session.scalar(
            select(ActivityAnswer.id).where(
                ActivityAnswer.activity_id == activity_id,
                ActivityAnswer.telegram_id == user.telegram_id,
            )
        )
        if exists is not None:
            raise HTTPException(status_code=409, detail="У тебя уже есть ответ. Повторная попытка недоступна")
        if item.kind == "choice" and answer_text not in [
            str(index) for index in range(len(json.loads(item.choices_json)))
        ]:
            raise HTTPException(status_code=400, detail="Выбери один из вариантов")
        if item.kind == "manual" and len(_clean(answer_text)) < 10:
            raise HTTPException(status_code=400, detail="Опиши выполнение подробнее")
        row = ActivityAnswer(
            activity_id=activity_id, telegram_id=user.telegram_id,
            answer=answer_text, status="pending", reward_amount=0,
            created_at=now, reviewed_at=None,
        )
        session.add(row)
        session.flush()
        if item.kind == "choice":
            correct = answer_text == item.answer_key
        elif item.kind == "text":
            correct = _clean(answer_text).casefold() == _clean(item.answer_key or "").casefold()
        else:
            correct = None
        if correct is True:
            if item.winner_count < item.max_winners:
                _award(session, item, row, user, now)
            else:
                row.status = "rejected"
                row.reviewed_at = now
        elif correct is False:
            row.status = "rejected"
            row.reviewed_at = now
        session.flush()
        result = _answer_json(row)
    return {"ok": True, "answer": result}


@router.get("/api/owner/activities/{activity_id}/answers")
def owner_activity_answers(
    activity_id: int,
    x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data"),
):
    _auth(x_telegram_init_data, owner=True)
    with core.SessionLocal() as session:
        if not session.get(Activity, activity_id):
            raise HTTPException(status_code=404, detail="Интерактив не найден")
        rows = session.execute(
            select(ActivityAnswer, core.User)
            .join(core.User, core.User.telegram_id == ActivityAnswer.telegram_id)
            .where(ActivityAnswer.activity_id == activity_id)
            .order_by(ActivityAnswer.id.desc()).limit(300)
        ).all()
        return {"ok": True, "answers": [
            {**_answer_json(answer), "telegram_id": user.telegram_id,
             "username": user.username, "first_name": user.first_name}
            for answer, user in rows
        ]}


@router.post("/api/owner/activities/{activity_id}/answers/{answer_id}/review")
def review_activity_answer(
    activity_id: int, answer_id: int, payload: ActivityReview,
    x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data"),
):
    _auth(x_telegram_init_data, owner=True)
    if payload.decision not in {"approve", "reject"}:
        raise HTTPException(status_code=400, detail="Некорректное решение")
    now = core.now_utc()
    with core.SessionLocal.begin() as session:
        item = session.scalar(select(Activity).where(Activity.id == activity_id).with_for_update())
        if not item:
            raise HTTPException(status_code=404, detail="Интерактив не найден")
        if item.kind != "manual":
            raise HTTPException(status_code=400, detail="Ручная модерация доступна только для заданий")
        row = session.scalar(select(ActivityAnswer).where(
            ActivityAnswer.id == answer_id,
            ActivityAnswer.activity_id == activity_id,
        ).with_for_update())
        if row is None or row.status != "pending":
            raise HTTPException(status_code=409, detail="Ответ уже рассмотрен или не найден")
        user = session.scalar(
            select(core.User).where(core.User.telegram_id == row.telegram_id).with_for_update()
        )
        if payload.decision == "approve":
            _award(session, item, row, user, now)
        else:
            row.status = "rejected"
            row.reviewed_at = now
        session.flush()
        result = _answer_json(row)
    return {"ok": True, "answer": result}


def register_interactive_builder(app) -> None:
    global _REGISTERED
    if _REGISTERED:
        return
    core.Base.metadata.create_all(core.engine, tables=[Activity.__table__, ActivityAnswer.__table__])
    app.include_router(router)
    _REGISTERED = True
