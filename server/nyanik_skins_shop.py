"""Limited Nyanik wallet backgrounds: four designs, six copies each, 500 paws.

Stock, debit, skin ownership and activation are committed in one transaction.
No startup action mints/spends paws or resets sale counts.
"""

from __future__ import annotations

import hashlib
import logging
import re
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, UniqueConstraint, select, text
from sqlalchemy.orm import Mapped, mapped_column

from . import backend_app as core
from .advanced_features import WalletNotification
from .appeals import WalletSkin, assign_skin_to_user
from .user_bans import BlockedUser


router = APIRouter()
_REGISTERED = False
LOG = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parent.parent
PRICE = 500
LIMIT = 6
AUTHOR = "HiTsumi$"
KEY_PATTERN = re.compile(r"[A-Za-z0-9_-]{16,64}\Z")

CATALOG = (
    {"sku": "moon_sail", "title": "Лунный парус", "description": "Ночной залив и лодка в лунном свете", "filename": "nyanik-moon-sail.webp", "sha256": "74bc91faf07ca2d23bd55953edd8265b124f89405778d398429fcf082d6a3b92"},
    {"sku": "lighthouse", "title": "Тихий маяк", "description": "Маяк на берегу в винных оттенках", "filename": "nyanik-lighthouse.webp", "sha256": "7925ec26069fb4636007d031d7d7c3bf74fe5623d07f5ff02afff9811301b26a"},
    {"sku": "balloon", "title": "Тихое небо", "description": "Воздушный шар и хвойные оттенки", "filename": "nyanik-balloon.webp", "sha256": "ff994c442895fcec2d5c8c7a2b49b2e30b51d7119b88146a3da2b2afe7806a64"},
    {"sku": "arch", "title": "Арка воспоминаний", "description": "Каменная арка в тёплых терракотовых тонах", "filename": "nyanik-arch.webp", "sha256": "da1df04ffa5e9a6e9840d1953b3020ef0b1f9a7ac113823a0e76f2a9c2be500c"},
)
BY_SKU = {item["sku"]: item for item in CATALOG}


class NyanikSkinListing(core.Base):
    __tablename__ = "nyanik_limited_skin_listings"

    sku: Mapped[str] = mapped_column(String(32), primary_key=True)
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    price: Mapped[int] = mapped_column(Integer, nullable=False)
    total: Mapped[int] = mapped_column(Integer, nullable=False)
    sold: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    skin_id: Mapped[int] = mapped_column(Integer, ForeignKey("wallet_skins.id"), nullable=False)


class NyanikSkinPurchase(core.Base):
    __tablename__ = "nyanik_limited_skin_purchases"
    __table_args__ = (
        UniqueConstraint("telegram_id", "sku", name="uq_nyanik_skin_user_sku"),
        UniqueConstraint("telegram_id", "request_key", name="uq_nyanik_skin_user_key"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.telegram_id", ondelete="CASCADE"), index=True, nullable=False)
    sku: Mapped[str] = mapped_column(String(32), ForeignKey("nyanik_limited_skin_listings.sku"), nullable=False)
    request_key: Mapped[str] = mapped_column(String(64), nullable=False)
    transaction_id: Mapped[int] = mapped_column(Integer, ForeignKey("transactions.id"), nullable=False, unique=True)
    price: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class BuySkin(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    sku: str = Field(min_length=1, max_length=32)
    request_key: str = Field(min_length=16, max_length=64)


def _seed() -> None:
    core.Base.metadata.create_all(core.engine, tables=[NyanikSkinListing.__table__, NyanikSkinPurchase.__table__], checkfirst=True)
    with core.SessionLocal.begin() as session:
        if session.get_bind().dialect.name == "postgresql":
            # Multiple app workers must not seed duplicate skins/listings.
            session.execute(text("SELECT pg_advisory_xact_lock(20261030, 506)"))
        for spec in CATALOG:
            path = ROOT / "assets" / "wallet-skins" / spec["filename"]
            if not path.is_file():
                raise RuntimeError(f"Не найден фон лавки: {path}")
            content = path.read_bytes()
            digest = hashlib.sha256(content).hexdigest()
            if digest != spec["sha256"] or len(content) > 2_000_000 or content[:4] != b"RIFF" or content[8:12] != b"WEBP":
                raise RuntimeError(f"Файл фона повреждён: {spec['filename']}")
            existing = session.scalar(
                select(WalletSkin).where(
                    WalletSkin.image_sha256 == digest,
                    WalletSkin.title == spec["title"],
                ).limit(1)
            )
            if existing is None:
                existing = WalletSkin(
                    title=spec["title"],
                    description=f"Лимитированная серия Няника · автор {AUTHOR}",
                    text_theme="light", image_mime="image/webp", image_data=content,
                    image_sha256=digest, image_width=1200, image_height=750,
                    is_template=False, is_active=True, created_at=datetime.now(timezone.utc),
                )
                session.add(existing)
                session.flush()
            listing = session.get(NyanikSkinListing, spec["sku"])
            if listing is None:
                session.add(NyanikSkinListing(
                    sku=spec["sku"], title=spec["title"], price=PRICE,
                    total=LIMIT, sold=0, skin_id=existing.id,
                ))
            elif (listing.title != spec["title"] or listing.price != PRICE or listing.total != LIMIT or listing.skin_id != existing.id):
                raise RuntimeError(f"Лот {spec['sku']} изменён после запуска. Ручная проверка обязательна")


def _state(session, telegram_id: int | None = None) -> dict:
    items = {row.sku: row for row in session.scalars(select(NyanikSkinListing)).all()}
    purchased = set()
    balance = None
    blocked = False
    if telegram_id is not None:
        purchased = set(session.scalars(
            select(NyanikSkinPurchase.sku).where(NyanikSkinPurchase.telegram_id == telegram_id)
        ))
        user = session.get(core.User, telegram_id)
        balance = user.balance if user else None
        blocked = session.get(BlockedUser, telegram_id) is not None
    ready = len(items) == len(CATALOG)
    result = []
    for spec in CATALOG:
        row = items.get(spec["sku"])
        skin = session.get(WalletSkin, row.skin_id) if row else None
        available = bool(skin and skin.is_active)
        ready = ready and available
        result.append({
            "sku": spec["sku"], "title": spec["title"], "description": spec["description"],
            "image": f"./assets/wallet-skins/{spec['filename']}",
            "price": row.price if row else PRICE,
            "total": row.total if row else LIMIT,
            "remaining": max(0, row.total - row.sold) if row else 0,
            "available": available,
            "purchased": spec["sku"] in purchased if telegram_id is not None else False,
        })
    return {"ok": True, "ready": ready, "balance": balance, "blocked": blocked,
            "items": result, "author": AUTHOR, "authenticated": telegram_id is not None}


@router.get("/api/nyanik-skins/catalog")
def catalog():
    with core.SessionLocal() as session:
        return _state(session)


@router.get("/api/nyanik-skins/status")
def status(x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data")):
    telegram = core.verify_init_data(x_telegram_init_data or "")
    with core.SessionLocal() as session:
        return _state(session, int(telegram["id"]))


@router.post("/api/nyanik-skins/buy")
def buy(payload: BuySkin, x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data")):
    telegram = core.verify_init_data(x_telegram_init_data or "")
    user_id = int(telegram["id"])
    if not KEY_PATTERN.fullmatch(payload.request_key):
        raise HTTPException(status_code=422, detail="Некорректный ключ покупки")
    if payload.sku not in BY_SKU:
        raise HTTPException(status_code=404, detail="Такого фона нет")
    with core.SessionLocal.begin() as session:
        # The listing row serializes purchases of the last copies on PostgreSQL.
        listing = session.scalar(
            select(NyanikSkinListing).where(NyanikSkinListing.sku == payload.sku).with_for_update()
        )
        if listing is None:
            raise HTTPException(status_code=503, detail="Лавка пока не готова")
        previous = session.scalar(select(NyanikSkinPurchase).where(
            NyanikSkinPurchase.telegram_id == user_id,
            NyanikSkinPurchase.request_key == payload.request_key,
        ))
        if previous:
            if previous.sku != payload.sku:
                raise HTTPException(status_code=409, detail="Ключ уже использован для другого фона")
            owner = session.get(core.User, user_id)
            return {"ok": True, "repeated": True, "balance": owner.balance if owner else 0, "sku": previous.sku}
        if session.get(BlockedUser, user_id) is not None:
            raise HTTPException(status_code=403, detail="Для вашего аккаунта покупки недоступны")
        if session.scalar(select(NyanikSkinPurchase.id).where(
            NyanikSkinPurchase.telegram_id == user_id,
            NyanikSkinPurchase.sku == payload.sku,
        )) is not None:
            raise HTTPException(status_code=409, detail="Этот фон уже есть в вашей коллекции")
        if listing.sold >= listing.total:
            raise HTTPException(status_code=409, detail="Все экземпляры этого фона распроданы")
        skin = session.get(WalletSkin, listing.skin_id)
        if skin is None or not skin.is_active:
            raise HTTPException(status_code=503, detail="Фон временно недоступен")
        user = session.scalar(
            select(core.User).where(core.User.telegram_id == user_id).with_for_update()
        )
        if user is None:
            raise HTTPException(status_code=404, detail="Сначала откройте Nyan Wallet")
        if int(user.balance) < PRICE:
            raise HTTPException(status_code=409, detail=f"Недостаточно лапкоинов. Нужно {PRICE} 🐾, на балансе {user.balance} 🐾")
        now = datetime.now(timezone.utc)
        user.balance = int(user.balance) - PRICE
        listing.sold += 1
        core.apply_telegram_profile(user, telegram, now)
        transaction = core.Transaction(
            telegram_id=user_id, amount=-PRICE, operation_type="nyanik_skin_purchase",
            description=f"Лавка Няника: фон «{listing.title}»", created_at=now,
        )
        session.add(transaction)
        session.flush()
        session.add(NyanikSkinPurchase(
            telegram_id=user_id, sku=listing.sku, request_key=payload.request_key,
            transaction_id=transaction.id, price=PRICE, created_at=now,
        ))
        assign_skin_to_user(session, user_id, skin, now)
        session.add(WalletNotification(
            telegram_id=user_id, kind="wallet_skin_purchase", title="Ваш новый фон Nyan Wallet",
            body=f"Фон «{listing.title}» за {PRICE} 🐾 приобретён и установлен. Осталось {user.balance} 🐾.",
            is_read=False, created_at=now,
        ))
        remaining = listing.total - listing.sold
        balance = int(user.balance)
    return {"ok": True, "repeated": False, "sku": payload.sku,
            "balance": balance, "remaining": remaining, "activated": True}


def register_nyanik_skins_shop(app) -> None:
    global _REGISTERED
    if _REGISTERED:
        return
    _seed()
    app.include_router(router)
    _REGISTERED = True
