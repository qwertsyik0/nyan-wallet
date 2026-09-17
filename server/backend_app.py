import hashlib
import hmac
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qsl

from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
    func,
    or_,
    select,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

BOT_TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL") or f"sqlite:///{ROOT / 'wallet.db'}"
OWNER_TELEGRAM_ID_RAW = os.getenv("OWNER_TELEGRAM_ID", "").strip()

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN отсутствует")

OWNER_TELEGRAM_ID: int | None = None
if OWNER_TELEGRAM_ID_RAW:
    try:
        OWNER_TELEGRAM_ID = int(OWNER_TELEGRAM_ID_RAW)
    except ValueError as exc:
        raise RuntimeError("OWNER_TELEGRAM_ID должен быть числом") from exc

if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+psycopg://", 1)
elif DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg://", 1)

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, pool_pre_ping=True, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    telegram_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    first_name: Mapped[str] = mapped_column(String(255), nullable=False)
    last_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    balance: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    transactions: Mapped[list["Transaction"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )


class Transaction(Base):
    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telegram_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.telegram_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    operation_type: Mapped[str] = mapped_column(String(50), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    user: Mapped[User] = relationship(back_populates="transactions")


class PromoCode(Base):
    __tablename__ = "promo_codes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(32), nullable=False, unique=True, index=True)
    reward_amount: Mapped[int] = mapped_column(Integer, nullable=False)
    max_uses: Mapped[int | None] = mapped_column(Integer, nullable=True)
    uses_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PromoRedemption(Base):
    __tablename__ = "promo_redemptions"
    __table_args__ = (
        UniqueConstraint("promo_id", "telegram_id", name="uq_promo_redemption"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    promo_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("promo_codes.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    telegram_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.telegram_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    reward_amount: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PromoRedeemRequest(BaseModel):
    code: str = Field(min_length=1, max_length=32)


class OwnerGrantRequest(BaseModel):
    target: str = Field(min_length=1, max_length=64)
    amount: int = Field(ge=1, le=10_000_000)
    reason: str | None = Field(default=None, max_length=200)


class OwnerPromoCreateRequest(BaseModel):
    code: str = Field(min_length=2, max_length=32)
    reward_amount: int = Field(ge=1, le=10_000_000)
    max_uses: int | None = Field(default=None, ge=1, le=1_000_000)
    expires_at: datetime | None = None
    description: str | None = Field(default=None, max_length=200)


Base.metadata.create_all(engine)

app = FastAPI(title="Nyan Wallet API", version="1.4.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://qwertsyik0.github.io"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "X-Telegram-Init-Data"],
)

PROMO_PATTERN = re.compile(r"^[A-Z0-9_-]{2,32}$")


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def is_owner(telegram_id: int) -> bool:
    return OWNER_TELEGRAM_ID is not None and telegram_id == OWNER_TELEGRAM_ID


def require_owner(tg_user: dict) -> None:
    if not is_owner(tg_user["id"]):
        raise HTTPException(status_code=403, detail="Доступ только для владельца")


def normalize_promo_code(value: str) -> str:
    return value.strip().upper()


def normalize_datetime(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def serialize_transaction(tx: Transaction) -> dict:
    return {
        "id": tx.id,
        "amount": tx.amount,
        "operation_type": tx.operation_type,
        "description": tx.description,
        "created_at": tx.created_at.isoformat(),
    }


def serialize_user(user: User) -> dict:
    owner = is_owner(user.telegram_id)
    return {
        "telegram_id": user.telegram_id,
        "username": user.username,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "balance": user.balance,
        "is_owner": owner,
        "unlimited_balance": owner,
        "created_at": user.created_at.isoformat(),
        "last_seen_at": user.last_seen_at.isoformat(),
    }


def serialize_promo(promo: PromoCode) -> dict:
    return {
        "id": promo.id,
        "code": promo.code,
        "reward_amount": promo.reward_amount,
        "max_uses": promo.max_uses,
        "uses_count": promo.uses_count,
        "is_active": promo.is_active,
        "description": promo.description,
        "created_at": promo.created_at.isoformat(),
        "expires_at": promo.expires_at.isoformat() if promo.expires_at else None,
    }


def seed_bootstrap_promo() -> None:
    raw_code = os.getenv("BOOTSTRAP_PROMO_CODE", "").strip()
    raw_amount = os.getenv("BOOTSTRAP_PROMO_AMOUNT", "").strip()
    raw_max_uses = os.getenv("BOOTSTRAP_PROMO_MAX_USES", "").strip()

    if not raw_code or not raw_amount:
        return

    code = normalize_promo_code(raw_code)
    if not PROMO_PATTERN.fullmatch(code):
        raise RuntimeError("BOOTSTRAP_PROMO_CODE имеет недопустимый формат")

    try:
        amount = int(raw_amount)
    except ValueError as exc:
        raise RuntimeError("BOOTSTRAP_PROMO_AMOUNT должен быть целым числом") from exc

    if amount <= 0:
        raise RuntimeError("BOOTSTRAP_PROMO_AMOUNT должен быть больше нуля")

    max_uses: int | None = None
    if raw_max_uses:
        try:
            max_uses = int(raw_max_uses)
        except ValueError as exc:
            raise RuntimeError("BOOTSTRAP_PROMO_MAX_USES должен быть целым числом") from exc
        if max_uses <= 0:
            raise RuntimeError("BOOTSTRAP_PROMO_MAX_USES должен быть больше нуля")

    with SessionLocal() as session:
        existing = session.scalar(select(PromoCode).where(PromoCode.code == code))
        if existing is not None:
            return

        session.add(
            PromoCode(
                code=code,
                reward_amount=amount,
                max_uses=max_uses,
                uses_count=0,
                is_active=True,
                description="Тестовый промокод Nyan Wallet",
                created_at=now_utc(),
                expires_at=None,
            )
        )
        session.commit()


seed_bootstrap_promo()


def verify_init_data(init_data: str) -> dict:
    if not init_data:
        raise HTTPException(status_code=401, detail="Telegram initData отсутствует")

    pairs = dict(parse_qsl(init_data, keep_blank_values=True))
    received_hash = pairs.get("hash")

    if not received_hash:
        raise HTTPException(status_code=401, detail="Telegram hash отсутствует")

    auth_date_raw = pairs.get("auth_date")
    if not auth_date_raw:
        raise HTTPException(status_code=401, detail="auth_date отсутствует")

    try:
        auth_date = int(auth_date_raw)
    except ValueError:
        raise HTTPException(status_code=401, detail="Некорректный auth_date")

    if abs(int(time.time()) - auth_date) > 3600:
        raise HTTPException(
            status_code=401,
            detail="Telegram сессия устарела. Откройте Mini App заново.",
        )

    secret_key = hmac.new(
        b"WebAppData",
        BOT_TOKEN.encode(),
        hashlib.sha256,
    ).digest()

    def calculate_hash(exclude_signature: bool) -> str:
        values = {
            key: value
            for key, value in pairs.items()
            if key != "hash" and not (exclude_signature and key == "signature")
        }
        data_check_string = "\n".join(
            f"{key}={value}" for key, value in sorted(values.items())
        )
        return hmac.new(
            secret_key,
            data_check_string.encode(),
            hashlib.sha256,
        ).hexdigest()

    valid = hmac.compare_digest(calculate_hash(False), received_hash)
    if not valid and "signature" in pairs:
        valid = hmac.compare_digest(calculate_hash(True), received_hash)

    if not valid:
        raise HTTPException(status_code=401, detail="Подпись Telegram недействительна")

    try:
        user = json.loads(pairs["user"])
    except (KeyError, json.JSONDecodeError):
        raise HTTPException(status_code=401, detail="Данные пользователя Telegram отсутствуют")

    if not isinstance(user.get("id"), int):
        raise HTTPException(status_code=401, detail="Некорректный Telegram ID")

    return user


def apply_telegram_profile(user: User, tg_user: dict, timestamp: datetime) -> None:
    user.username = tg_user.get("username")
    user.first_name = tg_user.get("first_name") or "Пользователь"
    user.last_name = tg_user.get("last_name")
    user.last_seen_at = timestamp


def get_or_create_user(tg_user: dict) -> dict:
    telegram_id = tg_user["id"]
    timestamp = now_utc()

    with SessionLocal() as session:
        user = session.get(User, telegram_id)

        if user is None:
            user = User(
                telegram_id=telegram_id,
                username=tg_user.get("username"),
                first_name=tg_user.get("first_name") or "Пользователь",
                last_name=tg_user.get("last_name"),
                balance=0,
                created_at=timestamp,
                last_seen_at=timestamp,
            )
            session.add(user)
        else:
            apply_telegram_profile(user, tg_user, timestamp)

        session.commit()
        session.refresh(user)

        transactions = session.scalars(
            select(Transaction)
            .where(Transaction.telegram_id == telegram_id)
            .order_by(Transaction.id.desc())
            .limit(20)
        ).all()

        return {
            "user": serialize_user(user),
            "transactions": [serialize_transaction(tx) for tx in transactions],
        }


def redeem_promo(tg_user: dict, raw_code: str) -> dict:
    code = normalize_promo_code(raw_code)
    if not PROMO_PATTERN.fullmatch(code):
        raise HTTPException(status_code=400, detail="Некорректный формат промокода")

    telegram_id = tg_user["id"]
    timestamp = now_utc()

    try:
        with SessionLocal() as session:
            with session.begin():
                user = session.scalar(
                    select(User)
                    .where(User.telegram_id == telegram_id)
                    .with_for_update()
                )

                if user is None:
                    user = User(
                        telegram_id=telegram_id,
                        username=tg_user.get("username"),
                        first_name=tg_user.get("first_name") or "Пользователь",
                        last_name=tg_user.get("last_name"),
                        balance=0,
                        created_at=timestamp,
                        last_seen_at=timestamp,
                    )
                    session.add(user)
                    session.flush()
                else:
                    apply_telegram_profile(user, tg_user, timestamp)

                promo = session.scalar(
                    select(PromoCode)
                    .where(PromoCode.code == code)
                    .with_for_update()
                )

                if promo is None or not promo.is_active:
                    raise HTTPException(status_code=404, detail="Промокод не найден")

                expires_at = normalize_datetime(promo.expires_at)
                if expires_at is not None and expires_at <= timestamp:
                    raise HTTPException(status_code=410, detail="Срок действия промокода истёк")

                already_used = session.scalar(
                    select(PromoRedemption.id).where(
                        PromoRedemption.promo_id == promo.id,
                        PromoRedemption.telegram_id == telegram_id,
                    )
                )
                if already_used is not None:
                    raise HTTPException(status_code=409, detail="Вы уже активировали этот промокод")

                if promo.max_uses is not None and promo.uses_count >= promo.max_uses:
                    raise HTTPException(status_code=410, detail="Лимит активаций промокода исчерпан")

                if promo.reward_amount <= 0:
                    raise HTTPException(status_code=500, detail="Промокод настроен некорректно")

                reward = promo.reward_amount
                user.balance += reward
                promo.uses_count += 1

                transaction = Transaction(
                    telegram_id=telegram_id,
                    amount=reward,
                    operation_type="promo",
                    description=f"Промокод {promo.code}",
                    created_at=timestamp,
                )
                session.add(transaction)
                session.flush()

                session.add(
                    PromoRedemption(
                        promo_id=promo.id,
                        telegram_id=telegram_id,
                        reward_amount=reward,
                        created_at=timestamp,
                    )
                )

                new_balance = user.balance
                transaction_id = transaction.id

            return {
                "reward": reward,
                "balance": new_balance,
                "transaction": {
                    "id": transaction_id,
                    "amount": reward,
                    "operation_type": "promo",
                    "description": f"Промокод {code}",
                    "created_at": timestamp.isoformat(),
                },
            }
    except IntegrityError as exc:
        raise HTTPException(status_code=409, detail="Вы уже активировали этот промокод") from exc


def find_target_user(session, raw_target: str, lock: bool = False) -> User | None:
    target = raw_target.strip()
    if not target:
        return None

    if target.startswith("@"):
        target = target[1:]

    query = select(User)

    if target.isdigit():
        query = query.where(User.telegram_id == int(target))
    else:
        query = query.where(func.lower(User.username) == target.lower())

    if lock:
        query = query.with_for_update()

    return session.scalar(query)


def grant_lapcoins(tg_user: dict, payload: OwnerGrantRequest) -> dict:
    require_owner(tg_user)
    timestamp = now_utc()
    reason = (payload.reason or "").strip()

    with SessionLocal() as session:
        with session.begin():
            target_user = find_target_user(session, payload.target, lock=True)
            if target_user is None:
                raise HTTPException(
                    status_code=404,
                    detail="Пользователь не найден. Он должен хотя бы один раз открыть Nyan Wallet.",
                )

            target_user.balance += payload.amount
            description = reason or "Начисление владельцем"

            transaction = Transaction(
                telegram_id=target_user.telegram_id,
                amount=payload.amount,
                operation_type="owner_grant",
                description=description,
                created_at=timestamp,
            )
            session.add(transaction)
            session.flush()

            result = {
                "telegram_id": target_user.telegram_id,
                "username": target_user.username,
                "first_name": target_user.first_name,
                "amount": payload.amount,
                "balance": target_user.balance,
                "reason": reason or None,
                "transaction_id": transaction.id,
            }

    return result


def debit_lapcoins(tg_user: dict, payload: OwnerGrantRequest) -> dict:
    require_owner(tg_user)
    timestamp = now_utc()
    reason = (payload.reason or "").strip()

    with SessionLocal() as session:
        with session.begin():
            target_user = find_target_user(session, payload.target, lock=True)
            if target_user is None:
                raise HTTPException(status_code=404, detail="Пользователь не найден")

            if is_owner(target_user.telegram_id):
                raise HTTPException(status_code=400, detail="У владельца бесконечный баланс")

            if target_user.balance < payload.amount:
                raise HTTPException(
                    status_code=409,
                    detail=f"Недостаточно лапкоинов. Баланс пользователя: {target_user.balance} 🐾",
                )

            target_user.balance -= payload.amount
            description = reason or "Списание владельцем"

            transaction = Transaction(
                telegram_id=target_user.telegram_id,
                amount=-payload.amount,
                operation_type="owner_debit",
                description=description,
                created_at=timestamp,
            )
            session.add(transaction)
            session.flush()

            result = {
                "telegram_id": target_user.telegram_id,
                "username": target_user.username,
                "first_name": target_user.first_name,
                "amount": payload.amount,
                "balance": target_user.balance,
                "reason": reason or None,
                "transaction_id": transaction.id,
            }

    return result


def list_owner_users(tg_user: dict, query_text: str) -> list[dict]:
    require_owner(tg_user)
    query_text = query_text.strip().lstrip("@")

    with SessionLocal() as session:
        query = select(User)

        if query_text:
            if query_text.isdigit():
                query = query.where(User.telegram_id == int(query_text))
            else:
                pattern = f"%{query_text}%"
                query = query.where(
                    or_(
                        User.username.ilike(pattern),
                        User.first_name.ilike(pattern),
                        User.last_name.ilike(pattern),
                    )
                )

        users = session.scalars(
            query.order_by(User.last_seen_at.desc()).limit(50)
        ).all()
        return [serialize_user(user) for user in users]


def get_owner_user_detail(tg_user: dict, telegram_id: int) -> dict:
    require_owner(tg_user)

    with SessionLocal() as session:
        user = session.get(User, telegram_id)
        if user is None:
            raise HTTPException(status_code=404, detail="Пользователь не найден")

        transactions = session.scalars(
            select(Transaction)
            .where(Transaction.telegram_id == telegram_id)
            .order_by(Transaction.id.desc())
            .limit(50)
        ).all()

        return {
            "user": serialize_user(user),
            "transactions": [serialize_transaction(tx) for tx in transactions],
        }


def create_owner_promo(tg_user: dict, payload: OwnerPromoCreateRequest) -> dict:
    require_owner(tg_user)
    timestamp = now_utc()
    code = normalize_promo_code(payload.code)

    if not PROMO_PATTERN.fullmatch(code):
        raise HTTPException(
            status_code=400,
            detail="Код должен содержать 2–32 символа: латиница, цифры, _ или -",
        )

    expires_at = normalize_datetime(payload.expires_at)
    if expires_at is not None and expires_at <= timestamp:
        raise HTTPException(status_code=400, detail="Дата окончания должна быть в будущем")

    description = (payload.description or "").strip() or None

    try:
        with SessionLocal() as session:
            promo = PromoCode(
                code=code,
                reward_amount=payload.reward_amount,
                max_uses=payload.max_uses,
                uses_count=0,
                is_active=True,
                description=description,
                created_at=timestamp,
                expires_at=expires_at,
            )
            session.add(promo)
            session.commit()
            session.refresh(promo)
            return serialize_promo(promo)
    except IntegrityError as exc:
        raise HTTPException(status_code=409, detail="Такой промокод уже существует") from exc


def list_owner_promos(tg_user: dict) -> list[dict]:
    require_owner(tg_user)

    with SessionLocal() as session:
        promos = session.scalars(
            select(PromoCode).order_by(PromoCode.id.desc()).limit(50)
        ).all()
        return [serialize_promo(promo) for promo in promos]


@app.get("/api/health")
async def health():
    return {
        "ok": True,
        "service": "Nyan Wallet API",
        "database": "postgresql" if DATABASE_URL.startswith("postgresql") else "sqlite",
    }


@app.get("/api/me")
async def me(
    x_telegram_init_data: str | None = Header(
        default=None,
        alias="X-Telegram-Init-Data",
    )
):
    tg_user = verify_init_data(x_telegram_init_data or "")
    return {"ok": True, **get_or_create_user(tg_user)}


@app.post("/api/promo/redeem")
async def promo_redeem(
    payload: PromoRedeemRequest,
    x_telegram_init_data: str | None = Header(
        default=None,
        alias="X-Telegram-Init-Data",
    ),
):
    tg_user = verify_init_data(x_telegram_init_data or "")
    return {"ok": True, **redeem_promo(tg_user, payload.code)}


@app.get("/api/owner/users")
async def owner_users(
    q: str = "",
    x_telegram_init_data: str | None = Header(
        default=None,
        alias="X-Telegram-Init-Data",
    ),
):
    tg_user = verify_init_data(x_telegram_init_data or "")
    return {"ok": True, "users": list_owner_users(tg_user, q)}


@app.get("/api/owner/users/{telegram_id}")
async def owner_user_detail(
    telegram_id: int,
    x_telegram_init_data: str | None = Header(
        default=None,
        alias="X-Telegram-Init-Data",
    ),
):
    tg_user = verify_init_data(x_telegram_init_data or "")
    return {"ok": True, **get_owner_user_detail(tg_user, telegram_id)}


@app.post("/api/owner/grant")
async def owner_grant(
    payload: OwnerGrantRequest,
    x_telegram_init_data: str | None = Header(
        default=None,
        alias="X-Telegram-Init-Data",
    ),
):
    tg_user = verify_init_data(x_telegram_init_data or "")
    return {"ok": True, "grant": grant_lapcoins(tg_user, payload)}


@app.post("/api/owner/debit")
async def owner_debit(
    payload: OwnerGrantRequest,
    x_telegram_init_data: str | None = Header(
        default=None,
        alias="X-Telegram-Init-Data",
    ),
):
    tg_user = verify_init_data(x_telegram_init_data or "")
    return {"ok": True, "debit": debit_lapcoins(tg_user, payload)}


@app.get("/api/owner/promos")
async def owner_promos(
    x_telegram_init_data: str | None = Header(
        default=None,
        alias="X-Telegram-Init-Data",
    ),
):
    tg_user = verify_init_data(x_telegram_init_data or "")
    return {"ok": True, "promos": list_owner_promos(tg_user)}


@app.post("/api/owner/promos")
async def owner_promo_create(
    payload: OwnerPromoCreateRequest,
    x_telegram_init_data: str | None = Header(
        default=None,
        alias="X-Telegram-Init-Data",
    ),
):
    tg_user = verify_init_data(x_telegram_init_data or "")
    return {"ok": True, "promo": create_owner_promo(tg_user, payload)}
