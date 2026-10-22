from __future__ import annotations

"""One-time, signed Telegram quote reflection with a fixed 200 paw reward."""
from datetime import datetime

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Mapped, mapped_column

from . import backend_app as core
from .user_bans import BlockedUser

router = APIRouter()
_REGISTERED = False
QUOTE_KEY = "bridge_of_effort_20261021"
REWARD_AMOUNT = 200
ANSWERS = frozenset({"unseen_effort", "other_opinion", "hidden_loneliness", "one_mistake"})
REWARD_REASON = "участие в интерактиве «Как вы поняли цитату?»"


class QuoteReflectionAnswer(core.Base):
    __tablename__ = "quote_reflection_answers"

    quote_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    telegram_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.telegram_id", ondelete="CASCADE"), primary_key=True
    )
    answer: Mapped[str] = mapped_column(String(32), nullable=False)
    reward_amount: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class QuoteAnswerPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    answer: str


def _identity(init_data: str | None) -> int:
    user = core.verify_init_data(init_data or "")
    return int(user["id"])


@router.get("/api/quote-reflection/status")
async def quote_reflection_status(
    x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data"),
):
    telegram_id = _identity(x_telegram_init_data)
    with core.SessionLocal() as session:
        row = session.get(QuoteReflectionAnswer, (QUOTE_KEY, telegram_id))
    return {
        "ok": True,
        "completed": row is not None,
        "answer": row.answer if row else None,
        "reward_amount": REWARD_AMOUNT,
    }


@router.post("/api/quote-reflection/submit")
async def quote_reflection_submit(
    payload: QuoteAnswerPayload,
    x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data"),
):
    tg_user = core.verify_init_data(x_telegram_init_data or "")
    telegram_id = int(tg_user["id"])
    if payload.answer not in ANSWERS:
        raise HTTPException(status_code=400, detail="Выбери один из четырёх ответов")

    timestamp = core.now_utc()
    with core.SessionLocal() as session:
        with session.begin():
            # Ensure the wallet row exists even when two first-launch requests
            # arrive simultaneously. ON CONFLICT waits for concurrent inserts.
            profile = dict(
                telegram_id=telegram_id,
                username=tg_user.get("username"),
                first_name=tg_user.get("first_name") or "Пользователь",
                last_name=tg_user.get("last_name"),
                balance=0,
                created_at=timestamp,
                last_seen_at=timestamp,
            )
            dialect = session.bind.dialect.name
            if dialect == "postgresql":
                statement = pg_insert(core.User).values(**profile)
            elif dialect == "sqlite":  # Local isolated test support.
                statement = sqlite_insert(core.User).values(**profile)
            else:
                raise RuntimeError("Для начислений Nyan Wallet необходим PostgreSQL")
            session.execute(statement.on_conflict_do_nothing(index_elements=["telegram_id"]))

            # The wallet-row lock serializes all claims, and the composite
            # primary key enforces one reward per quote and Telegram account.
            user = session.scalar(
                select(core.User).where(core.User.telegram_id == telegram_id).with_for_update()
            )
            if session.get(BlockedUser, telegram_id) is not None:
                raise HTTPException(status_code=403, detail="Начисление недоступно для заблокированного аккаунта")

            existing = session.get(QuoteReflectionAnswer, (QUOTE_KEY, telegram_id))
            if existing is not None:
                return {"ok": True, "completed": True, "already_completed": True,
                        "reward_amount": REWARD_AMOUNT, "balance": int(user.balance)}

            user.balance += REWARD_AMOUNT
            session.add(QuoteReflectionAnswer(
                quote_key=QUOTE_KEY,
                telegram_id=telegram_id,
                answer=payload.answer,
                reward_amount=REWARD_AMOUNT,
                created_at=timestamp,
            ))
            session.add(core.Transaction(
                telegram_id=telegram_id,
                amount=REWARD_AMOUNT,
                operation_type="quote_reflection_reward",
                description=REWARD_REASON,
                created_at=timestamp,
            ))
            # The mini-app inbox provides a record even if Telegram Bot API is unreachable.
            from .advanced_features import WalletNotification
            session.add(WalletNotification(
                telegram_id=telegram_id,
                kind="quote_reflection_reward",
                title="Награда за размышление",
                body="+200 🐾 за ответ на вопрос о цитате",
                is_read=False,
                created_at=timestamp,
            ))
            balance = int(user.balance)

    return {"ok": True, "completed": True, "already_completed": False,
            "reward_amount": REWARD_AMOUNT, "balance": balance}


def register_quote_reflection(app) -> None:
    global _REGISTERED
    if _REGISTERED:
        return
    core.Base.metadata.create_all(core.engine)
    app.include_router(router)
    _REGISTERED = True
