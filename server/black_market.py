"""Nyan Shop black market: a timed, finite, atomic lapcoin store.

The owner starts the only 20-minute sale.  A purchase locks the market window,
stock row and the buyer's wallet in one database transaction.  Products are
limited per user, and retries use a durable idempotency key.
"""

from __future__ import annotations

import hashlib
import logging
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, select
from sqlalchemy.orm import Mapped, mapped_column

from . import backend_app as core
from .advanced_features import WalletNotification
from .appeals import WalletSkin, assign_skin_to_user
from .telegram_relay import TelegramRelayMessage, _new_message, relay_enabled
from .user_bans import BlockedUser

LOG = logging.getLogger(__name__)
router = APIRouter()
_REGISTERED = False
ONE_WINDOW = 1
SALE_MINUTES = 20
KEY_PATTERN = re.compile(r"[a-zA-Z0-9_-]{16,64}\Z")
ROOT = Path(__file__).resolve().parent.parent

# Stable identifiers: never change the SKU of an item after it has sold.
CATALOG = (
    ("secret_key", "Ключ от тайной комнаты", "Откроет дополнительную загадку на следующем интерактиве", 300, 10, "voucher", None),
    ("nyanik_eye", "Глаз Няника", "Особая подсказка в следующем интерактиве", 450, 7, "voucher", None),
    ("backstage", "Пропуск за кулисы", "Доступ к закрытому бонусному раунду", 700, 5, "voucher", None),
    ("midnight", "Кошелёк «После полуночи»", "Лимитированный фон Nyan Wallet", 1200, 3, "skin", "black-market-midnight.webp"),
    ("dark_nyanik", "Кошелёк «Тёмный Няник»", "Единственный экземпляр золотисто-тёмного фона", 2000, 1, "skin", "black-market-dark-nyanik.webp"),
)


class MarketWindow(core.Base):
    __tablename__ = "nyan_black_market_windows"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closes_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    stopped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class MarketItem(core.Base):
    __tablename__ = "nyan_black_market_items"

    sku: Mapped[str] = mapped_column(String(32), primary_key=True)
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    price: Mapped[int] = mapped_column(Integer, nullable=False)
    total: Mapped[int] = mapped_column(Integer, nullable=False)
    sold: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    skin_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("wallet_skins.id"), nullable=True)


class MarketPurchase(core.Base):
    __tablename__ = "nyan_black_market_purchases"
    __table_args__ = (
        UniqueConstraint("telegram_id", "sku", name="uq_black_market_user_item"),
        UniqueConstraint("telegram_id", "request_key", name="uq_black_market_user_request"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.telegram_id", ondelete="CASCADE"), index=True, nullable=False)
    sku: Mapped[str] = mapped_column(String(32), ForeignKey("nyan_black_market_items.sku"), nullable=False)
    request_key: Mapped[str] = mapped_column(String(64), nullable=False)
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    transaction_id: Mapped[int] = mapped_column(Integer, ForeignKey("transactions.id"), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    redeemed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class BuyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    sku: str = Field(min_length=1, max_length=32)
    request_key: str = Field(min_length=16, max_length=64)


def utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def open_now(window: MarketWindow | None, now: datetime) -> bool:
    return bool(window and window.opened_at and window.closes_at and not window.stopped_at and utc(window.opened_at) <= now < utc(window.closes_at))


def _auth(data: str | None) -> dict:
    return core.verify_init_data(data or "")


def _receipt(row: MarketPurchase, balance: int, *, repeated: bool = False) -> dict:
    return {"id": row.id, "sku": row.sku, "price": row.amount, "balance": balance, "created_at": utc(row.created_at).isoformat(), "repeated": repeated}


def _skin_for_asset(session, title: str, filename: str, now: datetime) -> WalletSkin | None:
    path = ROOT / "assets" / "wallet-skins" / filename
    if not path.is_file():
        LOG.warning("Nyan black market image missing: %s", path)
        return None
    content = path.read_bytes()
    if not (20 <= len(content) <= 2_000_000 and content[:4] == b"RIFF" and content[8:12] == b"WEBP"):
        LOG.warning("Nyan black market image invalid: %s", path)
        return None
    digest = hashlib.sha256(content).hexdigest()
    skin = session.scalar(select(WalletSkin).where(WalletSkin.image_sha256 == digest, WalletSkin.title == title).limit(1))
    if skin is None:
        skin = WalletSkin(
            title=title, description="Лимитированная серия · Чёрный рынок Няника",
            text_theme="light", image_mime="image/webp", image_data=content,
            image_sha256=digest, image_width=1536, image_height=1024,
            is_template=False, is_active=True, created_at=now,
        )
        session.add(skin)
        session.flush()
    return skin


def _seed() -> None:
    core.Base.metadata.create_all(core.engine, tables=[MarketWindow.__table__, MarketItem.__table__, MarketPurchase.__table__], checkfirst=True)
    with core.SessionLocal.begin() as session:
        window = session.get(MarketWindow, ONE_WINDOW)
        if window is None:
            session.add(MarketWindow(id=ONE_WINDOW))
        for sku, title, description, price, stock, kind, filename in CATALOG:
            item = session.get(MarketItem, sku)
            if item is None:
                item = MarketItem(sku=sku, title=title, description=description, price=price, total=stock, sold=0, kind=kind)
                session.add(item)
                session.flush()
            # Do not silently change prices or counts for existing sales.
            if kind == "skin" and item.skin_id is None and filename:
                skin = _skin_for_asset(session, title, filename, core.now_utc())
                if skin:
                    item.skin_id = skin.id


def _serialize_state(session, telegram_id: int, now: datetime) -> dict:
    window = session.get(MarketWindow, ONE_WINDOW)
    items = session.scalars(select(MarketItem).order_by(MarketItem.price, MarketItem.sku)).all()
    purchased = session.scalars(select(MarketPurchase).where(MarketPurchase.telegram_id == telegram_id)).all()
    owned = {row.sku for row in purchased}
    user = session.get(core.User, telegram_id)
    active = open_now(window, now)
    ready = len(items) == len(CATALOG) and all(i.kind != "skin" or i.skin_id is not None for i in items)
    return {
        "ok": True,
        "server_now": now.isoformat(), "is_open": active,
        "has_opened": bool(window and window.opened_at),
        "opens_at": utc(window.opened_at).isoformat() if window and window.opened_at else None,
        "closes_at": utc(window.closes_at).isoformat() if window and window.closes_at else None,
        "closed_early": bool(window and window.stopped_at),
        "ready": ready, "is_owner": core.is_owner(telegram_id),
        "balance": user.balance if user else None,
        "items": [
            {"sku": i.sku, "title": i.title, "description": i.description, "price": i.price,
             "total": i.total, "remaining": max(0, i.total - i.sold),
             "kind": i.kind, "purchased": i.sku in owned}
            for i in items
        ],
        "purchases": [
            {"id": row.id, "sku": row.sku, "price": row.amount, "created_at": utc(row.created_at).isoformat()}
            for row in purchased
        ],
    }


@router.get("/api/black-market")
def status(x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data")):
    user = _auth(x_telegram_init_data)
    with core.SessionLocal() as session:
        result = _serialize_state(session, user["id"], core.now_utc())
        result["blocked"] = session.get(BlockedUser, int(user["id"])) is not None
        return result


@router.get("/api/black-market/catalog")
def public_catalog():
    """Public, read-only stock and countdown for channel links outside Telegram."""
    with core.SessionLocal() as session:
        data = _serialize_state(session, 0, core.now_utc())
    return {"ok": True, "server_now": data["server_now"], "is_open": data["is_open"],
            "has_opened": data["has_opened"], "opens_at": data["opens_at"],
            "closes_at": data["closes_at"], "ready": data["ready"], "items": [
                {key: value for key, value in item.items() if key != "purchased"}
                for item in data["items"]
            ]}


@router.post("/api/black-market/buy")
def buy(payload: BuyRequest, x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data")):
    telegram = _auth(x_telegram_init_data)
    if not KEY_PATTERN.fullmatch(payload.request_key):
        raise HTTPException(status_code=422, detail="Неверный ключ покупки")
    now = core.now_utc()
    with core.SessionLocal.begin() as session:
        window = session.scalar(select(MarketWindow).where(MarketWindow.id == ONE_WINDOW).with_for_update())
        previous = session.scalar(select(MarketPurchase).where(MarketPurchase.telegram_id == telegram["id"], MarketPurchase.request_key == payload.request_key))
        if previous is not None:
            if previous.sku != payload.sku:
                raise HTTPException(status_code=409, detail="Этот ключ уже использован для другого товара")
            user = session.get(core.User, telegram["id"])
            return {"ok": True, "purchase": _receipt(previous, user.balance if user else 0, repeated=True)}
        if not open_now(window, now):
            raise HTTPException(status_code=410, detail="Чёрный рынок сейчас закрыт")
        if session.get(BlockedUser, telegram["id"]) is not None:
            raise HTTPException(status_code=403, detail="Для вашего аккаунта покупки недоступны")
        item = session.scalar(select(MarketItem).where(MarketItem.sku == payload.sku).with_for_update())
        if item is None:
            raise HTTPException(status_code=404, detail="Такого товара нет")
        if item.total - item.sold <= 0:
            raise HTTPException(status_code=409, detail="Этот товар закончился")
        if item.kind == "skin" and (item.skin_id is None or not session.get(WalletSkin, item.skin_id)):
            raise HTTPException(status_code=503, detail="Дизайн временно недоступен")
        if session.scalar(select(MarketPurchase.id).where(MarketPurchase.telegram_id == telegram["id"], MarketPurchase.sku == item.sku)) is not None:
            raise HTTPException(status_code=409, detail="Вы уже купили этот товар")
        user = session.scalar(select(core.User).where(core.User.telegram_id == telegram["id"]).with_for_update())
        if user is None:
            raise HTTPException(status_code=404, detail="Сначала откройте основной Nyan Wallet")
        if user.balance < item.price:
            raise HTTPException(status_code=409, detail=f"Недостаточно лапкоинов: нужно {item.price} 🐾, у вас {user.balance} 🐾")
        user.balance -= item.price
        item.sold += 1
        core.apply_telegram_profile(user, telegram, now)
        transaction = core.Transaction(telegram_id=user.telegram_id, amount=-item.price,
                                       operation_type="black_market_purchase", description=f"Чёрный рынок Няника: {item.title}", created_at=now)
        session.add(transaction)
        session.flush()
        purchase = MarketPurchase(telegram_id=user.telegram_id, sku=item.sku, request_key=payload.request_key,
                                  amount=item.price, transaction_id=transaction.id, created_at=now)
        session.add(purchase)
        session.flush()
        if item.kind == "skin":
            assign_skin_to_user(session, user.telegram_id, session.get(WalletSkin, item.skin_id), now)
        body = f"Вы приобрели «{item.title}» на Чёрном рынке Няника за {item.price} 🐾. Остаток: {user.balance} 🐾."
        if item.kind == "voucher":
            body += " Предмет сохранён за вами и будет учтён в следующем интерактиве."
        session.add(WalletNotification(telegram_id=user.telegram_id, kind="black_market_purchase", title="Чёрный рынок Няника", body=body, is_read=False, created_at=now))
        if relay_enabled():
            session.add(TelegramRelayMessage(**_new_message(f"black_market_purchase:{purchase.id}", user.telegram_id, body)))
        receipt = _receipt(purchase, user.balance)
    return {"ok": True, "purchase": receipt}


@router.post("/api/black-market/owner/open")
def owner_open(x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data")):
    core.require_owner(_auth(x_telegram_init_data))
    with core.SessionLocal.begin() as session:
        window = session.scalar(select(MarketWindow).where(MarketWindow.id == ONE_WINDOW).with_for_update())
        if not window:
            raise HTTPException(status_code=503, detail="Рынок не установлен на сервере")
        if window.opened_at is not None:
            raise HTTPException(status_code=409, detail="Рынок уже запускался. Повторное открытие заблокировано")
        items = session.scalars(select(MarketItem).with_for_update()).all()
        if len(items) != len(CATALOG) or any(i.kind == "skin" and not i.skin_id for i in items):
            raise HTTPException(status_code=503, detail="Не все товары рынка подготовлены")
        now = core.now_utc()
        window.opened_at = now
        window.closes_at = now + timedelta(minutes=SALE_MINUTES)
    return {"ok": True, "closes_at": window.closes_at.isoformat()}


@router.post("/api/black-market/owner/close")
def owner_close(x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data")):
    core.require_owner(_auth(x_telegram_init_data))
    with core.SessionLocal.begin() as session:
        window = session.scalar(select(MarketWindow).where(MarketWindow.id == ONE_WINDOW).with_for_update())
        if not window or window.opened_at is None:
            raise HTTPException(status_code=409, detail="Рынок ещё не открывали")
        if window.stopped_at is None:
            window.stopped_at = core.now_utc()
    return {"ok": True}


@router.get("/api/black-market/owner/orders")
def owner_orders(x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data")):
    core.require_owner(_auth(x_telegram_init_data))
    with core.SessionLocal() as session:
        rows = session.execute(select(MarketPurchase, core.User, MarketItem).join(core.User, core.User.telegram_id == MarketPurchase.telegram_id)
            .join(MarketItem, MarketItem.sku == MarketPurchase.sku).order_by(MarketPurchase.id.desc()).limit(100)).all()
        return {"ok": True, "orders": [
            {"id": purchase.id, "telegram_id": user.telegram_id,
             "username": "@" + user.username if user.username else user.first_name,
             "sku": item.sku, "title": item.title, "kind": item.kind, "price": purchase.amount,
             "redeemed": bool(purchase.redeemed_at), "created_at": utc(purchase.created_at).isoformat()}
            for purchase, user, item in rows
        ]}


@router.post("/api/black-market/owner/orders/{purchase_id}/redeem")
def owner_redeem(purchase_id: int, x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data")):
    core.require_owner(_auth(x_telegram_init_data))
    with core.SessionLocal.begin() as session:
        order = session.scalar(select(MarketPurchase).where(MarketPurchase.id == purchase_id).with_for_update())
        if order is None:
            raise HTTPException(status_code=404, detail="Покупка не найдена")
        item = session.get(MarketItem, order.sku)
        if item.kind != "voucher":
            raise HTTPException(status_code=409, detail="Дизайн не требует использования")
        if order.redeemed_at is None:
            order.redeemed_at = core.now_utc()
    return {"ok": True, "redeemed": True}


def register_black_market(app) -> None:
    global _REGISTERED
    if _REGISTERED:
        return
    _seed()
    app.include_router(router)
    _REGISTERED = True
