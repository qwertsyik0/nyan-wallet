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



@router.get("/api/owner/wallet-survey/results")
async def owner_wallet_survey_results(
    x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data"),
):
    tg = core.verify_init_data(x_telegram_init_data or "")
    core.require_owner(tg)

    labels = {
        "useful": {
            "very": "очень полезен",
            "mostly": "скорее полезен",
            "sometimes": "пользуюсь иногда",
            "rarely": "почти не пользуюсь",
        },
        "most_used": {
            "balance": "баланс и история",
            "rewards": "каталог наград",
            "giveaways": "розыгрыши",
            "transfers": "переводы",
            "promos": "промокоды",
            "other": "другое",
        },
        "missing": {
            "more_rewards": "больше наград",
            "more_events": "больше ивентов и активностей",
            "more_customization": "больше кастомизации",
            "more_wallet_tools": "больше функций кошелька",
            "nothing": "сейчас всего хватает",
            "other": "другое",
        },
        "separate_channel": {
            "yes": "да, отдельный канал нужен",
            "no": "нет, достаточно Нян Шопа",
            "maybe": "не уверен(а)",
        },
        "updates": {
            "new_features": "новые функции",
            "promos": "промокоды и бонусы",
            "events": "ивенты и активности",
            "catalog": "новые награды и каталог",
            "all": "всё сразу",
        },
    }

    with core.SessionLocal() as session:
        rows = session.execute(
            select(WalletSurveyResponse, core.User)
            .join(core.User, core.User.telegram_id == WalletSurveyResponse.telegram_id)
            .where(WalletSurveyResponse.survey_key == SURVEY_KEY)
            .order_by(WalletSurveyResponse.created_at.desc())
        ).all()

    totals = {field: {} for field in ALLOWED}
    participants = []
    comments = []

    for response, user in rows:
        try:
            answers = json.loads(response.answers_json or "{}")
        except json.JSONDecodeError:
            answers = {}

        for field in ALLOWED:
            value = answers.get(field)
            if value:
                totals[field][value] = totals[field].get(value, 0) + 1

        name = f"@{user.username}" if user.username else (
            " ".join(part for part in [user.first_name, user.last_name] if part).strip()
            or f"ID {user.telegram_id}"
        )

        participant = {
            "telegram_id": int(user.telegram_id),
            "name": name,
            "username": user.username,
            "reward_amount": int(response.reward_amount),
            "created_at": response.created_at.isoformat(),
            "answers": answers,
        }
        participants.append(participant)

        comment = str(answers.get("comment") or "").strip()
        if comment:
            comments.append({
                "telegram_id": int(user.telegram_id),
                "name": name,
                "comment": comment,
                "created_at": response.created_at.isoformat(),
            })

    total = len(participants)
    questions = {}
    for field, field_labels in labels.items():
        options = []
        for key, label in field_labels.items():
            count = int(totals[field].get(key, 0))
            options.append({
                "key": key,
                "label": label,
                "count": count,
                "percent": round((count / total) * 100, 1) if total else 0.0,
            })
        questions[field] = options

    return {
        "ok": True,
        "survey_key": SURVEY_KEY,
        "total": total,
        "reward_amount": REWARD_AMOUNT,
        "total_rewards": total * REWARD_AMOUNT,
        "questions": questions,
        "comments": comments,
        "participants": participants,
    }

def register_wallet_survey(app) -> None:
    global _REGISTERED
    if _REGISTERED:
        return
    core.Base.metadata.create_all(core.engine)
    app.include_router(router)
    _REGISTERED = True
