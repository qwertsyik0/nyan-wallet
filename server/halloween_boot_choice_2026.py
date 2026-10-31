"""One-time Halloween boot-screen choice, recorded atomically with the wallet transaction.

Each verified Telegram account may choose once. A repeat request returns the
original result without ever applying a second credit or debit.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, select
from sqlalchemy.orm import Mapped, mapped_column

from . import backend_app as core
from .user_bans import BlockedUser


router = APIRouter()
_REGISTERED = False
AWARDS = {"sweet": 300, "trick": -400}
RETIRED = True  # Ended event: keep saved choices and transactions, forbid new grants.


class HalloweenBootChoice(core.Base):
    __tablename__ = "halloween_2026_boot_choices"

    telegram_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.telegram_id", ondelete="CASCADE"), primary_key=True
    )
    choice: Mapped[str] = mapped_column(String(12), nullable=False)
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    transaction_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("transactions.id"), nullable=False, unique=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ChoicePayload(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    choice: Literal["sweet", "trick"]


@router.get("/api/halloween-boot-2026/status")
def status(x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data")):
    telegram = core.verify_init_data(x_telegram_init_data or "")
    telegram_id = int(telegram["id"])
    with core.SessionLocal() as session:
        existing = session.get(HalloweenBootChoice, telegram_id)
        user = session.get(core.User, telegram_id)
        blocked = session.get(BlockedUser, telegram_id) is not None
        return {
            "ok": True,
            "eligible": not RETIRED and user is not None and existing is None and not blocked,
            "completed": existing is not None,
            "choice": existing.choice if existing else None,
            "amount": existing.amount if existing else None,
        }


@router.post("/api/halloween-boot-2026/choose")
def choose(payload: ChoicePayload, x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data")):
    telegram = core.verify_init_data(x_telegram_init_data or "")
    telegram_id = int(telegram["id"])
    with core.SessionLocal.begin() as session:
        # Lock the user, not only the choice: the row doesn't exist on first entry.
        # This serializes concurrent choices and protects wallet balance updates.
        user = session.scalar(
            select(core.User).where(core.User.telegram_id == telegram_id).with_for_update()
        )
        if user is None:
            raise HTTPException(status_code=404, detail="Сначала откройте Nyan Wallet")
        existing = session.get(HalloweenBootChoice, telegram_id)
        if existing:
            return {
                "ok": True, "repeated": True, "choice": existing.choice,
                "amount": existing.amount, "balance": int(user.balance),
            }
        if RETIRED:
            raise HTTPException(status_code=410, detail="Хеллоуинский ивент завершён")
        if session.get(BlockedUser, telegram_id) is not None:
            raise HTTPException(status_code=403, detail="Операции для аккаунта ограничены")

        amount = AWARDS[payload.choice]
        now = datetime.now(timezone.utc)
        user.balance = int(user.balance) + amount
        core.apply_telegram_profile(user, telegram, now)
        transaction = core.Transaction(
            telegram_id=telegram_id,
            amount=amount,
            operation_type="halloween_boot_choice_2026",
            description="Сладость или гадость · Сладость" if amount > 0 else "Сладость или гадость · Гадость",
            created_at=now,
        )
        session.add(transaction)
        session.flush()
        session.add(HalloweenBootChoice(
            telegram_id=telegram_id, choice=payload.choice,
            amount=amount, transaction_id=transaction.id, created_at=now,
        ))
        balance = int(user.balance)
    return {"ok": True, "repeated": False, "choice": payload.choice, "amount": amount, "balance": balance}


def register_halloween_boot_choice_2026(app) -> None:
    global _REGISTERED
    if _REGISTERED:
        return
    core.Base.metadata.create_all(core.engine, tables=[HalloweenBootChoice.__table__], checkfirst=True)
    app.include_router(router)
    _REGISTERED = True
