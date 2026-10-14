from __future__ import annotations

"""Financial administrator applications. No payroll, wallet or admin privileges are granted here."""

import json
import logging
import urllib.parse
import urllib.request
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, mapped_column

from . import backend_app as core

logger = logging.getLogger("nyan_wallet.finance_recruitment")
router = APIRouter()
_REGISTERED = False
REVIEW_URL = "https://qwertsyik0.github.io/nyan-wallet/finance-review.html"
AGE_GROUPS = {"under_16", "16_17", "18_plus"}
AVAILABILITY = {"less_1", "1_2", "2_4", "more_4"}
STATUSES = {"pending", "interview", "reserve", "rejected"}


class FinancialAdminApplication(core.Base):
    __tablename__ = "financial_admin_applications"
    __table_args__ = (UniqueConstraint("telegram_id", name="uq_fin_admin_applicant"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telegram_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.telegram_id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    display_name: Mapped[str] = mapped_column(String(64), nullable=False)
    age_group: Mapped[str] = mapped_column(String(16), nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False)
    availability: Mapped[str] = mapped_column(String(16), nullable=False)
    experience: Mapped[str] = mapped_column(Text, nullable=False)
    motivation: Mapped[str] = mapped_column(Text, nullable=False)
    situation_discrepancy: Mapped[str] = mapped_column(Text, nullable=False)
    situation_farm: Mapped[str] = mapped_column(Text, nullable=False)
    skills: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, index=True, default="pending")
    owner_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class FinanceApplyRequest(BaseModel):
    display_name: str = Field(min_length=2, max_length=64)
    age_group: Literal["under_16", "16_17", "18_plus"]
    timezone: str = Field(min_length=2, max_length=64)
    availability: Literal["less_1", "1_2", "2_4", "more_4"]
    experience: str = Field(min_length=30, max_length=1200)
    motivation: str = Field(min_length=30, max_length=1200)
    situation_discrepancy: str = Field(min_length=35, max_length=1200)
    situation_farm: str = Field(min_length=35, max_length=1200)
    skills: str = Field(min_length=10, max_length=800)
    consent: Literal[True]


class FinanceReviewRequest(BaseModel):
    decision: Literal["interview", "reserve", "rejected"]
    note: str | None = Field(default=None, max_length=400)


def clean_text(value: str, lower: int, upper: int, name: str) -> str:
    cleaned = " ".join(value.split())
    if not lower <= len(cleaned) <= upper:
        raise HTTPException(
            status_code=422,
            detail=f"Поле «{name}»: от {lower} до {upper} символов.",
        )
    return cleaned


def serialize(item: FinancialAdminApplication, user: core.User | None = None, *, full=False) -> dict:
    data = {
        "id": item.id,
        "status": item.status,
        "created_at": item.created_at.isoformat(),
        "reviewed_at": item.reviewed_at.isoformat() if item.reviewed_at else None,
        "owner_note": item.owner_note,
    }
    if full:
        for name in (
            "display_name", "age_group", "timezone", "availability", "experience",
            "motivation", "situation_discrepancy", "situation_farm", "skills",
        ):
            data[name] = getattr(item, name)
        data["telegram_id"] = item.telegram_id
        if user:
            data["username"] = user.username
            data["first_name"] = user.first_name
    return data


def send_notice(chat_id: int, message: str, *, review_button=False) -> None:
    if not core.BOT_TOKEN:
        return
    payload: dict[str, str] = {"chat_id": str(chat_id), "text": message}
    if review_button:
        payload["reply_markup"] = json.dumps({
            "inline_keyboard": [[{"text": "Рассмотреть анкеты", "web_app": {"url": REVIEW_URL}}]]
        }, ensure_ascii=False)
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{core.BOT_TOKEN}/sendMessage",
        data=urllib.parse.urlencode(payload).encode("utf-8"),
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=6) as response:
            response.read()
    except Exception as exc:
        logger.warning("finance recruitment notification failed: %s", type(exc).__name__)


@router.get("/api/recruitment/finance/me")
async def my_finance_application(
    x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data")
):
    user = core.verify_init_data(x_telegram_init_data or "")
    with core.SessionLocal() as session:
        record = session.scalar(
            select(FinancialAdminApplication)
            .where(FinancialAdminApplication.telegram_id == user["id"])
            .limit(1)
        )
        return {"ok": True, "application": serialize(record) if record else None}


@router.post("/api/recruitment/finance/apply", status_code=201)
async def submit_finance_application(
    payload: FinanceApplyRequest,
    background_tasks: BackgroundTasks,
    x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data"),
):
    user = core.verify_init_data(x_telegram_init_data or "")
    timestamp = core.now_utc()
    values = {
        "display_name": clean_text(payload.display_name, 2, 64, "Имя"),
        "timezone": clean_text(payload.timezone, 2, 64, "Часовой пояс"),
        "experience": clean_text(payload.experience, 30, 1200, "Опыт"),
        "motivation": clean_text(payload.motivation, 30, 1200, "Мотивация"),
        "situation_discrepancy": clean_text(payload.situation_discrepancy, 35, 1200, "Расхождение"),
        "situation_farm": clean_text(payload.situation_farm, 35, 1200, "Антифрод"),
        "skills": clean_text(payload.skills, 10, 800, "Навыки"),
        "age_group": payload.age_group,
        "availability": payload.availability,
    }

    # The unique DB constraint also handles simultaneous submissions.
    core.get_or_create_user(user)
    try:
        with core.SessionLocal() as session:
            with session.begin():
                existing = session.scalar(
                    select(FinancialAdminApplication.id).where(
                        FinancialAdminApplication.telegram_id == user["id"]
                    )
                )
                if existing is not None:
                    raise HTTPException(
                        status_code=409,
                        detail="Анкета уже отправлена. Её статус доступен на этой странице.",
                    )
                record = FinancialAdminApplication(
                    telegram_id=user["id"], created_at=timestamp,
                    reviewed_at=None, owner_note=None, status="pending", **values,
                )
                session.add(record)
                session.flush()
                result = serialize(record)
    except IntegrityError as exc:
        raise HTTPException(status_code=409, detail="Анкета уже отправлена.") from exc

    if core.OWNER_TELEGRAM_ID:
        name = "@" + user["username"] if user.get("username") else values["display_name"]
        background_tasks.add_task(
            send_notice, core.OWNER_TELEGRAM_ID,
            f"🐾 Nyan Wallet | Новая анкета\n\n"
            f"Должность: финансовый администратор\n"
            f"Заявка №{result['id']}\n"
            f"Кандидат: {name}\n"
            f"Ответы доступны в разделе рассмотрения.",
            review_button=True,
        )
    return {"ok": True, "application": result}


@router.get("/api/owner/recruitment/finance")
async def list_finance_applications(
    status: str = Query(default="pending", max_length=20),
    x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data"),
):
    user = core.verify_init_data(x_telegram_init_data or "")
    core.require_owner(user)
    if status not in STATUSES | {"all"}:
        raise HTTPException(status_code=400, detail="Некорректный фильтр")

    with core.SessionLocal() as session:
        query = (
            select(FinancialAdminApplication, core.User)
            .join(core.User, core.User.telegram_id == FinancialAdminApplication.telegram_id)
            .order_by(FinancialAdminApplication.id.desc())
            .limit(100)
        )
        if status != "all":
            query = query.where(FinancialAdminApplication.status == status)
        rows = session.execute(query).all()
        return {"ok": True, "applications": [serialize(item, person, full=True) for item, person in rows]}


@router.post("/api/owner/recruitment/finance/{application_id}/review")
async def review_finance_application(
    application_id: int,
    payload: FinanceReviewRequest,
    background_tasks: BackgroundTasks,
    x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data"),
):
    user = core.verify_init_data(x_telegram_init_data or "")
    core.require_owner(user)
    note = clean_text(payload.note, 1, 400, "Комментарий") if payload.note and payload.note.strip() else None

    with core.SessionLocal() as session:
        with session.begin():
            record = session.scalar(
                select(FinancialAdminApplication)
                .where(FinancialAdminApplication.id == application_id)
                .with_for_update()
            )
            if not record:
                raise HTTPException(status_code=404, detail="Анкета не найдена")
            if record.status not in {"pending", "reserve", "interview"}:
                raise HTTPException(status_code=409, detail="Эта анкета уже закрыта")
            if record.status == payload.decision:
                raise HTTPException(status_code=409, detail="Такой статус уже установлен")
            record.status = payload.decision
            record.owner_note = note
            record.reviewed_at = core.now_utc()
            result = serialize(record)
            target = record.telegram_id

    labels = {
        "interview": "Ты приглашён(а) на следующий этап отбора.",
        "reserve": "Твоя анкета находится в резерве кандидатов.",
        "rejected": "К сожалению, анкета не прошла отбор.",
    }
    message = ("🐾 Nyan Wallet | Финансовый администратор\n\n" +
               labels[payload.decision] +
               (("\nКомментарий: " + note) if note else "") +
               "\n\nЭто уведомление не предоставляет доступ к управлению кошельками.")
    background_tasks.add_task(send_notice, target, message)
    return {"ok": True, "application": result}


def register_finance_recruitment(app) -> None:
    global _REGISTERED
    if _REGISTERED:
        return
    FinancialAdminApplication.__table__.create(bind=core.engine, checkfirst=True)
    app.include_router(router)
    _REGISTERED = True
