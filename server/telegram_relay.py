"""Durable, authenticated Telegram notification outbox for the SprintHost relay.

Wallet mutations never depend on Telegram availability.  Transaction events are
inserted into this outbox using the *same database connection* as the ledger
entry, so a rolled-back operation cannot produce a notification.

The relay polls through the existing HTTPS API; it needs no inbound ports.
"""

from __future__ import annotations

import hmac
import logging
import os
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import BigInteger, DateTime, Integer, String, Text, and_, event, func, or_, select
from sqlalchemy.orm import Mapped, mapped_column

from . import backend_app as core


LOG = logging.getLogger("nyan_wallet.telegram_relay")
router = APIRouter()
_REGISTERED = False


def now() -> datetime:
    return datetime.now(timezone.utc)


def relay_enabled() -> bool:
    return bool(os.getenv("NYAN_TELEGRAM_RELAY_SECRET", "").strip())


class TelegramRelayMessage(core.Base):
    __tablename__ = "telegram_relay_outbox"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_key: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False, default="pending", index=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    lease_token: Mapped[str | None] = mapped_column(String(64), nullable=True)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    telegram_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(300), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


def _new_message(source_key: str, chat_id: int, body: str) -> dict:
    return {
        "source_key": source_key,
        "chat_id": int(chat_id),
        "body": body[:3800],
        "state": "pending",
        "attempts": 0,
        "created_at": now(),
    }


def queue_message(chat_id: int | None, text: str) -> None:
    """Queue non-ledger notices; safe to call after a committed transaction."""
    if not chat_id or not relay_enabled():
        return
    with core.SessionLocal.begin() as session:
        session.add(TelegramRelayMessage(**_new_message(
            "direct:" + uuid.uuid4().hex, int(chat_id), text
        )))


def _tx_notice(mapper, connection, target: core.Transaction) -> None:
    if not relay_enabled():
        return
    amount = int(target.amount)
    if amount == 0:
        return
    description = " ".join((target.description or "").split())[:500]
    operation = target.operation_type or "operation"
    verb = (f"Вам начислено +{amount} 🐾." if amount > 0
            else f"С вашего баланса списано {abs(amount)} 🐾.")
    body = verb + (f"\nПричина: {description}" if description else "")
    connection.execute(TelegramRelayMessage.__table__.insert().values(
        **_new_message(f"transaction:{target.id}:user", target.telegram_id, body)
    ))

    # The owner sees financial events independently of whether a user can
    # receive bot messages; do not let failed delivery affect the ledger.
    if core.OWNER_TELEGRAM_ID and int(target.telegram_id) != int(core.OWNER_TELEGRAM_ID):
        owner_body = (
            f"🐾 Nyan Wallet\nОперация: {operation}\n"
            f"Telegram ID: {target.telegram_id}\n"
            f"Сумма: {amount:+d} 🐾"
            + (f"\nПричина: {description}" if description else "")
        )
        connection.execute(TelegramRelayMessage.__table__.insert().values(
            **_new_message(f"transaction:{target.id}:owner", core.OWNER_TELEGRAM_ID, owner_body)
        ))


def queue_audit_notice(connection, audit_id: int, text: str) -> None:
    """Called by the audit INSERT listener within its original transaction."""
    if not relay_enabled() or not core.OWNER_TELEGRAM_ID:
        return
    connection.execute(TelegramRelayMessage.__table__.insert().values(
        **_new_message(f"audit:{audit_id}:owner", core.OWNER_TELEGRAM_ID, text)
    ))


def _authenticate(header: str | None) -> None:
    secret = os.getenv("NYAN_TELEGRAM_RELAY_SECRET", "").strip()
    if not secret or len(secret) < 32:
        raise HTTPException(status_code=503, detail="Telegram relay is not configured")
    if not header or not hmac.compare_digest(header, secret):
        raise HTTPException(status_code=401, detail="Unauthorized")


@router.get("/api/internal/telegram-relay/pull")
def pull_messages(
    limit: int = Query(default=20, ge=1, le=30),
    x_nyan_relay_secret: str | None = Header(default=None, alias="X-Nyan-Relay-Secret"),
):
    _authenticate(x_nyan_relay_secret)
    timestamp = now()
    output = []
    with core.SessionLocal.begin() as session:
        available = or_(
            and_(TelegramRelayMessage.state == "pending",
                 or_(TelegramRelayMessage.retry_at.is_(None),
                     TelegramRelayMessage.retry_at <= timestamp)),
            and_(TelegramRelayMessage.state == "leased",
                 TelegramRelayMessage.lease_until <= timestamp),
        )
        rows = session.scalars(
            select(TelegramRelayMessage)
            .where(available)
            .order_by(TelegramRelayMessage.id)
            .limit(limit)
            .with_for_update(skip_locked=True)
        ).all()
        for row in rows:
            row.state = "leased"
            row.lease_token = secrets.token_hex(20)
            row.lease_until = timestamp + timedelta(seconds=90)
            row.attempts += 1
            output.append({
                "id": row.id,
                "lease_token": row.lease_token,
                "chat_id": row.chat_id,
                "text": row.body,
            })
    return {"ok": True, "items": output}


class Ack(BaseModel):
    id: int = Field(ge=1)
    lease_token: str = Field(min_length=40, max_length=40)
    delivered: bool
    telegram_message_id: int | None = None
    permanent_failure: bool = False
    error: str | None = Field(default=None, max_length=300)


@router.get("/api/internal/telegram-relay/status")
def relay_status(
    x_nyan_relay_secret: str | None = Header(default=None, alias="X-Nyan-Relay-Secret"),
):
    _authenticate(x_nyan_relay_secret)
    with core.SessionLocal() as session:
        counts = dict(session.execute(
            select(TelegramRelayMessage.state, func.count(TelegramRelayMessage.id))
            .group_by(TelegramRelayMessage.state)
        ).all())
    return {"ok": True, "counts": counts}


@router.post("/api/internal/telegram-relay/ack")
def acknowledge_message(
    payload: Ack,
    x_nyan_relay_secret: str | None = Header(default=None, alias="X-Nyan-Relay-Secret"),
):
    _authenticate(x_nyan_relay_secret)
    with core.SessionLocal.begin() as session:
        row = session.scalar(
            select(TelegramRelayMessage)
            .where(TelegramRelayMessage.id == payload.id)
            .with_for_update()
        )
        if row is None:
            raise HTTPException(status_code=404, detail="Delivery not found")
        if row.state == "sent" and row.lease_token == payload.lease_token:
            return {"ok": True, "state": "sent"}
        if row.state != "leased" or row.lease_token != payload.lease_token:
            raise HTTPException(status_code=409, detail="Lease no longer valid")
        row.last_error = (payload.error or "")[:300] or None
        row.lease_until = None
        if payload.delivered:
            row.state = "sent"
            row.sent_at = now()
            row.telegram_message_id = payload.telegram_message_id
            row.last_error = None
        elif payload.permanent_failure:
            row.state = "failed"
        else:
            row.state = "pending"
            row.retry_at = now() + timedelta(seconds=min(300, 2 ** min(row.attempts, 8)))
        state = row.state
    return {"ok": True, "state": state}


def register_telegram_relay(app) -> None:
    global _REGISTERED
    if _REGISTERED:
        return
    if relay_enabled():
        if len(os.getenv("NYAN_TELEGRAM_RELAY_SECRET", "").strip()) < 32:
            raise RuntimeError("NYAN_TELEGRAM_RELAY_SECRET must be at least 32 characters")
        core.Base.metadata.create_all(core.engine, tables=[TelegramRelayMessage.__table__])
        event.listen(core.Transaction, "after_insert", _tx_notice)
        LOG.info("Telegram notification outbox enabled")
    app.include_router(router)
    _REGISTERED = True
