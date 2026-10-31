"""Owner-controlled private NYAN TAKEOVER drops; one claim per approved user."""
from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, UniqueConstraint, select
from sqlalchemy.orm import Mapped, mapped_column

from . import backend_app as core
from .nyan_takeover import _active, _approved, _auth, _owner, now


router = APIRouter()
_REGISTERED = False


class Drop(core.Base):
    __tablename__ = "takeover_2026_drops"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    capacity: Mapped[int] = mapped_column(Integer, nullable=False)
    claimed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class DropClaim(core.Base):
    __tablename__ = "takeover_2026_drop_claims"
    __table_args__ = (UniqueConstraint("telegram_id", "drop_id", name="uq_takeover_drop_per_user"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.telegram_id", ondelete="CASCADE"), nullable=False)
    drop_id: Mapped[int] = mapped_column(Integer, ForeignKey("takeover_2026_drops.id"), nullable=False)
    transaction_id: Mapped[int] = mapped_column(Integer, ForeignKey("transactions.id"), unique=True, nullable=False)


class CreateDrop(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    amount: int = Field(ge=10, le=300)
    capacity: int = Field(ge=1, le=500)
    minutes: int = Field(ge=1, le=60)


class DropId(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    drop_id: int = Field(gt=0)


@router.get("/api/nyan-takeover/drops")
def list_drops(x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data")):
    tg = _auth(x_telegram_init_data)
    uid = int(tg["id"])
    with core.SessionLocal() as session:
        if not core.is_owner(uid):
            _approved(session, uid)
        stamp = now()
        items = session.scalars(select(Drop).where(Drop.active.is_(True), Drop.expires_at > stamp).order_by(Drop.id.desc())).all()
        result = []
        for item in items:
            claimed = session.scalar(select(DropClaim.id).where(DropClaim.drop_id == item.id, DropClaim.telegram_id == uid)) is not None
            result.append({"id": item.id, "amount": item.amount, "remaining": max(0, item.capacity - item.claimed),
                           "expires_at": item.expires_at.isoformat(), "claimed": claimed})
        return {"ok": True, "items": result}


@router.post("/api/nyan-takeover/drops/claim")
def claim_drop(payload: DropId, x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data")):
    tg = _auth(x_telegram_init_data)
    _active()
    uid = int(tg["id"])
    with core.SessionLocal.begin() as session:
        item = session.scalar(select(Drop).where(Drop.id == payload.drop_id).with_for_update())
        if not item:
            raise HTTPException(404, "Раздача не найдена")
        _approved(session, uid)
        previous = session.scalar(select(DropClaim.id).where(DropClaim.telegram_id == uid, DropClaim.drop_id == item.id))
        if previous:
            return {"ok": True, "repeated": True}
        if not item.active or now() >= core.normalize_datetime(item.expires_at) or item.claimed >= item.capacity:
            raise HTTPException(409, "Раздача закончилась")
        user = session.scalar(select(core.User).where(core.User.telegram_id == uid).with_for_update())
        if not user:
            raise HTTPException(404, "Кошелёк не найден")
        stamp = now()
        user.balance += item.amount
        item.claimed += 1
        tx = core.Transaction(telegram_id=uid, amount=item.amount, operation_type="takeover_drop",
                              description=f"NYAN DROPS · раздача №{item.id}", created_at=stamp)
        session.add(tx)
        session.flush()
        session.add(DropClaim(telegram_id=uid, drop_id=item.id, transaction_id=tx.id))
        return {"ok": True, "repeated": False, "reward": item.amount, "balance": user.balance}


@router.post("/api/nyan-takeover/owner/drops")
def owner_create_drop(payload: CreateDrop, x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data")):
    _owner(x_telegram_init_data)
    _active()
    with core.SessionLocal.begin() as session:
        stamp = now()
        drop = Drop(amount=payload.amount, capacity=payload.capacity, claimed=0,
                    active=True, created_at=stamp, expires_at=stamp + timedelta(minutes=payload.minutes))
        session.add(drop)
        session.flush()
        return {"ok": True, "id": drop.id, "amount": drop.amount, "expires_at": drop.expires_at.isoformat()}


@router.post("/api/nyan-takeover/owner/drops/close")
def owner_close_drop(payload: DropId, x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data")):
    _owner(x_telegram_init_data)
    with core.SessionLocal.begin() as session:
        drop = session.scalar(select(Drop).where(Drop.id == payload.drop_id).with_for_update())
        if not drop:
            raise HTTPException(404, "Раздача не найдена")
        drop.active = False
    return {"ok": True}


def register_nyan_takeover_drops(app) -> None:
    global _REGISTERED
    if _REGISTERED:
        return
    core.Base.metadata.create_all(core.engine, tables=[Drop.__table__, DropClaim.__table__], checkfirst=True)
    app.include_router(router)
    _REGISTERED = True
