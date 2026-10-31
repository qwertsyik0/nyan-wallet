"""NYAN TAKEOVER auctions with escrowed bids and atomic outbid refunds.

The owner manually opens and settles each lot. An unsettled winning bid remains
held (deducted from the wallet) until settlement or cancellation; all releases
are recorded as wallet transactions. Only approved private-flood residents bid.
"""

from __future__ import annotations

import re
from datetime import datetime

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, UniqueConstraint, select, text
from sqlalchemy.orm import Mapped, mapped_column

from . import backend_app as core
from .nyan_takeover import START, END, _active, _approved, _auth, _badge, _owner, now


router = APIRouter()
_REGISTERED = False
KEY_RE = re.compile(r"[a-zA-Z0-9_-]{16,64}\Z")
LOTS = (
    ("unique_title", "Уникальный титул", "Единственное звание во флуде", 600, 100, "service"),
    ("exclusive_badge", "Значок победителя", "Эксклюзивное достижение в Nyan Wallet", 900, 100, "badge"),
    ("next_event", "Следующее событие", "Право определить тему следующего большого события", 1000, 150, "service"),
    ("custom_wallet", "Особый дизайн", "Индивидуальный фон Nyan Wallet", 1250, 150, "service"),
    ("economy_founder", "Основатель экономики", "Постоянное редкое достижение резидента", 1500, 200, "badge"),
)
BY_LOT = {item[0]: item for item in LOTS}


class AuctionLot(core.Base):
    __tablename__ = "takeover_2026_auction_lots"
    key: Mapped[str] = mapped_column(String(32), primary_key=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="closed")
    top_bid: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    top_user_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.telegram_id"), nullable=True)
    settled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    fulfillment: Mapped[str] = mapped_column(String(16), nullable=False, default="none")


class AuctionBid(core.Base):
    __tablename__ = "takeover_2026_auction_bids"
    __table_args__ = (UniqueConstraint("telegram_id", "request_key", name="uq_takeover_bid_request"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    lot_key: Mapped[str] = mapped_column(String(32), ForeignKey("takeover_2026_auction_lots.key"), nullable=False)
    telegram_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.telegram_id", ondelete="CASCADE"), nullable=False)
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    request_key: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class BidPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    lot_key: str = Field(min_length=1, max_length=32)
    amount: int = Field(gt=0, le=100_000_000)
    request_key: str = Field(min_length=16, max_length=64)


class AuctionControl(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    lot_key: str = Field(min_length=1, max_length=32)
    action: str


def _visible(session, uid: int) -> dict:
    _approved(session, uid)
    rows = {row.key: row for row in session.scalars(select(AuctionLot))}
    result = []
    for key, title, description, starting, step, kind in LOTS:
        row = rows.get(key)
        if row is None:
            continue
        result.append({
            "key": key, "title": title, "description": description,
            "starting": starting, "step": step, "status": row.status,
            "top_bid": row.top_bid, "minimum_next": max(starting, row.top_bid + step),
            "is_leader": row.top_user_id == uid,
            "winner": row.top_user_id == uid and row.status == "settled",
            "fulfillment": row.fulfillment if row.top_user_id == uid else None,
            "kind": kind,
        })
    return {"ok": True, "lots": result}


@router.get("/api/nyan-takeover/auction")
def auction_state(x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data")):
    tg = _auth(x_telegram_init_data)
    with core.SessionLocal() as session:
        if core.is_owner(int(tg["id"])):
            # Owner can inspect all lots even if they are not a registered resident.
            rows = {r.key: r for r in session.scalars(select(AuctionLot))}
            return {"ok": True, "lots": [
                {"key": key, "title": title, "description": description,
                 "starting": start, "step": step, "status": rows[key].status,
                 "top_bid": rows[key].top_bid, "minimum_next": max(start, rows[key].top_bid + step),
                 "is_leader": rows[key].top_user_id == int(tg["id"]),
                 "winner": False, "fulfillment": rows[key].fulfillment,
                 "top_user_id": rows[key].top_user_id, "kind": kind}
                for key, title, description, start, step, kind in LOTS if key in rows]}
        return _visible(session, int(tg["id"]))


@router.post("/api/nyan-takeover/auction/bid")
def bid(payload: BidPayload, x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data")):
    tg = _auth(x_telegram_init_data)
    _active()
    if not KEY_RE.fullmatch(payload.request_key) or payload.lot_key not in BY_LOT:
        raise HTTPException(422, "Некорректная ставка")
    uid = int(tg["id"])
    with core.SessionLocal.begin() as session:
        lot = session.scalar(select(AuctionLot).where(AuctionLot.key == payload.lot_key).with_for_update())
        if lot is None or lot.status != "open":
            raise HTTPException(409, "Торги по этому лоту не открыты")
        _approved(session, uid)
        old = session.scalar(select(AuctionBid).where(AuctionBid.telegram_id == uid, AuctionBid.request_key == payload.request_key))
        if old is not None:
            if old.lot_key != payload.lot_key or old.amount != payload.amount:
                raise HTTPException(409, "Ключ ставки уже использован")
            return {"ok": True, "repeated": True, "bid": old.amount, "leading": lot.top_user_id == uid}
        start, step = BY_LOT[payload.lot_key][3:5]
        if payload.amount < max(start, lot.top_bid + step):
            raise HTTPException(409, f"Новая ставка должна быть не меньше {max(start, lot.top_bid + step)} 🐾")
        if lot.top_user_id == uid:
            raise HTTPException(409, "Ты уже лидируешь по этому лоту")
        # Lock users consistently to avoid cross-lot deadlocks on refund/debit.
        ids = sorted({uid, lot.top_user_id} - {None})
        locked = {}
        for user_id in ids:
            locked[user_id] = session.scalar(select(core.User).where(core.User.telegram_id == user_id).with_for_update())
        if locked[uid] is None or locked[uid].balance < payload.amount:
            raise HTTPException(409, "Недостаточно лапкоинов для ставки")
        stamp = now()
        if lot.top_user_id is not None:
            previous = locked[lot.top_user_id]
            if previous is None:
                raise HTTPException(503, "Не удалось вернуть предыдущую ставку")
            previous.balance += lot.top_bid
            session.add(core.Transaction(telegram_id=previous.telegram_id, amount=lot.top_bid,
                operation_type="takeover_bid_refund", description=f"Возврат ставки · {BY_LOT[lot.key][1]}", created_at=stamp))
        locked[uid].balance -= payload.amount
        session.add(core.Transaction(telegram_id=uid, amount=-payload.amount,
            operation_type="takeover_bid_hold", description=f"Ставка на аукционе · {BY_LOT[lot.key][1]}", created_at=stamp))
        lot.top_bid, lot.top_user_id = payload.amount, uid
        session.add(AuctionBid(lot_key=lot.key, telegram_id=uid, amount=payload.amount,
                               request_key=payload.request_key, created_at=stamp))
        balance = locked[uid].balance
    return {"ok": True, "repeated": False, "bid": payload.amount, "balance": balance, "leading": True}


@router.post("/api/nyan-takeover/owner/auction")
def owner_control(payload: AuctionControl, x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data")):
    _owner(x_telegram_init_data)
    if payload.lot_key not in BY_LOT or payload.action not in ("open", "settle", "cancel", "delivered"):
        raise HTTPException(422, "Неизвестный лот или действие")
    with core.SessionLocal.begin() as session:
        lot = session.scalar(select(AuctionLot).where(AuctionLot.key == payload.lot_key).with_for_update())
        if lot is None:
            raise HTTPException(404, "Лот отсутствует")
        if payload.action == "open":
            _active()
            if lot.status != "closed":
                raise HTTPException(409, "Торги уже открыты или завершены")
            lot.status = "open"
        elif payload.action == "settle":
            if lot.status != "open":
                raise HTTPException(409, "Торги должны быть открыты")
            if not lot.top_user_id:
                raise HTTPException(409, "По лоту не было ставок. Отмени торги.")
            if BY_LOT[lot.key][5] == "badge":
                user = session.scalar(select(core.User).where(core.User.telegram_id == lot.top_user_id).with_for_update())
                if not user:
                    raise HTTPException(503, "Победитель не найден")
                _badge(session, lot.top_user_id,
                       "economy_founder" if lot.key == "economy_founder" else "auction_winner", now())
            lot.status = "settled"
            lot.settled_at = now()
            lot.fulfillment = "done" if BY_LOT[lot.key][5] == "badge" else "pending"
        elif payload.action == "delivered":
            if lot.status != "settled" or lot.fulfillment != "pending":
                raise HTTPException(409, "Нет ожидающей выдачи награды")
            lot.fulfillment = "done"
        elif payload.action == "cancel":
            if lot.status not in ("closed", "open"):
                raise HTTPException(409, "Завершённый лот нельзя отменить")
            if lot.top_user_id:
                user = session.scalar(select(core.User).where(core.User.telegram_id == lot.top_user_id).with_for_update())
                if not user:
                    raise HTTPException(503, "Не удалось вернуть ставку")
                user.balance += lot.top_bid
                session.add(core.Transaction(telegram_id=user.telegram_id, amount=lot.top_bid,
                    operation_type="takeover_bid_refund", description=f"Отмена аукциона · {BY_LOT[lot.key][1]}", created_at=now()))
            lot.status = "cancelled"
            lot.fulfillment = "none"
            lot.settled_at = now()
    return {"ok": True, "status": lot.status, "winner_id": lot.top_user_id}


def register_nyan_takeover_auction(app) -> None:
    global _REGISTERED
    if _REGISTERED:
        return
    core.Base.metadata.create_all(core.engine, tables=[AuctionLot.__table__, AuctionBid.__table__], checkfirst=True)
    with core.SessionLocal.begin() as session:
        if session.get_bind().dialect.name == "postgresql":
            session.execute(text("SELECT pg_advisory_xact_lock(20261031, 702)"))
        for key, *_ in LOTS:
            if session.get(AuctionLot, key) is None:
                session.add(AuctionLot(key=key, status="closed", top_bid=0, fulfillment="none"))
    app.include_router(router)
    _REGISTERED = True
