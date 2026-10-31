"""Private-group NYAN TAKEOVER: owner-approved access, one-time grant and market.

The bot is NOT a member of the private flood. No public link, passphrase or
Telegram username can prove membership. An owner must verify every application
in the group's member list before approving. All paid operations recheck this
server-side authorization in the same transaction as the debit.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, UniqueConstraint, func, select, text
from sqlalchemy.orm import Mapped, mapped_column

from . import backend_app as core
from .achievements import LimitedProfileBadge
from .appeals import WalletSkin, assign_skin_to_user
from .extended_features import send_telegram_message
from .user_bans import BlockedUser
from .nyan_takeover_group import group_member


router = APIRouter()
_REGISTERED = False
ROOT = Path(__file__).resolve().parent.parent
START = datetime(2026, 10, 31, 14, 30, tzinfo=timezone.utc)  # 17:30 Moscow
END = datetime(2026, 11, 1, 9, 0, tzinfo=timezone.utc)       # 12:00 Moscow
FLOOD_NAME = "𓏏 𐔌⫶ ׄ 𝙇𝙤𝙤𝙠 𝒮lׅ𝙩 𝙩𝙝ꫀ⁠⁠⁠ 𝙨𝙩a⁠⁠⁠𝙧𝙨 ݂ ՞ ꯭ ᪃"
KEY_RE = re.compile(r"[a-zA-Z0-9_-]{16,64}\Z")
CATALOG = (
    ("title_24h", "Особое звание", "Звание во флуде на 24 часа · выдаётся администрацией", 250, 5, "service", None),
    ("personal_card", "Персональная карточка", "Именная карточка от Nyan · создаётся вручную", 400, 8, "service", None),
    ("choose_bingo", "Выбор темы бинго", "Выбери тему следующего бинго во флуде", 600, 1, "service", None),
    ("flood_poll", "Свой опрос", "Твой опрос будет опубликован во флуде", 800, 2, "service", None),
    ("limited_badge", "Значок TAKEOVER", "Лимитированный значок для профиля Nyan Wallet", 1000, 3, "badge", "takeover_limited"),
    ("resident_skin", "Фон «Резидент»", "Светлый фон с фирменным котиком", 1500, 5, "skin", "resident"),
    ("founding_skin", "Фон «Ночная смена»", "Тёмный фон с хэллоуинским мишкой", 1500, 3, "skin", "founding"),
    ("economist_badge", "Экономист флуда", "Постоянное редкое достижение", 2000, 2, "badge", "economist"),
)
BY_SKU = {item[0]: item for item in CATALOG}
BADGES = {
    "resident": ("Резидент флуда", "badge-resident.png"),
    "founding": ("01 / FOUNDING RESIDENT", "badge-founding-resident.png"),
    "takeover_limited": ("NYAN TAKEOVER", "badge-takeover-limited.png"),
    "economist": ("Экономист флуда", "badge-economist.png"),
    "market_pioneer": ("Первопроходец рынка", "badge-market-pioneer.png"),
    "auction_winner": ("Победитель аукциона", "badge-auction-winner.png"),
    "economy_founder": ("Основатель экономики флуда", "badge-founding-resident.png"),
    "wallet_explorer": ("Исследователь кошелька", "badge-wallet-explorer.png"),
}
SKINS = {"resident": ("Резидент", "skin-resident.png", "dark"), "founding": ("Ночная смена", "skin-founding.png", "light")}


class TakeoverAccess(core.Base):
    __tablename__ = "takeover_2026_access"
    telegram_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.telegram_id", ondelete="CASCADE"), primary_key=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decided_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)


class TakeoverGrant(core.Base):
    __tablename__ = "takeover_2026_grants"
    telegram_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.telegram_id", ondelete="CASCADE"), primary_key=True)
    transaction_id: Mapped[int] = mapped_column(Integer, ForeignKey("transactions.id"), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class TakeoverMissionClaim(core.Base):
    __tablename__ = "takeover_2026_mission_claims"
    telegram_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.telegram_id", ondelete="CASCADE"), primary_key=True)
    transaction_id: Mapped[int] = mapped_column(Integer, ForeignKey("transactions.id"), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class TakeoverListing(core.Base):
    __tablename__ = "takeover_2026_listings"
    sku: Mapped[str] = mapped_column(String(32), primary_key=True)
    title: Mapped[str] = mapped_column(String(80), nullable=False)
    price: Mapped[int] = mapped_column(Integer, nullable=False)
    stock: Mapped[int] = mapped_column(Integer, nullable=False)
    sold: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    skin_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("wallet_skins.id"), nullable=True)


class TakeoverPurchase(core.Base):
    __tablename__ = "takeover_2026_purchases"
    __table_args__ = (
        UniqueConstraint("telegram_id", "sku", name="uq_takeover_user_sku"),
        UniqueConstraint("telegram_id", "request_key", name="uq_takeover_user_request"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.telegram_id", ondelete="CASCADE"), nullable=False, index=True)
    sku: Mapped[str] = mapped_column(String(32), ForeignKey("takeover_2026_listings.sku"), nullable=False)
    request_key: Mapped[str] = mapped_column(String(64), nullable=False)
    transaction_id: Mapped[int] = mapped_column(Integer, ForeignKey("transactions.id"), nullable=False, unique=True)
    fulfillment: Mapped[str] = mapped_column(String(16), nullable=False, default="done")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PurchaseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    sku: str = Field(min_length=1, max_length=32)
    request_key: str = Field(min_length=16, max_length=64)


class DecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    telegram_id: int = Field(gt=0)
    approved: bool


class FulfillRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    purchase_id: int = Field(gt=0)


def now() -> datetime:
    return datetime.now(timezone.utc)


def _auth(init_data: str | None) -> dict:
    return core.verify_init_data(init_data or "")


def _owner(init_data: str | None) -> dict:
    user = _auth(init_data)
    core.require_owner(user)
    return user


def _active() -> None:
    if not START <= now() < END:
        raise HTTPException(409, "Событие сейчас не проводится")


def _approved(session, telegram_id: int) -> None:
    if session.get(BlockedUser, telegram_id):
        raise HTTPException(403, "Для аккаунта операции недоступны")
    if not group_member(session, telegram_id):
        raise HTTPException(403, "Доступ только действующим участникам закрытого флуда")


def _badge(session, telegram_id: int, key: str, stamp: datetime) -> None:
    """Single transaction; use PostgreSQL advisory lock to serialize edition numbers."""
    badge_key = f"takeover_2026_{key}"
    if session.get(LimitedProfileBadge, (telegram_id, badge_key)):
        return
    # Caller locks user row; global edition sequences also need serialization.
    if session.get_bind().dialect.name == "postgresql":
        session.execute(text("SELECT pg_advisory_xact_lock(20261031, 700)"))
    edition = (session.scalar(select(func.max(LimitedProfileBadge.edition)).where(LimitedProfileBadge.badge_key == badge_key)) or 0) + 1
    session.add(LimitedProfileBadge(
        telegram_id=telegram_id, badge_key=badge_key,
        title=BADGES[key][0], edition=edition, acquired_at=stamp,
    ))
    session.flush()


def _seed() -> None:
    tables = [TakeoverAccess.__table__, TakeoverGrant.__table__, TakeoverMissionClaim.__table__, TakeoverListing.__table__, TakeoverPurchase.__table__]
    core.Base.metadata.create_all(core.engine, tables=tables, checkfirst=True)
    with core.SessionLocal.begin() as session:
        if session.get_bind().dialect.name == "postgresql":
            session.execute(text("SELECT pg_advisory_xact_lock(20261031, 701)"))
        skins = {}
        for key, (title, filename, theme) in SKINS.items():
            data = (ROOT / "assets" / "nyan-takeover" / filename).read_bytes()
            if not data.startswith(b"\x89PNG\r\n\x1a\n") or len(data) > 6_000_000:
                raise RuntimeError(f"Некорректный фон TAKEOVER: {filename}")
            digest = hashlib.sha256(data).hexdigest()
            skin = session.scalar(select(WalletSkin).where(WalletSkin.image_sha256 == digest).limit(1))
            if skin is None:
                skin = WalletSkin(
                    title=f"NYAN TAKEOVER · {title}", description="Ограниченная коллекция резидентов",
                    text_theme=theme, image_mime="image/png", image_data=data,
                    image_sha256=digest, image_width=1672, image_height=941,
                    is_template=False, is_active=True, created_at=now(),
                )
                session.add(skin)
                session.flush()
            skins[key] = skin.id
        for sku, title, _, price, stock, kind, asset in CATALOG:
            listing = session.get(TakeoverListing, sku)
            if listing is None:
                session.add(TakeoverListing(sku=sku, title=title, price=price, stock=stock,
                                            sold=0, skin_id=skins.get(asset) if kind == "skin" else None))
            elif listing.title != title or listing.price != price or listing.stock != stock:
                raise RuntimeError(f"Изменён опубликованный товар TAKEOVER: {sku}")


def _user_state(session, telegram_id: int, *, verified_member: bool = False) -> dict:
    user = session.get(core.User, telegram_id)
    status = "owner" if core.is_owner(telegram_id) else "approved" if verified_member else "none"
    if status not in ("approved", "owner"):
        # Do not expose the private flood name, lineup, stock or event metadata.
        return {"ok": True, "access": status, "owner": False}
    result = {
        "ok": True, "access": status, "owner": core.is_owner(telegram_id),
        "name": FLOOD_NAME, "starts_at": START.isoformat(), "ends_at": END.isoformat(),
        "event_open": START <= now() < END, "balance": user.balance if user else None,
        "claimed": False, "items": [], "purchases": [],
    }
    result["claimed"] = session.get(TakeoverGrant, telegram_id) is not None
    owned = {p.sku: p for p in session.scalars(select(TakeoverPurchase).where(TakeoverPurchase.telegram_id == telegram_id))}
    result["purchases"] = [{"sku": p.sku, "fulfillment": p.fulfillment} for p in owned.values()]
    listings = {row.sku: row for row in session.scalars(select(TakeoverListing)).all()}
    for sku, title, description, price, stock, kind, asset in CATALOG:
        listing = listings.get(sku)
        result["items"].append({
            "sku": sku, "title": title, "description": description, "price": price,
            "stock": stock, "remaining": max(0, stock - listing.sold) if listing else 0,
            "kind": kind, "asset": asset,
            "purchased": sku in owned, "fulfillment": owned[sku].fulfillment if sku in owned else None,
        })
    return result


FEATURES = {
    "fortune_spin": "Фортуна",
    "lottery_ticket": "Лотерея",
    "promo": "Промокод",
    "transfer_out": "Перевод",
    "takeover_purchase": "Рынок",
    "reward_request": "Заказ награды",
}


def _mission_state(session, telegram_id: int) -> dict:
    operation_types = session.scalars(select(core.Transaction.operation_type).where(
        core.Transaction.telegram_id == telegram_id,
        core.Transaction.created_at >= START,
        core.Transaction.created_at < END,
        core.Transaction.operation_type.in_(tuple(FEATURES)),
    ).distinct()).all()
    features = sorted({FEATURES[code] for code in operation_types})
    return {"ok": True, "progress": min(3, len(features)), "features": features,
            "claimed": session.get(TakeoverMissionClaim, telegram_id) is not None,
            "reward": 150}


@router.get("/api/nyan-takeover/mission")
def mission(x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data")):
    tg = _auth(x_telegram_init_data)
    with core.SessionLocal() as session:
        _approved(session, int(tg["id"]))
        return _mission_state(session, int(tg["id"]))


@router.post("/api/nyan-takeover/mission/claim")
def mission_claim(x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data")):
    tg = _auth(x_telegram_init_data)
    _active()
    uid = int(tg["id"])
    with core.SessionLocal.begin() as session:
        user = session.scalar(select(core.User).where(core.User.telegram_id == uid).with_for_update())
        if not user:
            raise HTTPException(404, "Сначала открой кошелёк")
        _approved(session, uid)
        mission = _mission_state(session, uid)
        if mission["claimed"]:
            return {"ok": True, "repeated": True, "balance": user.balance}
        if mission["progress"] < 3:
            raise HTTPException(409, "Используй три разные функции кошелька")
        stamp = now()
        user.balance += 150
        transaction = core.Transaction(telegram_id=uid, amount=150,
            operation_type="takeover_mission", description="NYAN TAKEOVER · три функции кошелька", created_at=stamp)
        session.add(transaction)
        session.flush()
        session.add(TakeoverMissionClaim(telegram_id=uid, transaction_id=transaction.id, created_at=stamp))
        _badge(session, uid, "wallet_explorer", stamp)
        return {"ok": True, "repeated": False, "balance": user.balance, "reward": 150}


@router.get("/api/nyan-takeover/status")
def status(x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data")):
    tg = _auth(x_telegram_init_data)
    uid = int(tg["id"])
    if core.is_owner(uid):
        with core.SessionLocal() as session:
            return _user_state(session, uid)
    with core.SessionLocal() as session:
        if session.get(BlockedUser, uid) or not group_member(session, uid):
            return _user_state(session, uid)
    core.get_or_create_user(tg)
    with core.SessionLocal() as session:
        return _user_state(session, uid, verified_member=True)


@router.post("/api/nyan-takeover/register")
def register(background_tasks: BackgroundTasks, x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data")):
    tg = _auth(x_telegram_init_data)
    if now() >= END:
        raise HTTPException(409, "Регистрация завершена")
    with core.SessionLocal() as session:
        _approved(session, int(tg["id"]))
    core.get_or_create_user(tg)
    return {"ok": True, "status": "approved"}


@router.post("/api/nyan-takeover/claim")
def claim(x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data")):
    tg = _auth(x_telegram_init_data)
    _active()
    uid = int(tg["id"])
    with core.SessionLocal.begin() as session:
        user = session.scalar(select(core.User).where(core.User.telegram_id == uid).with_for_update())
        if not user:
            raise HTTPException(404, "Сначала открой Nyan Wallet")
        _approved(session, uid)
        if session.get(TakeoverGrant, uid):
            return {"ok": True, "repeated": True, "balance": user.balance}
        stamp = now()
        user.balance += 500
        tx = core.Transaction(telegram_id=uid, amount=500, operation_type="takeover_start",
                              description="NYAN TAKEOVER · стартовый капитал", created_at=stamp)
        session.add(tx)
        session.flush()
        session.add(TakeoverGrant(telegram_id=uid, transaction_id=tx.id, created_at=stamp))
        _badge(session, uid, "resident", stamp)
        _badge(session, uid, "founding", stamp)
        result = user.balance
    return {"ok": True, "repeated": False, "balance": result, "reward": 500}


@router.post("/api/nyan-takeover/buy")
def buy(payload: PurchaseRequest, x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data")):
    tg = _auth(x_telegram_init_data)
    _active()
    if not KEY_RE.fullmatch(payload.request_key) or payload.sku not in BY_SKU:
        raise HTTPException(422, "Некорректный товар или ключ покупки")
    uid = int(tg["id"])
    with core.SessionLocal.begin() as session:
        listing = session.scalar(select(TakeoverListing).where(TakeoverListing.sku == payload.sku).with_for_update())
        if not listing:
            raise HTTPException(503, "Рынок ещё готовится")
        _approved(session, uid)
        previous = session.scalar(select(TakeoverPurchase).where(
            TakeoverPurchase.telegram_id == uid, TakeoverPurchase.request_key == payload.request_key))
        if previous:
            if previous.sku != payload.sku:
                raise HTTPException(409, "Ключ покупки уже использован")
            user = session.get(core.User, uid)
            return {"ok": True, "repeated": True, "balance": user.balance if user else None}
        if session.scalar(select(TakeoverPurchase.id).where(
            TakeoverPurchase.telegram_id == uid, TakeoverPurchase.sku == payload.sku)):
            raise HTTPException(409, "У тебя уже есть этот товар")
        if listing.sold >= listing.stock:
            raise HTTPException(409, "Товар закончился")
        user = session.scalar(select(core.User).where(core.User.telegram_id == uid).with_for_update())
        if not user or user.balance < listing.price:
            raise HTTPException(409, "Недостаточно лапкоинов")
        _, title, _, _, _, kind, asset = BY_SKU[payload.sku]
        stamp = now()
        user.balance -= listing.price
        listing.sold += 1
        tx = core.Transaction(telegram_id=uid, amount=-listing.price, operation_type="takeover_purchase",
                              description=f"NYAN TAKEOVER · {title}", created_at=stamp)
        session.add(tx)
        session.flush()
        fulfillment = "pending" if kind == "service" else "done"
        session.add(TakeoverPurchase(
            telegram_id=uid, sku=payload.sku, request_key=payload.request_key,
            transaction_id=tx.id, fulfillment=fulfillment, created_at=stamp,
        ))
        if kind == "badge" and asset:
            _badge(session, uid, asset, stamp)
        elif kind == "skin" and asset:
            skin = session.get(WalletSkin, listing.skin_id)
            if not skin or not skin.is_active:
                raise HTTPException(503, "Фон сейчас недоступен")
            assign_skin_to_user(session, uid, skin, stamp)
        _badge(session, uid, "market_pioneer", stamp)
        remaining, balance = listing.stock - listing.sold, user.balance
    return {"ok": True, "repeated": False, "balance": balance,
            "remaining": remaining, "fulfillment": fulfillment}


@router.get("/api/nyan-takeover/owner/requests")
def owner_requests(x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data")):
    _owner(x_telegram_init_data)
    with core.SessionLocal() as session:
        requests = session.scalars(select(TakeoverAccess).order_by(TakeoverAccess.requested_at.desc())).all()
        purchases = session.scalars(select(TakeoverPurchase).where(TakeoverPurchase.fulfillment == "pending").order_by(TakeoverPurchase.created_at)).all()
        def user_record(uid):
            user = session.get(core.User, uid)
            return {"telegram_id": uid, "username": user.username if user else None,
                    "first_name": user.first_name if user else ""}
        return {"ok": True, "requests": [
            {**user_record(row.telegram_id), "status": row.status,
             "requested_at": row.requested_at.isoformat()} for row in requests],
            "fulfillment": [
                {**user_record(row.telegram_id), "id": row.id, "sku": row.sku,
                 "title": BY_SKU[row.sku][1], "created_at": row.created_at.isoformat()}
                for row in purchases],
        }


@router.post("/api/nyan-takeover/owner/decision")
def owner_decision(payload: DecisionRequest, background_tasks: BackgroundTasks, x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data")):
    tg = _owner(x_telegram_init_data)
    with core.SessionLocal.begin() as session:
        access = session.scalar(select(TakeoverAccess).where(TakeoverAccess.telegram_id == payload.telegram_id).with_for_update())
        if not access:
            raise HTTPException(404, "Заявка не найдена")
        if access.status == "approved" and not payload.approved:
            raise HTTPException(409, "Уже допущенного резидента нельзя отклонить этим действием")
        if access.status == "rejected" and payload.approved:
            raise HTTPException(409, "Отклонённую заявку нужно разобрать вручную")
        access.status = "approved" if payload.approved else "rejected"
        access.decided_at = now()
        access.decided_by = int(tg["id"])
    background_tasks.add_task(send_telegram_message, payload.telegram_id,
        "NYAN TAKEOVER · участие подтверждено. Открой событие в Nyan Wallet и забери стартовые 500 🐾."
        if payload.approved else "NYAN TAKEOVER · заявка не прошла проверку участников флуда.")
    return {"ok": True, "status": access.status}


@router.post("/api/nyan-takeover/owner/fulfilled")
def owner_fulfilled(payload: FulfillRequest, x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data")):
    _owner(x_telegram_init_data)
    with core.SessionLocal.begin() as session:
        row = session.scalar(select(TakeoverPurchase).where(TakeoverPurchase.id == payload.purchase_id).with_for_update())
        if not row:
            raise HTTPException(404, "Покупка не найдена")
        if row.fulfillment == "pending":
            row.fulfillment = "done"
    return {"ok": True, "status": "done"}


def register_nyan_takeover(app) -> None:
    global _REGISTERED
    if _REGISTERED:
        return
    _seed()
    app.include_router(router)
    _REGISTERED = True
