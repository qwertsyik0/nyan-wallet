"""Nyanik's event shop. Closed by default; owner must stock and open it.

Purchases are one per SKU per Telegram user, transactional and idempotent.
No prize fulfilment is automated: paid vouchers are visible to the owner.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, select
from sqlalchemy.orm import Mapped, mapped_column

from . import backend_app as core
from .advanced_features import WalletNotification
from .user_bans import BlockedUser

router = APIRouter()
_REGISTERED = False
KEY_PATTERN = re.compile(r"[a-zA-Z0-9_-]{16,64}\Z")
CATALOG = (
    ("hint", "Подсказка Няника", "Намёк на решение загадки", 120, "boost"),
    ("chance", "Второй шанс", "Ещё одна попытка в раунде", 190, "boost"),
    ("box", "Тайная коробка", "Содержимое неизвестно до открытия", 320, "secret"),
    ("ticket", "Дополнительный билет", "Ещё один билет на финальный розыгрыш", 260, "boost"),
    ("key", "Золотой ключ", "Открывает тайный ящик", 590, "secret"),
    ("letter", "Запечатанное письмо", "Важная часть истории", 210, "secret"),
)


class LavkaWindow(core.Base):
    __tablename__ = "nyan_lavka_window"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closes_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    stopped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class LavkaItem(core.Base):
    __tablename__ = "nyan_lavka_items"
    sku: Mapped[str] = mapped_column(String(32), primary_key=True)
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    price: Mapped[int] = mapped_column(Integer, nullable=False)
    total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sold: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)


class LavkaPurchase(core.Base):
    __tablename__ = "nyan_lavka_purchases"
    __table_args__ = (
        UniqueConstraint("telegram_id", "sku", name="uq_lavka_user_sku"),
        UniqueConstraint("telegram_id", "request_key", name="uq_lavka_user_request"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.telegram_id", ondelete="CASCADE"), index=True, nullable=False)
    sku: Mapped[str] = mapped_column(String(32), ForeignKey("nyan_lavka_items.sku"), nullable=False)
    request_key: Mapped[str] = mapped_column(String(64), nullable=False)
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    transaction_id: Mapped[int] = mapped_column(Integer, ForeignKey("transactions.id"), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    redeemed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class BuyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    sku: str = Field(min_length=1, max_length=32)
    request_key: str = Field(min_length=16, max_length=64)


class StockRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    sku: str = Field(min_length=1, max_length=32)
    total: int = Field(ge=0, le=100_000)


class OpenRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    minutes: int = Field(default=60, ge=5, le=180)


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _is_open(window: LavkaWindow | None, now: datetime) -> bool:
    return bool(window and window.opened_at and window.closes_at and not window.stopped_at
                and _utc(window.opened_at) <= now < _utc(window.closes_at))


def _auth(raw: str | None) -> dict:
    return core.verify_init_data(raw or "")


def _seed() -> None:
    core.Base.metadata.create_all(core.engine, tables=[LavkaWindow.__table__, LavkaItem.__table__, LavkaPurchase.__table__], checkfirst=True)
    with core.SessionLocal.begin() as session:
        if session.get(LavkaWindow, 1) is None:
            session.add(LavkaWindow(id=1))
        for sku, title, description, price, kind in CATALOG:
            if session.get(LavkaItem, sku) is None:
                session.add(LavkaItem(sku=sku, title=title, description=description, price=price, kind=kind, total=0, sold=0))


def _state(session, now: datetime, telegram_id: int | None = None) -> dict:
    window = session.get(LavkaWindow, 1)
    items = session.scalars(select(LavkaItem).order_by(LavkaItem.price, LavkaItem.sku)).all()
    owned = set()
    balance = None
    if telegram_id is not None:
        owned = set(session.scalars(select(LavkaPurchase.sku).where(LavkaPurchase.telegram_id == telegram_id)).all())
        user = session.get(core.User, telegram_id)
        balance = user.balance if user else None
    return {
        "ok": True,
        "server_now": now.isoformat(),
        "is_open": _is_open(window, now),
        "has_opened": bool(window and window.opened_at),
        "closes_at": _utc(window.closes_at).isoformat() if window and window.closes_at else None,
        "ready": any(item.total > item.sold for item in items),
        "balance": balance,
        "items": [
            {"sku": i.sku, "title": i.title, "description": i.description, "price": i.price,
             "kind": i.kind, "total": i.total, "remaining": max(0, i.total - i.sold), "purchased": i.sku in owned}
            for i in items
        ],
    }


@router.get("/api/nyan-lavka/catalog")
def public_catalog():
    with core.SessionLocal() as session:
        state = _state(session, core.now_utc())
    state.pop("balance")
    for item in state["items"]:
        item.pop("purchased")
    return state


@router.get("/api/nyan-lavka/status")
def status(x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data")):
    telegram = _auth(x_telegram_init_data)
    with core.SessionLocal() as session:
        state = _state(session, core.now_utc(), int(telegram["id"]))
        state["blocked"] = session.get(BlockedUser, int(telegram["id"])) is not None
    state["is_owner"] = core.is_owner(int(telegram["id"]))
    return state


@router.post("/api/nyan-lavka/buy")
def buy(payload: BuyRequest, x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data")):
    telegram = _auth(x_telegram_init_data)
    if not KEY_PATTERN.fullmatch(payload.request_key):
        raise HTTPException(status_code=422, detail="Неверный ключ покупки")
    telegram_id = int(telegram["id"])
    with core.SessionLocal.begin() as session:
        window = session.scalar(select(LavkaWindow).where(LavkaWindow.id == 1).with_for_update())
        now = core.now_utc()
        existing = session.scalar(select(LavkaPurchase).where(LavkaPurchase.telegram_id == telegram_id,
                                LavkaPurchase.request_key == payload.request_key))
        if existing:
            if existing.sku != payload.sku:
                raise HTTPException(status_code=409, detail="Ключ уже использован для другого товара")
            user = session.get(core.User, telegram_id)
            return {"ok": True, "purchase": {"id": existing.id, "sku": existing.sku,
                    "price": existing.amount, "balance": user.balance if user else 0, "repeated": True}}
        if not _is_open(window, now):
            raise HTTPException(status_code=410, detail="Лавка сейчас закрыта")
        if session.get(BlockedUser, telegram_id):
            raise HTTPException(status_code=403, detail="Покупки недоступны")
        item = session.scalar(select(LavkaItem).where(LavkaItem.sku == payload.sku).with_for_update())
        if item is None:
            raise HTTPException(status_code=404, detail="Товар не найден")
        if item.total <= item.sold:
            raise HTTPException(status_code=409, detail="Товар закончился")
        if session.scalar(select(LavkaPurchase.id).where(LavkaPurchase.telegram_id == telegram_id, LavkaPurchase.sku == item.sku)):
            raise HTTPException(status_code=409, detail="Вы уже купили этот товар")
        user = session.scalar(select(core.User).where(core.User.telegram_id == telegram_id).with_for_update())
        if user is None:
            raise HTTPException(status_code=404, detail="Сначала откройте Nyan Wallet")
        if user.balance < item.price:
            raise HTTPException(status_code=409, detail=f"Не хватает лапкоинов: нужно {item.price} 🐾")
        user.balance -= item.price
        item.sold += 1
        core.apply_telegram_profile(user, telegram, now)
        txn = core.Transaction(telegram_id=telegram_id, amount=-item.price,
              operation_type="nyan_lavka_purchase", description=f"Лавка Няника: {item.title}", created_at=now)
        session.add(txn)
        session.flush()
        purchase = LavkaPurchase(telegram_id=telegram_id, sku=item.sku, request_key=payload.request_key,
                    amount=item.price, transaction_id=txn.id, created_at=now)
        session.add(purchase)
        session.flush()
        body = f"Вы приобрели «{item.title}» за {item.price} 🐾. Остаток: {user.balance} 🐾. Предмет сохранён до выдачи на интерактиве."
        session.add(WalletNotification(telegram_id=telegram_id, kind="nyan_lavka_purchase",
                    title="Лавка Няника", body=body, is_read=False, created_at=now))
        result = {"id": purchase.id, "sku": item.sku, "price": item.price, "balance": user.balance, "repeated": False}
    return {"ok": True, "purchase": result}


@router.post("/api/nyan-lavka/owner/stock")
def owner_stock(payload: StockRequest, x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data")):
    core.require_owner(_auth(x_telegram_init_data))
    with core.SessionLocal.begin() as session:
        window = session.scalar(select(LavkaWindow).where(LavkaWindow.id == 1).with_for_update())
        if window is None or window.opened_at is not None:
            raise HTTPException(status_code=409, detail="После открытия нельзя менять остатки")
        item = session.scalar(select(LavkaItem).where(LavkaItem.sku == payload.sku).with_for_update())
        if item is None:
            raise HTTPException(status_code=404, detail="Товар не найден")
        item.total = payload.total
    return {"ok": True, "sku": payload.sku, "total": payload.total}


@router.post("/api/nyan-lavka/owner/open")
def owner_open(payload: OpenRequest, x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data")):
    core.require_owner(_auth(x_telegram_init_data))
    with core.SessionLocal.begin() as session:
        window = session.scalar(select(LavkaWindow).where(LavkaWindow.id == 1).with_for_update())
        if window is None or window.opened_at is not None:
            raise HTTPException(status_code=409, detail="Лавка уже запускалась")
        if not session.scalar(select(LavkaItem.sku).where(LavkaItem.total > 0).limit(1)):
            raise HTTPException(status_code=409, detail="Сначала укажите остатки хотя бы одного товара")
        now = core.now_utc()
        window.opened_at = now
        window.closes_at = now + timedelta(minutes=payload.minutes)
    return {"ok": True, "closes_at": window.closes_at.isoformat()}


@router.post("/api/nyan-lavka/owner/close")
def owner_close(x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data")):
    core.require_owner(_auth(x_telegram_init_data))
    with core.SessionLocal.begin() as session:
        window = session.scalar(select(LavkaWindow).where(LavkaWindow.id == 1).with_for_update())
        if not window or not window.opened_at:
            raise HTTPException(status_code=409, detail="Лавку ещё не открывали")
        if window.stopped_at is None:
            window.stopped_at = core.now_utc()
    return {"ok": True}


@router.get("/api/nyan-lavka/owner/orders")
def owner_orders(x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data")):
    core.require_owner(_auth(x_telegram_init_data))
    with core.SessionLocal() as session:
        rows = session.execute(select(LavkaPurchase, LavkaItem, core.User)
            .join(LavkaItem, LavkaItem.sku == LavkaPurchase.sku)
            .join(core.User, core.User.telegram_id == LavkaPurchase.telegram_id)
            .order_by(LavkaPurchase.id.desc()).limit(500)).all()
    return {"ok": True, "orders": [
        {"id": order.id, "telegram_id": user.telegram_id, "username": user.username,
         "sku": item.sku, "title": item.title, "price": order.amount,
         "redeemed": order.redeemed_at is not None, "created_at": _utc(order.created_at).isoformat()}
        for order, item, user in rows
    ]}


@router.post("/api/nyan-lavka/owner/orders/{purchase_id}/redeem")
def owner_redeem(purchase_id: int, x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data")):
    core.require_owner(_auth(x_telegram_init_data))
    with core.SessionLocal.begin() as session:
        order = session.scalar(select(LavkaPurchase).where(LavkaPurchase.id == purchase_id).with_for_update())
        if order is None:
            raise HTTPException(status_code=404, detail="Покупка не найдена")
        if order.redeemed_at is None:
            order.redeemed_at = core.now_utc()
    return {"ok": True}


def register_nyan_lavka(app) -> None:
    global _REGISTERED
    if _REGISTERED:
        return
    _seed()
    app.include_router(router)
    _REGISTERED = True
