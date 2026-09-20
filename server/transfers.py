from __future__ import annotations

import hashlib
import hmac
import io
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any

import qrcode
import qrcode.image.svg
from fastapi import APIRouter, Header, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Mapped, Session, mapped_column

from server import backend_app as core

logger = logging.getLogger("nyan_wallet.transfers")

router = APIRouter()
_REGISTERED = False

BOT_USERNAME = os.getenv("NYAN_BOT_USERNAME", "nyancash_bot").strip().lstrip("@") or "nyancash_bot"
MAX_TRANSFER_AMOUNT = 100_000
MAX_TRANSFER_DAILY = 500_000
MAX_TRANSFERS_PER_MINUTE = 10
MAX_NOTE_LENGTH = 120
PUBLIC_ADDRESS_RE = re.compile(r"^NW[A-F0-9]{20}$")
WALLET_ALIAS_RE = re.compile(r"^NYAN\d{12}$")
IDEMPOTENCY_RE = re.compile(r"^[A-Za-z0-9_-]{16,64}$")


class WalletAddress(core.Base):
    __tablename__ = "wallet_addresses"

    telegram_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.telegram_id", ondelete="CASCADE"),
        primary_key=True,
    )
    public_id: Mapped[str] = mapped_column(String(24), nullable=False, unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class WalletAlias(core.Base):
    __tablename__ = "wallet_aliases"

    telegram_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.telegram_id", ondelete="CASCADE"),
        primary_key=True,
    )
    alias: Mapped[str] = mapped_column(String(16), nullable=False, unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class WalletTransfer(core.Base):
    __tablename__ = "wallet_transfers"
    __table_args__ = (
        UniqueConstraint("sender_id", "idempotency_key", name="uq_wallet_transfer_sender_idempotency"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    public_id: Mapped[str] = mapped_column(String(24), nullable=False, unique=True, index=True)
    sender_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.telegram_id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    recipient_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.telegram_id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)


class ClientLaunchDiagnostic(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    client_version: str = Field(min_length=1, max_length=40)
    detected_target: str | None = Field(default=None, max_length=80)
    unsafe_start_param: str | None = Field(default=None, max_length=120)
    init_start_param: str | None = Field(default=None, max_length=120)
    query_startapp: str | None = Field(default=None, max_length=120)
    query_tg_start: str | None = Field(default=None, max_length=120)
    hash_startapp: str | None = Field(default=None, max_length=120)
    hash_tg_start: str | None = Field(default=None, max_length=120)


class TransferRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    recipient: str = Field(min_length=1, max_length=80)
    amount: int = Field(ge=1, le=MAX_TRANSFER_AMOUNT)
    note: str | None = Field(default=None, max_length=MAX_NOTE_LENGTH)
    idempotency_key: str = Field(min_length=16, max_length=64)

    @field_validator("recipient")
    @classmethod
    def validate_recipient(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Получатель не указан")
        return normalized

    @field_validator("note")
    @classmethod
    def validate_note(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = " ".join(value.split())
        return normalized or None

    @field_validator("idempotency_key")
    @classmethod
    def validate_idempotency_key(cls, value: str) -> str:
        if not IDEMPOTENCY_RE.fullmatch(value):
            raise ValueError("Некорректный ключ операции")
        return value


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def public_wallet_id(telegram_id: int) -> str:
    digest = hmac.new(
        core.BOT_TOKEN.encode("utf-8"),
        f"nyan-wallet-address:{telegram_id}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return f"NW{digest[:20].upper()}"


def legacy_wallet_alias(telegram_id: int) -> str:
    """Return the same NYAN xxxx xxxx xxxx number the frontend historically showed."""
    value = f"nyan-wallet:{telegram_id}"
    left = 0x811C9DC5
    right = 0x9E3779B9

    for char in value:
        code = ord(char)
        left = ((left ^ code) * 16777619) & 0xFFFFFFFF
        right = ((right ^ code) * 2246822519) & 0xFFFFFFFF

    digits = f"{left % 1_000_000:06d}{right % 1_000_000:06d}"
    return f"NYAN{digits}"


def format_wallet_alias(alias: str) -> str:
    if not WALLET_ALIAS_RE.fullmatch(alias):
        return alias
    digits = alias[4:]
    return f"NYAN {digits[:4]} {digits[4:8]} {digits[8:12]}"


def _fallback_wallet_alias(telegram_id: int, attempt: int) -> str:
    digest = hmac.new(
        core.BOT_TOKEN.encode("utf-8"),
        f"nyan-wallet-alias:{telegram_id}:{attempt}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    digits = f"{int(digest[:16], 16) % 1_000_000_000_000:012d}"
    return f"NYAN{digits}"


def ensure_wallet_alias(session: Session, user: core.User, timestamp: datetime) -> WalletAlias:
    existing = session.get(WalletAlias, user.telegram_id)
    if existing is not None:
        return existing

    candidates = [legacy_wallet_alias(int(user.telegram_id))]
    candidates.extend(_fallback_wallet_alias(int(user.telegram_id), attempt) for attempt in range(1, 33))

    for candidate in candidates:
        owner = session.scalar(
            select(WalletAlias.telegram_id).where(WalletAlias.alias == candidate)
        )
        if owner is not None and int(owner) != int(user.telegram_id):
            continue

        alias = WalletAlias(
            telegram_id=int(user.telegram_id),
            alias=candidate,
            created_at=timestamp,
        )
        session.add(alias)
        session.flush()
        return alias

    raise HTTPException(status_code=500, detail="Не удалось создать уникальный номер кошелька")


def bootstrap_wallet_aliases() -> None:
    """Backfill aliases for existing users so NYAN numbers are resolvable immediately."""
    timestamp = now_utc()
    with core.SessionLocal() as session:
        with session.begin():
            users = session.scalars(
                select(core.User)
                .outerjoin(WalletAlias, WalletAlias.telegram_id == core.User.telegram_id)
                .where(WalletAlias.telegram_id.is_(None))
                .order_by(core.User.telegram_id.asc())
            ).all()
            for user in users:
                ensure_wallet_alias(session, user, timestamp)


def transfer_public_id(sender_id: int, idempotency_key: str) -> str:
    digest = hmac.new(
        core.BOT_TOKEN.encode("utf-8"),
        f"nyan-transfer:{sender_id}:{idempotency_key}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return f"NWT{digest[:16].upper()}"


def user_label(user: core.User) -> str:
    if user.username:
        return f"@{user.username}"
    name = " ".join(part for part in (user.first_name, user.last_name) if part).strip()
    return name or f"ID {user.telegram_id}"


def ensure_wallet_address(session: Session, user: core.User, timestamp: datetime) -> WalletAddress:
    address = session.get(WalletAddress, user.telegram_id)
    if address is not None:
        return address

    address = WalletAddress(
        telegram_id=user.telegram_id,
        public_id=public_wallet_id(user.telegram_id),
        created_at=timestamp,
    )
    session.add(address)
    session.flush()
    return address


def wallet_deep_link(address_token: str) -> str:
    return f"https://t.me/{BOT_USERNAME}?startapp=pay_{address_token}"


def serialize_recipient(
    user: core.User,
    address: WalletAddress,
    alias: WalletAlias,
) -> dict[str, Any]:
    return {
        "wallet_address": format_wallet_alias(alias.alias),
        "wallet_address_compact": alias.alias,
        "technical_address": address.public_id,
        "username": user.username,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "label": user_label(user),
    }


def serialize_transfer(
    transfer: WalletTransfer,
    sender: core.User,
    recipient: core.User,
    *,
    sender_balance: int,
) -> dict[str, Any]:
    return {
        "id": transfer.public_id,
        "amount": transfer.amount,
        "note": transfer.note,
        "created_at": transfer.created_at.isoformat(),
        "sender": {
            "telegram_id": sender.telegram_id,
            "label": user_label(sender),
        },
        "recipient": {
            "wallet_address": public_wallet_id(recipient.telegram_id),
            "label": user_label(recipient),
            "username": recipient.username,
        },
        "sender_balance": sender_balance,
        "sender_unlimited_balance": core.is_owner(sender.telegram_id),
    }


def normalize_target(raw_target: str) -> str:
    target = raw_target.strip()
    if not target:
        raise HTTPException(status_code=400, detail="Укажите получателя")
    return target


def resolve_recipient_id(session: Session, raw_target: str) -> int:
    target = normalize_target(raw_target)
    canonical = target.upper()
    compact = re.sub(r"[\s-]+", "", canonical)

    if WALLET_ALIAS_RE.fullmatch(compact):
        telegram_id = session.scalar(
            select(WalletAlias.telegram_id).where(WalletAlias.alias == compact)
        )
        if telegram_id is None:
            raise HTTPException(status_code=404, detail="Кошелёк с таким номером не найден")
        return int(telegram_id)

    if PUBLIC_ADDRESS_RE.fullmatch(canonical):
        telegram_id = session.scalar(
            select(WalletAddress.telegram_id).where(WalletAddress.public_id == canonical)
        )
        if telegram_id is None:
            raise HTTPException(status_code=404, detail="Кошелёк с таким адресом не найден")
        return int(telegram_id)

    plain = target[1:] if target.startswith("@") else target
    if plain.isdigit():
        user_id = int(plain)
        if user_id <= 0:
            raise HTTPException(status_code=400, detail="Некорректный Telegram ID")
        exists = session.scalar(select(core.User.telegram_id).where(core.User.telegram_id == user_id))
        if exists is None:
            raise HTTPException(
                status_code=404,
                detail="Пользователь не найден. Он должен хотя бы один раз открыть Nyan Wallet.",
            )
        return int(exists)

    if not re.fullmatch(r"[A-Za-z0-9_]{3,64}", plain):
        raise HTTPException(status_code=400, detail="Введите @username, Telegram ID или адрес кошелька")

    user_id = session.scalar(
        select(core.User.telegram_id).where(func.lower(core.User.username) == plain.lower())
    )
    if user_id is None:
        raise HTTPException(
            status_code=404,
            detail="Пользователь не найден. Проверьте username или попросите его открыть Nyan Wallet.",
        )
    return int(user_id)


def lock_users(session: Session, sender_id: int, recipient_id: int) -> tuple[core.User, core.User]:
    ids = sorted({sender_id, recipient_id})
    users = session.scalars(
        select(core.User)
        .where(core.User.telegram_id.in_(ids))
        .order_by(core.User.telegram_id.asc())
        .with_for_update()
    ).all()
    by_id = {int(user.telegram_id): user for user in users}
    sender = by_id.get(sender_id)
    recipient = by_id.get(recipient_id)
    if sender is None:
        raise HTTPException(status_code=404, detail="Ваш кошелёк не найден")
    if recipient is None:
        raise HTTPException(status_code=404, detail="Кошелёк получателя не найден")
    return sender, recipient


def check_transfer_limits(session: Session, sender_id: int, amount: int, timestamp: datetime) -> None:
    minute_ago = timestamp - timedelta(minutes=1)
    transfers_last_minute = session.scalar(
        select(func.count(WalletTransfer.id)).where(
            WalletTransfer.sender_id == sender_id,
            WalletTransfer.created_at >= minute_ago,
        )
    ) or 0
    if int(transfers_last_minute) >= MAX_TRANSFERS_PER_MINUTE:
        raise HTTPException(
            status_code=429,
            detail="Слишком много переводов. Попробуйте снова через минуту.",
        )

    day_ago = timestamp - timedelta(hours=24)
    sent_last_day = session.scalar(
        select(func.coalesce(func.sum(WalletTransfer.amount), 0)).where(
            WalletTransfer.sender_id == sender_id,
            WalletTransfer.created_at >= day_ago,
        )
    ) or 0
    if int(sent_last_day) + amount > MAX_TRANSFER_DAILY:
        remaining = max(0, MAX_TRANSFER_DAILY - int(sent_last_day))
        raise HTTPException(
            status_code=429,
            detail=f"Суточный лимит переводов превышен. Сейчас доступно: {remaining} 🐾.",
        )


def existing_idempotent_transfer(
    session: Session,
    sender_id: int,
    idempotency_key: str,
) -> WalletTransfer | None:
    return session.scalar(
        select(WalletTransfer).where(
            WalletTransfer.sender_id == sender_id,
            WalletTransfer.idempotency_key == idempotency_key,
        )
    )


def transfer_lapcoins(tg_user: dict[str, Any], payload: TransferRequest) -> dict[str, Any]:
    sender_id = int(tg_user["id"])
    timestamp = now_utc()

    # Ensure the authenticated sender exists before entering the money-moving transaction.
    core.get_or_create_user(tg_user)

    recipient_id: int | None = None

    try:
        with core.SessionLocal() as session:
            with session.begin():
                recipient_id = resolve_recipient_id(session, payload.recipient)
                if recipient_id == sender_id:
                    raise HTTPException(status_code=400, detail="Нельзя перевести лапкоины самому себе")

                existing = existing_idempotent_transfer(session, sender_id, payload.idempotency_key)
                if existing is not None:
                    sender = session.get(core.User, sender_id)
                    recipient = session.get(core.User, existing.recipient_id)
                    if sender is None or recipient is None:
                        raise HTTPException(status_code=500, detail="Не удалось восстановить состояние перевода")
                    if existing.recipient_id != recipient_id or existing.amount != payload.amount or existing.note != payload.note:
                        raise HTTPException(
                            status_code=409,
                            detail="Этот ключ операции уже использован для другого перевода",
                        )
                    return serialize_transfer(existing, sender, recipient, sender_balance=int(sender.balance))

                sender, recipient = lock_users(session, sender_id, recipient_id)
                recipient_address = ensure_wallet_address(session, recipient, timestamp)
                ensure_wallet_address(session, sender, timestamp)

                check_transfer_limits(session, sender_id, payload.amount, timestamp)

                if not core.is_owner(sender_id) and int(sender.balance) < payload.amount:
                    raise HTTPException(
                        status_code=409,
                        detail=f"Недостаточно лапкоинов. Доступно: {sender.balance} 🐾.",
                    )

                if not core.is_owner(sender_id):
                    sender.balance -= payload.amount
                recipient.balance += payload.amount

                transfer = WalletTransfer(
                    public_id=transfer_public_id(sender_id, payload.idempotency_key),
                    sender_id=sender_id,
                    recipient_id=recipient_id,
                    amount=payload.amount,
                    note=payload.note,
                    idempotency_key=payload.idempotency_key,
                    created_at=timestamp,
                )
                session.add(transfer)

                suffix = f" · {payload.note}" if payload.note else ""
                session.add(
                    core.Transaction(
                        telegram_id=sender_id,
                        amount=-payload.amount,
                        operation_type="transfer_out",
                        description=f"Перевод для {user_label(recipient)}{suffix}",
                        created_at=timestamp,
                    )
                )
                session.add(
                    core.Transaction(
                        telegram_id=recipient_id,
                        amount=payload.amount,
                        operation_type="transfer_in",
                        description=f"Перевод от {user_label(sender)}{suffix}",
                        created_at=timestamp,
                    )
                )
                session.flush()

                result = serialize_transfer(
                    transfer,
                    sender,
                    recipient,
                    sender_balance=int(sender.balance),
                )
                result["recipient"]["wallet_address"] = recipient_address.public_id

            logger.info(
                "wallet_transfer_completed transfer_id=%s sender_id=%s recipient_id=%s amount=%s",
                result["id"],
                sender_id,
                recipient_id,
                payload.amount,
            )
            return result
    except HTTPException:
        raise
    except IntegrityError as exc:
        # A retry can race with the original request. The unique sender/idempotency
        # constraint guarantees only one money movement survives.
        with core.SessionLocal() as recovery_session:
            existing = existing_idempotent_transfer(
                recovery_session,
                sender_id,
                payload.idempotency_key,
            )
            if existing is not None:
                sender = recovery_session.get(core.User, sender_id)
                recipient = recovery_session.get(core.User, existing.recipient_id)
                if sender is not None and recipient is not None:
                    if (
                        existing.amount == payload.amount
                        and existing.note == payload.note
                        and (recipient_id is None or existing.recipient_id == recipient_id)
                    ):
                        return serialize_transfer(
                            existing,
                            sender,
                            recipient,
                            sender_balance=int(sender.balance),
                        )
        logger.exception("wallet_transfer_integrity_error sender_id=%s", sender_id)
        raise HTTPException(status_code=409, detail="Конфликт операции. Обновите кошелёк и повторите.") from exc
    except SQLAlchemyError as exc:
        logger.exception("wallet_transfer_database_error sender_id=%s", sender_id)
        raise HTTPException(
            status_code=503,
            detail="База данных временно недоступна. Деньги не списаны, повторите позже.",
        ) from exc


@router.post("/api/client/launch")
async def client_launch_diagnostic(
    payload: ClientLaunchDiagnostic,
    x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data"),
):
    tg = core.verify_init_data(x_telegram_init_data or "")
    logger.warning(
        "client_launch telegram_id=%s version=%s detected=%r unsafe=%r init=%r q_startapp=%r q_tg=%r h_startapp=%r h_tg=%r",
        int(tg["id"]),
        payload.client_version,
        payload.detected_target,
        payload.unsafe_start_param,
        payload.init_start_param,
        payload.query_startapp,
        payload.query_tg_start,
        payload.hash_startapp,
        payload.hash_tg_start,
    )
    return {"ok": True}


@router.get("/api/wallet/address")
async def my_wallet_address(
    x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data"),
):
    tg = core.verify_init_data(x_telegram_init_data or "")
    core.get_or_create_user(tg)
    timestamp = now_utc()

    try:
        with core.SessionLocal() as session:
            with session.begin():
                user = session.scalar(
                    select(core.User)
                    .where(core.User.telegram_id == int(tg["id"]))
                    .with_for_update()
                )
                if user is None:
                    raise HTTPException(status_code=404, detail="Кошелёк не найден")
                address = ensure_wallet_address(session, user, timestamp)
                alias = ensure_wallet_alias(session, user, timestamp)
                return {
                    "ok": True,
                    "wallet_address": format_wallet_alias(alias.alias),
                    "wallet_address_compact": alias.alias,
                    "technical_address": address.public_id,
                    "deep_link": wallet_deep_link(alias.alias),
                    "limits": {
                        "per_transfer": MAX_TRANSFER_AMOUNT,
                        "per_24h": MAX_TRANSFER_DAILY,
                        "per_minute_count": MAX_TRANSFERS_PER_MINUTE,
                    },
                }
    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        logger.exception("wallet_address_database_error telegram_id=%s", tg["id"])
        raise HTTPException(status_code=503, detail="Не удалось загрузить адрес кошелька") from exc


@router.get("/api/transfers/recipient")
async def transfer_recipient(
    target: str = Query(min_length=1, max_length=80),
    x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data"),
):
    tg = core.verify_init_data(x_telegram_init_data or "")
    core.get_or_create_user(tg)

    with core.SessionLocal() as session:
        with session.begin():
            recipient_id = resolve_recipient_id(session, target)
            if recipient_id == int(tg["id"]):
                raise HTTPException(status_code=400, detail="Это ваш собственный кошелёк")
            recipient = session.scalar(
                select(core.User)
                .where(core.User.telegram_id == recipient_id)
                .with_for_update()
            )
            if recipient is None:
                raise HTTPException(status_code=404, detail="Получатель не найден")
            timestamp = now_utc()
            address = ensure_wallet_address(session, recipient, timestamp)
            alias = ensure_wallet_alias(session, recipient, timestamp)
            return {"ok": True, "recipient": serialize_recipient(recipient, address, alias)}


@router.post("/api/transfers")
async def create_transfer(
    payload: TransferRequest,
    x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data"),
):
    tg = core.verify_init_data(x_telegram_init_data or "")
    return {"ok": True, "transfer": transfer_lapcoins(tg, payload)}


@router.get("/api/wallet/qr")
async def wallet_qr(
    x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data"),
):
    tg = core.verify_init_data(x_telegram_init_data or "")
    core.get_or_create_user(tg)

    with core.SessionLocal() as session:
        with session.begin():
            user = session.scalar(
                select(core.User)
                .where(core.User.telegram_id == int(tg["id"]))
                .with_for_update()
            )
            if user is None:
                raise HTTPException(status_code=404, detail="Кошелёк не найден")
            timestamp = now_utc()
            address = ensure_wallet_address(session, user, timestamp)
            alias = ensure_wallet_alias(session, user, timestamp)
            deep_link = wallet_deep_link(alias.alias)

    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=8,
        border=4,
    )
    qr.add_data(deep_link)
    qr.make(fit=True)
    image = qr.make_image(image_factory=qrcode.image.svg.SvgPathImage)
    stream = io.BytesIO()
    image.save(stream)
    svg = stream.getvalue()

    return Response(
        content=svg,
        media_type="image/svg+xml",
        headers={
            "Cache-Control": "private, no-store",
            "Content-Disposition": "inline; filename=nyan-wallet-qr.svg",
            "X-Content-Type-Options": "nosniff",
        },
    )


def register_transfers(app) -> None:
    global _REGISTERED
    if _REGISTERED:
        return
    core.Base.metadata.create_all(core.engine)
    bootstrap_wallet_aliases()
    app.include_router(router)
    _REGISTERED = True
