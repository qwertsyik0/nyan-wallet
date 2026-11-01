"""One-person-one-vote poll for the next Nyan Wallet update.

Votes are tied to verified Telegram Mini App initData. A 100-LK reward is
issued in the very same database transaction as the unique vote row.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, func, select
from sqlalchemy.orm import Mapped, mapped_column

from . import backend_app as core


router = APIRouter()
_REGISTERED = False
REWARD_AMOUNT = 100
CHOICES = {
    "market": "NYAN MARKET 2.0",
    "arcade": "NYAN ARCADE",
    "contracts": "NYAN CONTRACTS",
    "social": "NYAN SOCIAL",
    "studio": "NYAN STUDIO 2.0",
}


class NyanFutureVote(core.Base):
    __tablename__ = "nyan_future_votes_2026"

    telegram_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.telegram_id", ondelete="CASCADE"),
        primary_key=True,
    )
    choice: Mapped[str] = mapped_column(String(24), nullable=False)
    reward_amount: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class VoteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    choice: Literal["market", "arcade", "contracts", "social", "studio"]
    pledged: Literal[True]


def _telegram_user(init_data: str | None) -> dict:
    return core.verify_init_data(init_data or "")


@router.get("/api/nyan-future-vote/status")
def vote_status(
    x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data"),
):
    tg = _telegram_user(x_telegram_init_data)
    core.get_or_create_user(tg)
    with core.SessionLocal() as session:
        vote = session.get(NyanFutureVote, int(tg["id"]))
        return {
            "ok": True,
            "completed": vote is not None,
            "reward_amount": REWARD_AMOUNT,
        }


@router.post("/api/nyan-future-vote/submit")
def vote_submit(
    payload: VoteRequest,
    x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data"),
):
    tg = _telegram_user(x_telegram_init_data)
    telegram_id = int(tg["id"])
    core.get_or_create_user(tg)

    with core.SessionLocal() as session:
        with session.begin():
            # Always lock the user's balance row first. Concurrent requests
            # for the same Telegram account therefore cannot double-credit.
            user = session.scalar(
                select(core.User)
                .where(core.User.telegram_id == telegram_id)
                .with_for_update()
            )
            if user is None:
                raise HTTPException(status_code=404, detail="Пользователь не найден")

            if session.get(NyanFutureVote, telegram_id) is not None:
                raise HTTPException(status_code=409, detail="Ваш голос уже учтён")

            timestamp = core.now_utc()
            user.balance += REWARD_AMOUNT
            session.add(
                NyanFutureVote(
                    telegram_id=telegram_id,
                    choice=payload.choice,
                    reward_amount=REWARD_AMOUNT,
                    created_at=timestamp,
                )
            )
            session.add(
                core.Transaction(
                    telegram_id=telegram_id,
                    amount=REWARD_AMOUNT,
                    operation_type="nyan_future_vote_reward",
                    description="Голосование за следующее обновление Nyan Wallet",
                    created_at=timestamp,
                )
            )
            balance = int(user.balance)

    return {"ok": True, "reward_amount": REWARD_AMOUNT, "balance": balance}


@router.get("/api/owner/nyan-future-vote/results")
def owner_vote_results(
    x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data"),
):
    tg = _telegram_user(x_telegram_init_data)
    core.require_owner(tg)
    with core.SessionLocal() as session:
        counts = dict(
            session.execute(
                select(NyanFutureVote.choice, func.count(NyanFutureVote.telegram_id))
                .group_by(NyanFutureVote.choice)
            ).all()
        )
    results = [
        {"choice": key, "title": title, "votes": int(counts.get(key, 0))}
        for key, title in CHOICES.items()
    ]
    return {"ok": True, "total": sum(row["votes"] for row in results), "results": results}


def register_nyan_future_vote(app) -> None:
    global _REGISTERED
    if _REGISTERED:
        return
    NyanFutureVote.__table__.create(bind=core.engine, checkfirst=True)
    app.include_router(router)
    _REGISTERED = True
