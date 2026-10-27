"""Free Nyan Fortune wheel with durable, at-most-once wallet rewards.

Eight visual sectors have equal odds. The result is chosen with a secure server
RNG, never accepted from the browser. A user's wallet row serializes spins on
PostgreSQL, and every nonzero award shares a transaction with the spin record.
"""

from __future__ import annotations

import re
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, UniqueConstraint, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Mapped, mapped_column

from . import backend_app as core
from .user_bans import BlockedUser


router = APIRouter()
_REGISTERED = False
SECTORS = (10, 25, 50, 100, 0, 200, 25, 500)
COOLDOWN = timedelta(hours=24)
MAX_BALANCE = 2_147_483_647  # The existing users.balance column is INTEGER.
REQUEST_KEY_RE = re.compile(r"[A-Za-z0-9_-]{16,64}\Z")


class FortuneSpin(core.Base):
    __tablename__ = "fortune_spins"
    __table_args__ = (
        UniqueConstraint("telegram_id", "request_key", name="uq_fortune_user_request"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telegram_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.telegram_id", ondelete="CASCADE"), nullable=False, index=True,
    )
    request_key: Mapped[str] = mapped_column(String(64), nullable=False)
    sector_index: Mapped[int] = mapped_column(Integer, nullable=False)
    reward_amount: Mapped[int] = mapped_column(Integer, nullable=False)
    balance_after: Mapped[int] = mapped_column(Integer, nullable=False)
    transaction_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("transactions.id"), nullable=True, unique=True,
    )
    spun_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class SpinRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    request_key: str = Field(min_length=16, max_length=64)


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def _serialize(spin: FortuneSpin) -> dict:
    return {
        "id": spin.id,
        "sector_index": spin.sector_index,
        "reward": spin.reward_amount,
        "balance_after": spin.balance_after,
        "spun_at": _utc(spin.spun_at).isoformat(),
    }


def _latest(session, telegram_id: int) -> FortuneSpin | None:
    return session.scalar(
        select(FortuneSpin)
        .where(FortuneSpin.telegram_id == telegram_id)
        .order_by(FortuneSpin.spun_at.desc(), FortuneSpin.id.desc())
        .limit(1)
    )


def _eligible_user(session, tg_user: dict, timestamp: datetime) -> core.User:
    values = {
        "telegram_id": int(tg_user["id"]),
        "username": tg_user.get("username"),
        "first_name": tg_user.get("first_name") or "Пользователь",
        "last_name": tg_user.get("last_name"),
        "balance": 0,
        "created_at": timestamp,
        "last_seen_at": timestamp,
    }
    dialect = session.bind.dialect.name
    if dialect == "postgresql":
        statement = pg_insert(core.User).values(**values)
    elif dialect == "sqlite":
        statement = sqlite_insert(core.User).values(**values)
    else:
        raise RuntimeError("Unsupported database")
    session.execute(statement.on_conflict_do_nothing(index_elements=["telegram_id"]))

    user = session.scalar(
        select(core.User)
        .where(core.User.telegram_id == int(tg_user["id"]))
        .with_for_update()
    )
    if session.get(BlockedUser, user.telegram_id) is not None:
        raise HTTPException(status_code=403, detail="Аккаунт заблокирован для участия")
    core.apply_telegram_profile(user, tg_user, timestamp)
    return user


@router.get("/api/fortune")
def fortune_status(
    x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data"),
):
    tg_user = core.verify_init_data(x_telegram_init_data or "")
    now = core.now_utc()
    with core.SessionLocal() as session:
        blocked = session.get(BlockedUser, int(tg_user["id"])) is not None
        last = _latest(session, int(tg_user["id"]))
        next_at = _utc(last.spun_at) + COOLDOWN if last else None
        return {
            "ok": True,
            "sectors": SECTORS,
            "cooldown_seconds": int(COOLDOWN.total_seconds()),
            "available": not blocked and (next_at is None or next_at <= now),
            "blocked": blocked,
            "next_at": next_at.isoformat() if next_at else None,
            "last_spin": _serialize(last) if last else None,
        }


@router.post("/api/fortune/spin")
def fortune_spin(
    payload: SpinRequest,
    x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data"),
):
    tg_user = core.verify_init_data(x_telegram_init_data or "")
    if not REQUEST_KEY_RE.fullmatch(payload.request_key):
        raise HTTPException(status_code=422, detail="Некорректный ключ вращения")

    timestamp = core.now_utc()
    with core.SessionLocal.begin() as session:
        user = _eligible_user(session, tg_user, timestamp)

        # This check precedes cooldown for safe retries after a lost response.
        previous = session.scalar(
            select(FortuneSpin).where(
                FortuneSpin.telegram_id == user.telegram_id,
                FortuneSpin.request_key == payload.request_key,
            )
        )
        if previous is not None:
            result = {"ok": True, "duplicate": True, "spin": _serialize(previous),
                      "next_at": (_utc(previous.spun_at) + COOLDOWN).isoformat()}
        else:
            last = _latest(session, user.telegram_id)
            next_at = _utc(last.spun_at) + COOLDOWN if last else None
            if next_at is not None and next_at > timestamp:
                raise HTTPException(status_code=409, detail={
                    "message": "Следующее бесплатное вращение пока недоступно",
                    "next_at": next_at.isoformat(),
                })

            sector_index = secrets.randbelow(len(SECTORS))
            reward = SECTORS[sector_index]
            if user.balance + reward > MAX_BALANCE:
                raise HTTPException(status_code=409, detail="Достигнут предел баланса")

            spin = FortuneSpin(
                telegram_id=user.telegram_id, request_key=payload.request_key,
                sector_index=sector_index, reward_amount=reward,
                balance_after=user.balance + reward, spun_at=timestamp,
            )
            session.add(spin)
            session.flush()
            if reward:
                user.balance += reward
                tx = core.Transaction(
                    telegram_id=user.telegram_id, amount=reward,
                    operation_type="fortune_spin",
                    description=f"Колесо фортуны · вращение №{spin.id}",
                    created_at=timestamp,
                )
                session.add(tx)
                session.flush()
                spin.transaction_id = tx.id

            result = {"ok": True, "duplicate": False, "spin": _serialize(spin),
                      "next_at": (timestamp + COOLDOWN).isoformat()}
    return result


def register_fortune(app) -> None:
    global _REGISTERED
    if _REGISTERED:
        return
    core.Base.metadata.create_all(core.engine, tables=[FortuneSpin.__table__])
    app.include_router(router)
    _REGISTERED = True
