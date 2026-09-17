import hashlib
import hmac
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qsl

from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, Text, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

BOT_TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL") or f"sqlite:///{ROOT / 'wallet.db'}"

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN отсутствует")

# Render may provide postgres://; SQLAlchemy/psycopg expects postgresql+psycopg://
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


Base.metadata.create_all(engine)

app = FastAPI(title="Nyan Wallet API", version="1.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://qwertsyik0.github.io"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "X-Telegram-Init-Data"],
)


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


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
            user.username = tg_user.get("username")
            user.first_name = tg_user.get("first_name") or "Пользователь"
            user.last_name = tg_user.get("last_name")
            user.last_seen_at = timestamp

        session.commit()
        session.refresh(user)

        transactions = session.scalars(
            select(Transaction)
            .where(Transaction.telegram_id == telegram_id)
            .order_by(Transaction.id.desc())
            .limit(20)
        ).all()

        return {
            "user": {
                "telegram_id": user.telegram_id,
                "username": user.username,
                "first_name": user.first_name,
                "last_name": user.last_name,
                "balance": user.balance,
                "created_at": user.created_at.isoformat(),
            },
            "transactions": [
                {
                    "id": tx.id,
                    "amount": tx.amount,
                    "operation_type": tx.operation_type,
                    "description": tx.description,
                    "created_at": tx.created_at.isoformat(),
                }
                for tx in transactions
            ],
        }


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
