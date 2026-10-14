"""Private second-round written exercise for one verified finance administrator applicant.

This module never changes wallet balances, assigns administrator permissions, or
sends invitations on import. The candidate must supply valid Telegram Mini App
initData. A unique constraint guarantees no duplicate responses.
"""

from __future__ import annotations

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
from .finance_recruitment import FinancialAdminApplication

log = logging.getLogger("nyan_wallet.finance_stage2")
router = APIRouter()
_REGISTERED = False

TARGET_APPLICATION_ID = 2
TARGET_TELEGRAM_ID = 1129986805
REVIEW_URL = "https://qwertsyik0.github.io/nyan-wallet/finance-review.html"


class FinanceStage2Response(core.Base):
    __tablename__ = "finance_stage2_responses"
    __table_args__ = (UniqueConstraint("application_id", name="uq_finance_stage2_application"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    application_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("financial_admin_applications.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    telegram_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.telegram_id", ondelete="CASCADE"), nullable=False, index=True,
    )
    balance: Mapped[str] = mapped_column(Text, nullable=False)
    duplicate: Mapped[str] = mapped_column(String(20), nullable=False)
    audit: Mapped[str] = mapped_column(Text, nullable=False)
    fraud: Mapped[str] = mapped_column(Text, nullable=False)
    access: Mapped[str] = mapped_column(String(20), nullable=False)
    dispute: Mapped[str] = mapped_column(Text, nullable=False)
    internship: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Stage2Submit(BaseModel):
    balance: str = Field(min_length=15, max_length=1600)
    duplicate: Literal["debit", "verify", "ignore"]
    audit: str = Field(min_length=25, max_length=1600)
    fraud: str = Field(min_length=35, max_length=1800)
    access: Literal["do", "report", "deal"]
    dispute: str = Field(min_length=35, max_length=1800)
    internship: str = Field(min_length=30, max_length=1600)


def _check_candidate(tg_user: dict) -> None:
    if tg_user["id"] != TARGET_TELEGRAM_ID:
        # Never disclose the candidate's identity to other logged-in users.
        raise HTTPException(status_code=403, detail="Это персональное испытание недоступно вашему аккаунту.")


def _get_application(session) -> FinancialAdminApplication:
    app = session.scalar(
        select(FinancialAdminApplication)
        .where(
            FinancialAdminApplication.id == TARGET_APPLICATION_ID,
            FinancialAdminApplication.telegram_id == TARGET_TELEGRAM_ID,
        )
        .with_for_update()
    )
    if not app or app.status not in {"pending", "interview"}:
        raise HTTPException(
            status_code=403,
            detail="Второй этап отбора недоступен для текущего статуса заявки.",
        )
    return app


def _serialize(item: FinanceStage2Response | None) -> dict | None:
    if not item:
        return None
    return {
        "id": item.id,
        "application_id": item.application_id,
        "telegram_id": item.telegram_id,
        "balance": item.balance,
        "duplicate": item.duplicate,
        "audit": item.audit,
        "fraud": item.fraud,
        "access": item.access,
        "dispute": item.dispute,
        "internship": item.internship,
        "created_at": item.created_at.isoformat(),
    }


def _message_owner(text: str) -> None:
    if not core.BOT_TOKEN or not core.OWNER_TELEGRAM_ID:
        return
    request_body = {
        "chat_id": str(core.OWNER_TELEGRAM_ID),
        "text": text,
        "reply_markup": json.dumps(
            {"inline_keyboard": [[{"text": "Открыть ответы кандидата", "web_app": {"url": REVIEW_URL}}]]},
            ensure_ascii=False,
        ),
    }
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{core.BOT_TOKEN}/sendMessage",
        data=urllib.parse.urlencode(request_body).encode("utf-8"),
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=7) as response:
            response.read()
    except Exception as exc:
        log.warning("second stage owner notification failed: %s", type(exc).__name__)


@router.get("/api/recruitment/finance/stage2/me")
async def get_stage2_me(
    x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data"),
):
    tg_user = core.verify_init_data(x_telegram_init_data or "")
    _check_candidate(tg_user)
    with core.SessionLocal() as session:
        _get_application(session)
        response = session.scalar(
            select(FinanceStage2Response)
            .where(FinanceStage2Response.application_id == TARGET_APPLICATION_ID)
        )
        return {
            "ok": True,
            "can_submit": response is None,
            "submitted": response is not None,
            "created_at": response.created_at.isoformat() if response else None,
        }


@router.post("/api/recruitment/finance/stage2/submit", status_code=201)
async def submit_stage2(
    payload: Stage2Submit,
    background_tasks: BackgroundTasks,
    x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data"),
):
    tg_user = core.verify_init_data(x_telegram_init_data or "")
    _check_candidate(tg_user)
    keys = ("balance", "audit", "fraud", "dispute", "internship")
    data = payload.model_dump()
    for key in keys:
        data[key] = " ".join(data[key].split())
        low = {"balance": 15, "audit": 25, "fraud": 35, "dispute": 35, "internship": 30}[key]
        if len(data[key]) < low:
            raise HTTPException(status_code=422, detail=f"Ответ «{key}» слишком короткий.")

    try:
        with core.SessionLocal() as session:
            with session.begin():
                app = _get_application(session)
                existing = session.scalar(
                    select(FinanceStage2Response.id).where(
                        FinanceStage2Response.application_id == app.id
                    )
                )
                if existing:
                    raise HTTPException(status_code=409, detail="Ответы на второй этап уже отправлены.")

                item = FinanceStage2Response(
                    application_id=app.id,
                    telegram_id=tg_user["id"],
                    created_at=core.now_utc(),
                    **data,
                )
                session.add(item)
                session.flush()
                result = _serialize(item)
    except IntegrityError as exc:
        raise HTTPException(status_code=409, detail="Ответы на второй этап уже отправлены.") from exc

    background_tasks.add_task(
        _message_owner,
        f"🐾 Nyan Wallet | Второй этап пройден\n\n"
        f"Кандидат: @nasttchl\nЗаявка №{TARGET_APPLICATION_ID}\n"
        f"Ответы сохранены. Открой рассмотрение анкет.",
    )
    return {"ok": True, "submitted": True, "created_at": result["created_at"]}


@router.get("/api/owner/recruitment/finance/stage2/{application_id}")
async def owner_stage2(
    application_id: int,
    x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data"),
):
    tg_user = core.verify_init_data(x_telegram_init_data or "")
    core.require_owner(tg_user)
    if application_id != TARGET_APPLICATION_ID:
        raise HTTPException(status_code=404, detail="Для этой заявки второй этап не назначен.")
    with core.SessionLocal() as session:
        response = session.scalar(
            select(FinanceStage2Response)
            .where(FinanceStage2Response.application_id == application_id)
        )
        return {"ok": True, "submitted": response is not None, "response": _serialize(response)}


def register_finance_stage2(app) -> None:
    global _REGISTERED
    if _REGISTERED:
        return
    FinanceStage2Response.__table__.create(bind=core.engine, checkfirst=True)
    app.include_router(router)
    _REGISTERED = True
