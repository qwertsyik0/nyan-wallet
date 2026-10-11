from __future__ import annotations

import json
from datetime import datetime

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, Text, UniqueConstraint, select
from sqlalchemy.orm import Mapped, mapped_column

from . import backend_app as core

router = APIRouter()
_REGISTERED = False

SURVEY_KEY = "wallet_feedback_20261011"
REWARD_AMOUNT = 100


class WalletSurveyResponse(core.Base):
    __tablename__ = "wallet_survey_responses"
    __table_args__ = (
        UniqueConstraint("survey_key", "telegram_id", name="uq_wallet_survey_user"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    survey_key: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    telegram_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.telegram_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    answers_json: Mapped[str] = mapped_column(Text, nullable=False)
    reward_amount: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class SurveySubmit(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    useful: str = Field(min_length=1, max_length=32)
    most_used: str = Field(min_length=1, max_length=64)
    missing: str = Field(min_length=1, max_length=64)
    separate_channel: str = Field(min_length=1, max_length=16)
    updates: str = Field(min_length=1, max_length=64)
    comment: str = Field(default="", max_length=700)


ALLOWED = {
    "useful": {"very", "mostly", "sometimes", "rarely"},
    "most_used": {"balance", "rewards", "giveaways", "transfers", "promos", "other"},
    "missing": {"more_rewards", "more_events", "more_customization", "more_wallet_tools", "nothing", "other"},
    "separate_channel": {"yes", "no", "maybe"},
    "updates": {"new_features", "promos", "events", "catalog", "all"},
}


def _validate(payload: SurveySubmit) -> None:
    values = payload.model_dump()
    for field, allowed in ALLOWED.items():
        if values[field] not in allowed:
            raise HTTPException(status_code=400, detail=f"Некорректный ответ: {field}")


@router.get("/api/wallet-survey/status")
async def wallet_survey_status(
    x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data"),
):
    tg = core.verify_init_data(x_telegram_init_data or "")
    core.get_or_create_user(tg)
    telegram_id = int(tg["id"])

    with core.SessionLocal() as session:
        row = session.scalar(
            select(WalletSurveyResponse).where(
                WalletSurveyResponse.survey_key == SURVEY_KEY,
                WalletSurveyResponse.telegram_id == telegram_id,
            )
        )
        return {
            "ok": True,
            "survey_key": SURVEY_KEY,
            "reward_amount": REWARD_AMOUNT,
            "completed": row is not None,
            "completed_at": row.created_at.isoformat() if row else None,
        }


@router.post("/api/wallet-survey/submit")
async def wallet_survey_submit(
    payload: SurveySubmit,
    x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data"),
):
    tg = core.verify_init_data(x_telegram_init_data or "")
    telegram_id = int(tg["id"])
    timestamp = core.now_utc()
    _validate(payload)

    core.get_or_create_user(tg)

    with core.SessionLocal() as session:
        with session.begin():
            existing = session.scalar(
                select(WalletSurveyResponse)
                .where(
                    WalletSurveyResponse.survey_key == SURVEY_KEY,
                    WalletSurveyResponse.telegram_id == telegram_id,
                )
                .with_for_update()
            )
            if existing is not None:
                raise HTTPException(status_code=409, detail="Вы уже прошли этот опрос")

            user = session.scalar(
                select(core.User)
                .where(core.User.telegram_id == telegram_id)
                .with_for_update()
            )
            if user is None:
                raise HTTPException(status_code=404, detail="Пользователь Nyan Wallet не найден")

            answers = payload.model_dump()
            user.balance += REWARD_AMOUNT

            session.add(
                WalletSurveyResponse(
                    survey_key=SURVEY_KEY,
                    telegram_id=telegram_id,
                    answers_json=json.dumps(answers, ensure_ascii=False, separators=(",", ":")),
                    reward_amount=REWARD_AMOUNT,
                    created_at=timestamp,
                )
            )
            session.add(
                core.Transaction(
                    telegram_id=telegram_id,
                    amount=REWARD_AMOUNT,
                    operation_type="wallet_survey_reward",
                    description="Опрос Nyan Wallet",
                    created_at=timestamp,
                )
            )

            balance = int(user.balance)

    return {
        "ok": True,
        "reward_amount": REWARD_AMOUNT,
        "balance": balance,
    }


def register_wallet_survey(app) -> None:
    global _REGISTERED
    if _REGISTERED:
        return
    core.Base.metadata.create_all(core.engine)
    app.include_router(router)
    _REGISTERED = True
