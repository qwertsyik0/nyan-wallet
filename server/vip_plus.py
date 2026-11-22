"""Owner-managed Nyan VIP privileges, shop cashback and early access.

No user-facing endpoint can grant balances or raffle eligibility. A shop order
must be independently verified by the owner before it is recorded here.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, mapped_column

from . import backend_app as core
from .vip import VipSubscription, aware, now, status_for_user

router = APIRouter()
_REGISTERED = False


class VipManualGrant(core.Base):
    __tablename__ = "vip_manual_grants"
    __table_args__ = (
        UniqueConstraint("telegram_id", "kind", "event_key", name="uq_vip_grant_person_kind_event"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.telegram_id", ondelete="CASCADE"), index=True, nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)  # gift / raffle
    event_key: Mapped[str] = mapped_column(String(96), nullable=False)
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    amount: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    issued_by: Mapped[int] = mapped_column(BigInteger, nullable=False)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class VipEarlyAccess(core.Base):
    __tablename__ = "vip_early_access"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    enabled: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class VipShopCashback(core.Base):
    __tablename__ = "vip_shop_cashback"
    order_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.telegram_id", ondelete="CASCADE"), index=True, nullable=False)
    paid_kopecks: Mapped[int] = mapped_column(BigInteger, nullable=False)
    rate_percent: Mapped[int] = mapped_column(Integer, nullable=False)
    credited_lapcoins: Mapped[int] = mapped_column(Integer, nullable=False)
    purchased_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    recorded_by: Mapped[int] = mapped_column(BigInteger, nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class GrantPayload(BaseModel):
    telegram_id: int = Field(gt=0)
    kind: Literal["gift", "raffle"]
    event_key: str = Field(min_length=3, max_length=96)
    title: str = Field(min_length=1, max_length=160)
    # Gifts may be physical/digital (0 lapcoins); value is owner-defined.
    amount: int = Field(default=0, ge=0, le=100_000)


class RevokePayload(BaseModel):
    telegram_id: int = Field(gt=0)
    event_key: str = Field(min_length=3, max_length=96)


class ShopPurchasePayload(BaseModel):
    telegram_id: int = Field(gt=0)
    order_id: str = Field(min_length=3, max_length=96)
    paid_kopecks: int = Field(gt=0, le=100_000_000)
    purchased_at: datetime | None = None


class EarlyAccessPayload(BaseModel):
    enabled: bool
    title: str = Field(min_length=1, max_length=100)
    description: str = Field(max_length=2000)
    url: str | None = Field(default=None, max_length=500)


def _auth(value: str | None, *, owner: bool = False) -> dict:
    tg = core.verify_init_data(value or "")
    if owner:
        core.require_owner(tg)
    return tg


def _vip_active_at(session, telegram_id: int, timestamp: datetime) -> bool:
    timestamp = aware(timestamp)
    return session.scalar(select(VipSubscription.request_id).where(
        VipSubscription.telegram_id == telegram_id,
        VipSubscription.starts_at <= timestamp,
        VipSubscription.ends_at > timestamp,
    ).limit(1)) is not None


def _grant_data(row: VipManualGrant) -> dict:
    return {
        "id": row.id, "kind": row.kind, "event_key": row.event_key,
        "title": row.title, "amount": row.amount,
        "issued_at": aware(row.issued_at).isoformat(),
        "active": row.revoked_at is None,
    }


def _notify(session, telegram_id: int, title: str, message: str, kind: str) -> None:
    from .advanced_features import WalletNotification
    session.add(WalletNotification(
        telegram_id=telegram_id, kind=kind, title=title, body=message,
        is_read=False, created_at=now(),
    ))


def benefits_for_user(session, telegram_id: int, *, owner: bool = False) -> dict:
    current = status_for_user(session, telegram_id)
    active = bool(current["active"])
    grants = session.scalars(select(VipManualGrant).where(
        VipManualGrant.telegram_id == telegram_id,
        VipManualGrant.revoked_at.is_(None),
    ).order_by(VipManualGrant.issued_at.desc()).limit(40)).all()
    preview = session.get(VipEarlyAccess, 1)
    return {
        "active": active,
        "cashback_percent": 8 if active else 5,
        "standard_cashback_percent": 5,
        "priority_support": active,
        "exclusive_wallet_background": active,
        "profile_frame": active,
        "badge": active,
        "manual_gifts": [_grant_data(r) for r in grants if r.kind == "gift"],
        "raffle_entries": [_grant_data(r) for r in grants if r.kind == "raffle"] if active else [],
        # VIP-only early access is never exposed to non-VIP users.
        "early_access": {
            "title": preview.title,
            "description": preview.description,
            "url": preview.url,
        } if preview is not None and preview.enabled and (active or owner) else None,
        "early_access_available": bool(preview is not None and preview.enabled and (active or owner)),
        "is_owner": owner,
    }


@router.get("/api/vip/benefits")
def my_vip_benefits(
    x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data"),
):
    tg = _auth(x_telegram_init_data)
    core.get_or_create_user(tg)
    with core.SessionLocal() as session:
        return {"ok": True, **benefits_for_user(session, int(tg["id"]), owner=core.is_owner(int(tg["id"])))}


@router.post("/api/owner/vip/grants")
def owner_issue_vip_grant(
    payload: GrantPayload,
    x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data"),
):
    tg = _auth(x_telegram_init_data, owner=True)
    key = payload.event_key.strip()
    title = payload.title.strip()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9:_-]{2,95}", key) or not title:
        raise HTTPException(status_code=422, detail="Неверный код или название события")
    if payload.kind == "raffle" and payload.amount:
        raise HTTPException(status_code=422, detail="Допуск к розыгрышу не начисляет лапкоины")
    with core.SessionLocal.begin() as session:
        user = session.scalar(select(core.User).where(core.User.telegram_id == payload.telegram_id).with_for_update())
        if user is None:
            raise HTTPException(status_code=404, detail="Кошелёк участника не найден")
        previous = session.scalar(select(VipManualGrant).where(
            VipManualGrant.telegram_id == payload.telegram_id,
            VipManualGrant.kind == payload.kind,
            VipManualGrant.event_key == key,
        ).with_for_update())
        if previous is not None:
            return {"ok": True, "already_recorded": True, "grant": _grant_data(previous)}
        if not _vip_active_at(session, payload.telegram_id, now()):
            raise HTTPException(status_code=409, detail="У участника нет активной VIP подписки")
        item = VipManualGrant(
            telegram_id=payload.telegram_id, kind=payload.kind, event_key=key,
            title=title, amount=payload.amount, issued_by=int(tg["id"]), issued_at=now(),
        )
        session.add(item)
        if payload.amount > 0:
            user.balance += payload.amount
            session.add(core.Transaction(
                telegram_id=user.telegram_id, amount=payload.amount,
                operation_type="vip_manual_gift", description=title, created_at=now(),
            ))
        _notify(session, user.telegram_id, "VIP подарок" if payload.kind == "gift" else "VIP розыгрыш",
                f"{title}" + (f" (+{payload.amount} 🐾)" if payload.amount else ""),
                "vip_manual_gift" if payload.kind == "gift" else "vip_raffle_access")
        session.flush()
        result = _grant_data(item)
    return {"ok": True, "already_recorded": False, "grant": result}


@router.post("/api/owner/vip/raffles/revoke")
def owner_revoke_vip_raffle(
    payload: RevokePayload,
    x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data"),
):
    _auth(x_telegram_init_data, owner=True)
    with core.SessionLocal.begin() as session:
        row = session.scalar(select(VipManualGrant).where(
            VipManualGrant.telegram_id == payload.telegram_id,
            VipManualGrant.kind == "raffle", VipManualGrant.event_key == payload.event_key,
        ).with_for_update())
        if row is None:
            raise HTTPException(status_code=404, detail="Допуск не найден")
        if row.revoked_at is None:
            row.revoked_at = now()
    return {"ok": True}


@router.post("/api/owner/vip/early-access")
def owner_set_early_access(
    payload: EarlyAccessPayload,
    x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data"),
):
    _auth(x_telegram_init_data, owner=True)
    title = payload.title.strip()
    link = (payload.url or "").strip() or None
    if not title or (link is not None and not (link.startswith("https://") and len(link) > 8)):
        raise HTTPException(status_code=422, detail="Укажите название и HTTPS ссылку")
    with core.SessionLocal.begin() as session:
        item = session.scalar(select(VipEarlyAccess).where(VipEarlyAccess.id == 1).with_for_update())
        if item is None:
            item = VipEarlyAccess(id=1, title=title, description=payload.description.strip(),
                                  url=link, enabled=int(payload.enabled), updated_at=now())
            session.add(item)
        else:
            item.title = title
            item.description = payload.description.strip()
            item.url = link
            item.enabled = int(payload.enabled)
            item.updated_at = now()
    return {"ok": True}


def cashback_lapcoins(paid_kopecks: int, *, vip: bool) -> int:
    """Whole-lapcoin cashback: floor(kopecks × percent ÷ 10_000)."""
    return paid_kopecks * (8 if vip else 5) // 10_000


def _record_shop_purchase(payload: ShopPurchasePayload, recorded_by: int) -> dict:
    """Crediting logic shared by the owner UI and signed Shop checkout webhook."""
    key = payload.order_id.strip()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9:_-]{2,95}", key):
        raise HTTPException(status_code=422, detail="Некорректный ID заказа")
    purchased = aware(payload.purchased_at or now())
    if purchased > now() + timedelta(minutes=5) or purchased < now() - timedelta(days=90):
        raise HTTPException(status_code=422, detail="Дата покупки вне допустимого интервала")
    with core.SessionLocal.begin() as session:
        # Serialise all writes to this user's balance before evaluating the order.
        user = session.scalar(select(core.User).where(core.User.telegram_id == payload.telegram_id).with_for_update())
        if user is None:
            raise HTTPException(status_code=404, detail="Кошелёк покупателя не найден")
        previous = session.get(VipShopCashback, key)
        if previous is not None:
            if previous.telegram_id != payload.telegram_id or previous.paid_kopecks != payload.paid_kopecks:
                raise HTTPException(status_code=409, detail="Этот ID заказа уже принадлежит другой покупке")
            return {"ok": True, "already_recorded": True,
                    "credited_lapcoins": previous.credited_lapcoins,
                    "rate_percent": previous.rate_percent, "balance": user.balance}
        vip_at_purchase = _vip_active_at(session, payload.telegram_id, purchased)
        rate = 8 if vip_at_purchase else 5
        amount = cashback_lapcoins(payload.paid_kopecks, vip=vip_at_purchase)
        row = VipShopCashback(
            order_id=key, telegram_id=payload.telegram_id,
            paid_kopecks=payload.paid_kopecks, rate_percent=rate,
            credited_lapcoins=amount, purchased_at=purchased,
            recorded_by=recorded_by, recorded_at=now(),
        )
        session.add(row)
        if amount:
            user.balance += amount
            session.add(core.Transaction(
                telegram_id=user.telegram_id, amount=amount,
                operation_type="shop_cashback", description=f"Nyan Shop #{key} · {rate}%",
                created_at=now(),
            ))
            _notify(session, user.telegram_id, "Кэшбэк Nyan Shop",
                    f"Покупка #{key}: +{amount} 🐾 ({rate}% от суммы)", "shop_cashback")
        session.flush()
        balance = user.balance
    return {"ok": True, "already_recorded": False,
            "credited_lapcoins": amount, "rate_percent": rate, "balance": balance}



@router.post("/api/owner/vip/shop-cashback")
def owner_record_shop_purchase(
    payload: ShopPurchasePayload,
    x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data"),
):
    """Manual owner-confirmed PAID order. Never grant legacy 5% as well."""
    tg = _auth(x_telegram_init_data, owner=True)
    return _record_shop_purchase(payload, recorded_by=int(tg["id"]))


@router.post("/api/integrations/nyan-shop/cashback")
async def signed_shop_cashback(
    request: Request,
    x_nyan_shop_signature: str | None = Header(default=None, alias="X-Nyan-Shop-Signature"),
):
    """Shop's checkout calls this once after verifying payment.

    Signature = lowercase hex HMAC-SHA256 over the unmodified JSON request
    bytes, with the same strong NYAN_SHOP_CASHBACK_SECRET configured on both
    backends. Does not accept Telegram user credentials from the merchant.
    """
    secret = os.getenv("NYAN_SHOP_CASHBACK_SECRET", "").strip()
    if len(secret) < 32:
        raise HTTPException(status_code=503, detail="Shop cashback webhook не настроен")
    raw = await request.body()
    if not raw or len(raw) > 4096:
        raise HTTPException(status_code=413, detail="Неверный размер заказа")
    supplied = (x_nyan_shop_signature or "").strip()
    expected = hmac.new(secret.encode("utf-8"), raw, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(supplied, expected):
        raise HTTPException(status_code=401, detail="Подпись магазина недействительна")
    try:
        payload = ShopPurchasePayload.model_validate_json(raw)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail="Некорректные поля заказа") from exc
    return _record_shop_purchase(payload, recorded_by=0)


def register_vip_plus(app) -> None:
    global _REGISTERED
    if _REGISTERED:
        return
    core.Base.metadata.create_all(core.engine, tables=[
        VipManualGrant.__table__, VipEarlyAccess.__table__, VipShopCashback.__table__,
    ], checkfirst=True)
    app.include_router(router)
    _REGISTERED = True
