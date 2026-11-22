"""Paid 30-day VIP membership; independent from the lifetime-earned VIP rank.

A fulfilled catalog purchase activates membership. Renewals preserve remaining
days, up to 90 days prepaid. Four 25-lapcoin weekly credits are idempotent.
"""
from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Header, HTTPException
from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, UniqueConstraint, select
from sqlalchemy.orm import Mapped, mapped_column

from . import backend_app as core

LOG = logging.getLogger("nyan_wallet.vip")
router = APIRouter()
_REGISTERED = False
_WORKER: asyncio.Task | None = None

DURATION = timedelta(days=30)
MAX_PREPAID = timedelta(days=90)
WEEKLY_AMOUNT = 25
WEEKS_PER_TERM = 4
SWEEP_INTERVAL = 15 * 60


class VipSubscription(core.Base):
    __tablename__ = "vip_subscriptions"

    request_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("spend_requests.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    telegram_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.telegram_id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class VipPurchaseToken(core.Base):
    """Idempotency receipt for one authenticated VIP purchase request."""
    __tablename__ = "vip_purchase_tokens"

    telegram_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.telegram_id", ondelete="CASCADE"),
        primary_key=True,
    )
    token: Mapped[str] = mapped_column(String(80), primary_key=True)
    request_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("spend_requests.id", ondelete="RESTRICT"),
        nullable=False, unique=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class VipWeeklyCredit(core.Base):
    __tablename__ = "vip_weekly_credits"
    __table_args__ = (
        UniqueConstraint("request_id", "week_number", name="uq_vip_week_credit"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    request_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("vip_subscriptions.request_id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    telegram_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.telegram_id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    week_number: Mapped[int] = mapped_column(Integer, nullable=False)
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


def now() -> datetime:
    return datetime.now(timezone.utc)


def aware(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def is_vip_reward(title: str | None) -> bool:
    """Only the established 'Статус «VIP» на 30 дней' catalog item."""
    normalized = re.sub(r"[«»\"'’]", "", str(title or "").casefold())
    return " ".join(normalized.split()) in {"статус vip на 30 дней", "vip на 30 дней", "подписка vip на 30 дней"}


def _latest_end(session, telegram_id: int) -> datetime | None:
    row = session.scalar(
        select(VipSubscription)
        .where(VipSubscription.telegram_id == telegram_id)
        .order_by(VipSubscription.ends_at.desc(), VipSubscription.request_id.desc())
        .limit(1)
    )
    return aware(row.ends_at) if row is not None else None


def check_renewal_capacity(session, telegram_id: int, timestamp: datetime) -> None:
    timestamp = aware(timestamp)
    latest = _latest_end(session, telegram_id)
    next_start = max(timestamp, latest) if latest else timestamp
    if next_start + DURATION > timestamp + MAX_PREPAID:
        raise HTTPException(
            status_code=409,
            detail="VIP уже продлён на 90 дней. Дождитесь уменьшения срока.",
        )


def activate_vip(
    session, request_id: int, telegram_id: int, timestamp: datetime,
    *, enforce_cap: bool = True, announce: bool = True,
) -> VipSubscription:
    """Called in the same DB transaction that fulfills a paid reward request.

    The request ID is the subscription primary key, so repeated calls are safe.
    Callers serialize purchases per user with SELECT FOR UPDATE.
    """
    existing = session.get(VipSubscription, request_id)
    if existing is not None:
        return existing

    user = session.scalar(
        select(core.User).where(core.User.telegram_id == telegram_id).with_for_update()
    )
    if user is None:
        raise RuntimeError("VIP wallet is missing")

    from .extended_features import SpendRequest
    request = session.get(SpendRequest, request_id)
    if (request is None or request.telegram_id != telegram_id
            or request.status != "fulfilled" or not is_vip_reward(request.reward_title)):
        raise RuntimeError("VIP activation requires a fulfilled VIP catalog request")

    timestamp = aware(timestamp)
    if enforce_cap:
        check_renewal_capacity(session, telegram_id, timestamp)
    latest = _latest_end(session, telegram_id)
    starts = max(timestamp, latest) if latest else timestamp
    row = VipSubscription(
        request_id=request_id,
        telegram_id=telegram_id,
        starts_at=starts,
        ends_at=starts + DURATION,
        created_at=timestamp,
    )
    session.add(row)

    if announce:
        from .advanced_features import WalletNotification
        session.add(WalletNotification(
            telegram_id=telegram_id,
            kind="vip_activated",
            title="VIP подписка активирована",
            body="VIP действует до " + (starts + DURATION).strftime("%d.%m.%Y") +
                 ". Каждые 7 дней по 25 🐾, до 100 🐾 за срок подписки.",
            is_read=False,
            created_at=timestamp,
        ))
    session.flush()
    return row


def credit_due_for_user(session, telegram_id: int, timestamp: datetime) -> int:
    """Credit due weeks atomically, serialized on the wallet's user row."""
    timestamp = aware(timestamp)
    user = session.scalar(
        select(core.User).where(core.User.telegram_id == telegram_id).with_for_update()
    )
    if user is None or user.balance < 0:
        return 0

    terms = session.scalars(
        select(VipSubscription)
        .where(
            VipSubscription.telegram_id == telegram_id,
            VipSubscription.starts_at <= timestamp,
            VipSubscription.ends_at > timestamp,
        )
        .order_by(VipSubscription.starts_at.asc())
    ).all()
    if not terms:
        return 0

    paid = set(session.execute(
        select(VipWeeklyCredit.request_id, VipWeeklyCredit.week_number)
        .where(VipWeeklyCredit.telegram_id == telegram_id)
    ).all())

    from .advanced_features import WalletNotification
    credited = 0
    for term in terms:
        for week in range(1, WEEKS_PER_TERM + 1):
            due = aware(term.starts_at) + timedelta(days=7 * week)
            key = (term.request_id, week)
            if due > timestamp or key in paid:
                continue
            paid.add(key)
            session.add(VipWeeklyCredit(
                request_id=term.request_id,
                telegram_id=telegram_id,
                week_number=week,
                amount=WEEKLY_AMOUNT,
                created_at=timestamp,
            ))
            user.balance += WEEKLY_AMOUNT
            credited += WEEKLY_AMOUNT
            session.add(core.Transaction(
                telegram_id=telegram_id,
                amount=WEEKLY_AMOUNT,
                operation_type="vip_weekly_bonus",
                description=f"VIP бонус: неделя {week}/4, подписка #{term.request_id}",
                created_at=timestamp,
            ))
            session.add(WalletNotification(
                telegram_id=telegram_id,
                kind="vip_weekly_bonus",
                title="Еженедельный VIP бонус",
                body=f"Начислено +{WEEKLY_AMOUNT} 🐾 за неделю {week}/4.",
                is_read=False,
                created_at=timestamp,
            ))
    return credited


def status_for_user(session, telegram_id: int, timestamp: datetime | None = None) -> dict:
    timestamp = aware(timestamp or now())
    terms = session.scalars(
        select(VipSubscription)
        .where(VipSubscription.telegram_id == telegram_id)
        .order_by(VipSubscription.ends_at.desc())
    ).all()
    active = next(
        (term for term in terms if aware(term.starts_at) <= timestamp < aware(term.ends_at)),
        None,
    )
    latest_end = aware(terms[0].ends_at) if terms else None
    total_paid = 0
    next_week = None
    if active is not None:
        payments = set(session.scalars(
            select(VipWeeklyCredit.week_number).where(
                VipWeeklyCredit.request_id == active.request_id
            )
        ).all())
        total_paid = WEEKLY_AMOUNT * len(payments)
        for week in range(1, WEEKS_PER_TERM + 1):
            if week not in payments:
                next_week = aware(active.starts_at) + timedelta(days=7 * week)
                break

    return {
        "active": active is not None,
        "badge": "NYAN VIP" if active is not None else None,
        "frame": "vip_berry" if active is not None else None,
        "expires_at": latest_end.isoformat() if latest_end else None,
        "current_term_ends_at": aware(active.ends_at).isoformat() if active else None,
        "weekly_paid_in_term": total_paid,
        "next_weekly_at": next_week.isoformat() if next_week else None,
        "weekly_amount": WEEKLY_AMOUNT,
        "maximum_weekly_bonus": WEEKLY_AMOUNT * WEEKS_PER_TERM,
        "term_days": DURATION.days,
        "maximum_prepaid_days": MAX_PREPAID.days,
    }


@router.get("/api/vip/status")
async def vip_status(
    x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data"),
):
    tg = core.verify_init_data(x_telegram_init_data or "")
    core.get_or_create_user(tg)
    from .extended_features import Reward
    with core.SessionLocal() as session:
        with session.begin():
            timestamp = now()
            credited = credit_due_for_user(session, tg["id"], timestamp)
            status = status_for_user(session, tg["id"], timestamp)
            user = session.get(core.User, tg["id"])
            rewards = session.scalars(
                select(Reward).where(Reward.is_active.is_(True))
            ).all()
            reward = next((item for item in rewards if is_vip_reward(item.title)), None)
            status.update({
                "ok": True,
                "balance": int(user.balance) if user else 0,
                "newly_credited": credited,
                "reward_id": reward.id if reward else None,
                "price": reward.cost if reward else None,
            })
        return status


def _run_due_credit_sweep() -> None:
    """A passive safety net: pay due bonuses even if the client stays closed."""
    timestamp = now()
    with core.SessionLocal() as session:
        ids = session.scalars(
            select(VipSubscription.telegram_id).where(
                VipSubscription.starts_at <= timestamp,
                VipSubscription.ends_at > timestamp,
            ).distinct()
        ).all()

    for uid in ids:
        try:
            with core.SessionLocal() as session:
                with session.begin():
                    credit_due_for_user(session, int(uid), timestamp)
        except Exception:
            LOG.exception("VIP weekly credit failed for wallet")


async def _weekly_worker() -> None:
    while True:
        try:
            await asyncio.to_thread(_run_due_credit_sweep)
        except asyncio.CancelledError:
            raise
        except Exception:
            LOG.exception("VIP credit worker crashed; retrying")
        await asyncio.sleep(SWEEP_INTERVAL)


async def _start_worker() -> None:
    global _WORKER
    if _WORKER is None or _WORKER.done():
        _WORKER = asyncio.create_task(_weekly_worker())


async def _stop_worker() -> None:
    global _WORKER
    if _WORKER is not None:
        _WORKER.cancel()
        try:
            await _WORKER
        except asyncio.CancelledError:
            pass
        _WORKER = None


def backfill_fulfilled_vip() -> None:
    """Honor already fulfilled VIP purchases without charging them again."""
    from .extended_features import SpendRequest
    with core.SessionLocal() as session:
        with session.begin():
            rows = session.scalars(
                select(SpendRequest)
                .where(SpendRequest.status == "fulfilled")
                .order_by(SpendRequest.processed_at.asc(), SpendRequest.id.asc())
            ).all()
            for req in rows:
                if is_vip_reward(req.reward_title):
                    activate_vip(
                        session, req.id, req.telegram_id,
                        req.processed_at or req.created_at,
                        enforce_cap=False,
                        announce=False,
                    )


def register_vip(app) -> None:
    global _REGISTERED
    if _REGISTERED:
        return
    core.Base.metadata.create_all(core.engine)
    backfill_fulfilled_vip()
    app.include_router(router)
    app.add_event_handler("startup", _start_worker)
    app.add_event_handler("shutdown", _stop_worker)
    _REGISTERED = True
