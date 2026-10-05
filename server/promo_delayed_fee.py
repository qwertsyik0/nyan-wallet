from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict
from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Mapped, mapped_column

from . import backend_app as core

logger = logging.getLogger("nyan_wallet.promo_delayed_fee")

ROOT = Path(__file__).resolve().parent.parent
PROMO_CODE = "NYAN300"
FEE_PERCENT = 10
FEE_DELAY = timedelta(hours=1)
PROCESS_INTERVAL_SECONDS = 30

router = APIRouter()
_REGISTERED = False
_worker_task: asyncio.Task | None = None


class PromoDelayedFee(core.Base):
    __tablename__ = "promo_delayed_fees"
    __table_args__ = (
        UniqueConstraint("promo_id", "telegram_id", name="uq_promo_delayed_fee"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    promo_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("promo_codes.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    telegram_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.telegram_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    percent: Mapped[int] = mapped_column(Integer, nullable=False, default=FEE_PERCENT)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    applied_amount: Mapped[int | None] = mapped_column(Integer, nullable=True)


class ConditionalPromoRedeemRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    accepted_terms: bool


def schedule_fee(session, *, promo_id: int, telegram_id: int, activated_at: datetime) -> None:
    existing = session.scalar(
        select(PromoDelayedFee.id).where(
            PromoDelayedFee.promo_id == promo_id,
            PromoDelayedFee.telegram_id == telegram_id,
        )
    )
    if existing is not None:
        return

    session.add(
        PromoDelayedFee(
            promo_id=promo_id,
            telegram_id=telegram_id,
            percent=FEE_PERCENT,
            due_at=activated_at + FEE_DELAY,
            processed_at=None,
            applied_amount=None,
        )
    )


def process_due_fees() -> int:
    now = datetime.now(timezone.utc)
    processed = 0

    try:
        with core.SessionLocal() as session:
            while True:
                with session.begin():
                    fee = session.scalar(
                        select(PromoDelayedFee)
                        .where(
                            PromoDelayedFee.processed_at.is_(None),
                            PromoDelayedFee.due_at <= now,
                        )
                        .order_by(PromoDelayedFee.due_at.asc(), PromoDelayedFee.id.asc())
                        .with_for_update(skip_locked=True)
                        .limit(1)
                    )
                    if fee is None:
                        break

                    user = session.scalar(
                        select(core.User)
                        .where(core.User.telegram_id == fee.telegram_id)
                        .with_for_update()
                    )
                    if user is None:
                        fee.processed_at = now
                        fee.applied_amount = 0
                        processed += 1
                        continue

                    current_balance = max(0, int(user.balance or 0))
                    debit = (current_balance * int(fee.percent)) // 100

                    if debit > 0:
                        user.balance -= debit
                        session.add(
                            core.Transaction(
                                telegram_id=user.telegram_id,
                                amount=-debit,
                                operation_type="promo_delayed_fee",
                                description=(
                                    f"Условие промокода {PROMO_CODE}: "
                                    f"{fee.percent}% баланса через 1 час"
                                ),
                                created_at=now,
                            )
                        )

                    fee.processed_at = now
                    fee.applied_amount = debit
                    processed += 1

        if processed:
            logger.info("promo_delayed_fees_processed count=%s", processed)
        return processed
    except SQLAlchemyError:
        logger.exception("promo_delayed_fee_processing_failed")
        return 0


async def _fee_worker() -> None:
    await asyncio.sleep(5)
    while True:
        await asyncio.to_thread(process_due_fees)
        await asyncio.sleep(PROCESS_INTERVAL_SECONDS)


async def _start_fee_worker() -> None:
    global _worker_task
    if _worker_task is None or _worker_task.done():
        _worker_task = asyncio.create_task(_fee_worker(), name="nyan-promo-delayed-fee")


@router.get("/promo-300.html", include_in_schema=False)
async def promo_300_page():
    return FileResponse(ROOT / "promo-300.html", media_type="text/html; charset=utf-8")


@router.get("/promo-300.css", include_in_schema=False)
async def promo_300_css():
    return FileResponse(ROOT / "promo-300.css", media_type="text/css; charset=utf-8")


@router.get("/promo.css", include_in_schema=False)
async def shared_promo_css():
    return FileResponse(ROOT / "promo.css", media_type="text/css; charset=utf-8")


@router.get("/style.css", include_in_schema=False)
async def shared_style_css():
    return FileResponse(ROOT / "style.css", media_type="text/css; charset=utf-8")


@router.get("/network.js", include_in_schema=False)
async def promo_network_js():
    return FileResponse(ROOT / "network.js", media_type="application/javascript; charset=utf-8")


@router.get("/promo-300.js", include_in_schema=False)
async def promo_300_js():
    return FileResponse(ROOT / "promo-300.js", media_type="application/javascript; charset=utf-8")


@router.post("/api/promo/nyan300/redeem")
async def redeem_conditional_promo(
    payload: ConditionalPromoRedeemRequest,
    x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data"),
):
    if payload.accepted_terms is not True:
        raise HTTPException(
            status_code=400,
            detail="Нужно подтвердить условие списания 10% баланса через 1 час",
        )

    tg_user = core.verify_init_data(x_telegram_init_data or "")
    result = core.redeem_promo(
        tg_user,
        PROMO_CODE,
        allow_conditional=True,
    )
    return {
        "ok": True,
        **result,
        "terms": {
            "percent": FEE_PERCENT,
            "delay_seconds": int(FEE_DELAY.total_seconds()),
            "basis": "текущий баланс на момент списания",
            "rounding": "вниз до целого лапкоина",
        },
    }


@router.get("/api/promo/nyan300/status")
async def conditional_promo_status(
    x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data"),
):
    tg_user = core.verify_init_data(x_telegram_init_data or "")
    telegram_id = int(tg_user["id"])

    with core.SessionLocal() as session:
        promo = session.scalar(select(core.PromoCode).where(core.PromoCode.code == PROMO_CODE))
        if promo is None:
            return {"ok": True, "available": False}

        fee = session.scalar(
            select(PromoDelayedFee).where(
                PromoDelayedFee.promo_id == promo.id,
                PromoDelayedFee.telegram_id == telegram_id,
            )
        )
        return {
            "ok": True,
            "available": bool(
                promo.is_active
                and (promo.max_uses is None or promo.uses_count < promo.max_uses)
            ),
            "uses_count": int(promo.uses_count),
            "max_uses": promo.max_uses,
            "fee": None if fee is None else {
                "due_at": fee.due_at.isoformat(),
                "processed_at": fee.processed_at.isoformat() if fee.processed_at else None,
                "applied_amount": fee.applied_amount,
                "percent": fee.percent,
            },
        }


def register_promo_delayed_fee(app) -> None:
    global _REGISTERED
    if _REGISTERED:
        return
    core.Base.metadata.create_all(core.engine)
    app.include_router(router)
    app.add_event_handler("startup", _start_fee_worker)
    _REGISTERED = True
