from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, UniqueConstraint, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Mapped, mapped_column

from . import backend_app as core

logger = logging.getLogger("nyan_wallet.promo150_subscription_penalty")

PROMO_CODE = "NYAN150"
PENALTY_AMOUNT = 500
PROCESS_INTERVAL_SECONDS = 300
BATCH_SIZE = 50

_REGISTERED = False
_worker_task: asyncio.Task | None = None


class Promo150SubscriptionWatch(core.Base):
    __tablename__ = "promo150_subscription_watches"
    __table_args__ = (
        UniqueConstraint("promo_id", "telegram_id", name="uq_promo150_subscription_watch"),
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
    activated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    penalized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    penalty_amount: Mapped[int | None] = mapped_column(Integer, nullable=True)


def schedule_subscription_watch(
    session,
    *,
    promo_id: int,
    telegram_id: int,
    activated_at: datetime,
) -> None:
    existing = session.scalar(
        select(Promo150SubscriptionWatch.id).where(
            Promo150SubscriptionWatch.promo_id == promo_id,
            Promo150SubscriptionWatch.telegram_id == telegram_id,
        )
    )
    if existing is not None:
        return

    session.add(
        Promo150SubscriptionWatch(
            promo_id=promo_id,
            telegram_id=telegram_id,
            activated_at=activated_at,
            last_checked_at=None,
            penalized_at=None,
            penalty_amount=None,
        )
    )


def process_subscription_watches() -> int:
    now = datetime.now(timezone.utc)
    checked = 0
    penalized = 0

    try:
        with core.SessionLocal() as session:
            watches = session.scalars(
                select(Promo150SubscriptionWatch)
                .where(Promo150SubscriptionWatch.penalized_at.is_(None))
                .order_by(
                    Promo150SubscriptionWatch.last_checked_at.asc().nullsfirst(),
                    Promo150SubscriptionWatch.id.asc(),
                )
                .limit(BATCH_SIZE)
            ).all()

            for watch in watches:
                try:
                    subscription = core._channel_subscription_status(int(watch.telegram_id))
                except HTTPException:
                    logger.warning(
                        "promo150_subscription_check_unavailable telegram_id=%s",
                        watch.telegram_id,
                    )
                    continue
                except Exception:
                    logger.exception(
                        "promo150_subscription_check_failed telegram_id=%s",
                        watch.telegram_id,
                    )
                    continue

                with session.begin_nested():
                    locked = session.scalar(
                        select(Promo150SubscriptionWatch)
                        .where(Promo150SubscriptionWatch.id == watch.id)
                        .with_for_update()
                    )
                    if locked is None or locked.penalized_at is not None:
                        continue

                    locked.last_checked_at = now
                    checked += 1

                    if subscription.get("subscribed"):
                        continue

                    user = session.scalar(
                        select(core.User)
                        .where(core.User.telegram_id == locked.telegram_id)
                        .with_for_update()
                    )
                    if user is None:
                        locked.penalized_at = now
                        locked.penalty_amount = 0
                        continue

                    user.balance = int(user.balance or 0) - PENALTY_AMOUNT
                    session.add(
                        core.Transaction(
                            telegram_id=user.telegram_id,
                            amount=-PENALTY_AMOUNT,
                            operation_type="promo_subscription_penalty",
                            description=(
                                f"Условие промокода {PROMO_CODE}: "
                                "отписка от информационного канала"
                            ),
                            created_at=now,
                        )
                    )
                    locked.penalized_at = now
                    locked.penalty_amount = PENALTY_AMOUNT
                    penalized += 1

            session.commit()

        if checked or penalized:
            logger.info(
                "promo150_subscription_watch checked=%s penalized=%s",
                checked,
                penalized,
            )
        return penalized
    except SQLAlchemyError:
        logger.exception("promo150_subscription_watch_db_failed")
        return 0


async def _worker() -> None:
    await asyncio.sleep(15)
    while True:
        await asyncio.to_thread(process_subscription_watches)
        await asyncio.sleep(PROCESS_INTERVAL_SECONDS)


async def _start_worker() -> None:
    global _worker_task
    if _worker_task is None or _worker_task.done():
        _worker_task = asyncio.create_task(
            _worker(),
            name="nyan-promo150-subscription-watch",
        )


def register_promo150_subscription_penalty(app) -> None:
    global _REGISTERED
    if _REGISTERED:
        return
    core.Base.metadata.create_all(core.engine)
    app.add_event_handler("startup", _start_worker)
    _REGISTERED = True
