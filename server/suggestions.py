import html
import json
import logging
import urllib.parse
import urllib.request
from datetime import datetime

from fastapi import Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, Text, select
from sqlalchemy.orm import Mapped, mapped_column

from . import backend_app as core

logger = logging.getLogger(__name__)

REWARD_AMOUNT = 300
MODERATION_URL = "https://qwertsyik0.github.io/nyan-wallet/suggestion-moderation.html"


class SuggestionSubmission(core.Base):
    __tablename__ = "suggestion_submissions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telegram_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.telegram_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    text: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending", index=True)
    reward_amount: Mapped[int] = mapped_column(Integer, nullable=False, default=REWARD_AMOUNT)
    moderator_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rewarded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SuggestionCreateRequest(BaseModel):
    text: str = Field(min_length=20, max_length=2500)


class SuggestionReviewRequest(BaseModel):
    decision: str = Field(min_length=6, max_length=7)
    note: str | None = Field(default=None, max_length=500)


SuggestionSubmission.__table__.create(bind=core.engine, checkfirst=True)


def _send_telegram_message(chat_id: int, text: str, *, moderation_button: bool = False) -> None:
    payload = {
        "chat_id": str(chat_id),
        "text": text,
        "disable_web_page_preview": "true",
    }
    if moderation_button:
        payload["reply_markup"] = json.dumps(
            {
                "inline_keyboard": [
                    [
                        {
                            "text": "Открыть модерацию",
                            "web_app": {"url": MODERATION_URL},
                        }
                    ]
                ]
            },
            ensure_ascii=False,
        )

    request = urllib.request.Request(
        f"https://api.telegram.org/bot{core.BOT_TOKEN}/sendMessage",
        data=urllib.parse.urlencode(payload).encode("utf-8"),
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=6) as response:
            response.read()
    except Exception as exc:
        logger.warning("suggestion notification failed chat_id=%s error=%s", chat_id, type(exc).__name__)


def _serialize(item: SuggestionSubmission, user: core.User | None = None) -> dict:
    result = {
        "id": item.id,
        "telegram_id": item.telegram_id,
        "text": item.text,
        "status": item.status,
        "reward_amount": item.reward_amount,
        "moderator_note": item.moderator_note,
        "created_at": item.created_at.isoformat(),
        "reviewed_at": item.reviewed_at.isoformat() if item.reviewed_at else None,
        "rewarded_at": item.rewarded_at.isoformat() if item.rewarded_at else None,
    }
    if user is not None:
        result["username"] = user.username
        result["first_name"] = user.first_name
        result["last_name"] = user.last_name
    return result


def _ensure_user(session, tg_user: dict, timestamp: datetime) -> core.User:
    user = session.scalar(
        select(core.User)
        .where(core.User.telegram_id == tg_user["id"])
        .with_for_update()
    )
    if user is None:
        user = core.User(
            telegram_id=tg_user["id"],
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
        core.apply_telegram_profile(user, tg_user, timestamp)
    return user


def submit_suggestion(tg_user: dict, text: str) -> dict:
    clean = " ".join((text or "").strip().split())
    if len(clean) < 20:
        raise HTTPException(status_code=400, detail="Опишите предложение подробнее — минимум 20 символов.")
    if len(clean) > 2500:
        raise HTTPException(status_code=400, detail="Предложение слишком длинное.")

    timestamp = core.now_utc()
    with core.SessionLocal() as session:
        with session.begin():
            user = _ensure_user(session, tg_user, timestamp)

            approved = session.scalar(
                select(SuggestionSubmission.id).where(
                    SuggestionSubmission.telegram_id == user.telegram_id,
                    SuggestionSubmission.status == "approved",
                )
            )
            if approved is not None:
                raise HTTPException(
                    status_code=409,
                    detail="Ваше предложение уже было одобрено и награда 300 🐾 получена.",
                )

            pending = session.scalar(
                select(SuggestionSubmission.id).where(
                    SuggestionSubmission.telegram_id == user.telegram_id,
                    SuggestionSubmission.status == "pending",
                )
            )
            if pending is not None:
                raise HTTPException(
                    status_code=409,
                    detail="У вас уже есть предложение на модерации.",
                )

            item = SuggestionSubmission(
                telegram_id=user.telegram_id,
                text=clean,
                status="pending",
                reward_amount=REWARD_AMOUNT,
                moderator_note=None,
                created_at=timestamp,
                reviewed_at=None,
                rewarded_at=None,
            )
            session.add(item)
            session.flush()
            result = _serialize(item, user)

    if core.OWNER_TELEGRAM_ID:
        username = f"@{tg_user.get('username')}" if tg_user.get("username") else (tg_user.get("first_name") or "Пользователь")
        preview = clean if len(clean) <= 900 else clean[:897] + "..."
        _send_telegram_message(
            core.OWNER_TELEGRAM_ID,
            f"💡 Новое предложение Nyan Wallet\n\n"
            f"Заявка #{result['id']}\n"
            f"Пользователь: {username}\n"
            f"ID: {tg_user['id']}\n"
            f"Награда при одобрении: +{REWARD_AMOUNT} 🐾\n\n"
            f"{preview}",
            moderation_button=True,
        )
    return result


def my_suggestion(tg_user: dict) -> dict:
    with core.SessionLocal() as session:
        item = session.scalar(
            select(SuggestionSubmission)
            .where(SuggestionSubmission.telegram_id == tg_user["id"])
            .order_by(SuggestionSubmission.id.desc())
            .limit(1)
        )
        approved = session.scalar(
            select(SuggestionSubmission.id).where(
                SuggestionSubmission.telegram_id == tg_user["id"],
                SuggestionSubmission.status == "approved",
            )
        )
        pending = session.scalar(
            select(SuggestionSubmission.id).where(
                SuggestionSubmission.telegram_id == tg_user["id"],
                SuggestionSubmission.status == "pending",
            )
        )
        return {
            "latest": _serialize(item) if item else None,
            "can_submit": approved is None and pending is None,
            "reward_amount": REWARD_AMOUNT,
        }


def list_suggestions(tg_user: dict, status: str = "pending") -> list[dict]:
    core.require_owner(tg_user)
    status = (status or "pending").strip().lower()
    if status not in {"pending", "approved", "rejected", "all"}:
        raise HTTPException(status_code=400, detail="Некорректный статус")

    with core.SessionLocal() as session:
        query = (
            select(SuggestionSubmission, core.User)
            .join(core.User, core.User.telegram_id == SuggestionSubmission.telegram_id)
            .order_by(SuggestionSubmission.id.desc())
            .limit(100)
        )
        if status != "all":
            query = query.where(SuggestionSubmission.status == status)
        rows = session.execute(query).all()
        return [_serialize(item, user) for item, user in rows]


def review_suggestion(tg_user: dict, suggestion_id: int, payload: SuggestionReviewRequest) -> dict:
    core.require_owner(tg_user)
    decision = payload.decision.strip().lower()
    if decision not in {"approve", "reject"}:
        raise HTTPException(status_code=400, detail="decision должен быть approve или reject")

    timestamp = core.now_utc()
    notify_chat_id = None
    result = None

    with core.SessionLocal() as session:
        with session.begin():
            item = session.scalar(
                select(SuggestionSubmission)
                .where(SuggestionSubmission.id == suggestion_id)
                .with_for_update()
            )
            if item is None:
                raise HTTPException(status_code=404, detail="Предложение не найдено")
            if item.status != "pending":
                raise HTTPException(status_code=409, detail="Это предложение уже обработано")

            user = session.scalar(
                select(core.User)
                .where(core.User.telegram_id == item.telegram_id)
                .with_for_update()
            )
            if user is None:
                raise HTTPException(status_code=404, detail="Пользователь не найден")

            if decision == "approve":
                already_approved = session.scalar(
                    select(SuggestionSubmission.id).where(
                        SuggestionSubmission.telegram_id == item.telegram_id,
                        SuggestionSubmission.status == "approved",
                        SuggestionSubmission.id != item.id,
                    )
                )
                if already_approved is not None:
                    raise HTTPException(status_code=409, detail="Пользователь уже получал награду за предложение")

                user.balance += REWARD_AMOUNT
                session.add(
                    core.Transaction(
                        telegram_id=user.telegram_id,
                        amount=REWARD_AMOUNT,
                        operation_type="suggestion_reward",
                        description=f"Одобрено предложение #{item.id}",
                        created_at=timestamp,
                    )
                )
                item.status = "approved"
                item.rewarded_at = timestamp
            else:
                item.status = "rejected"
                item.rewarded_at = None

            item.moderator_note = (payload.note or "").strip() or None
            item.reviewed_at = timestamp
            session.flush()
            notify_chat_id = user.telegram_id
            result = _serialize(item, user)

    if notify_chat_id and result:
        if result["status"] == "approved":
            _send_telegram_message(
                notify_chat_id,
                f"✅ Ваше предложение по улучшению Nyan Wallet одобрено.\n\n+{REWARD_AMOUNT} 🐾 уже начислено на баланс.",
            )
        else:
            note = result.get("moderator_note")
            suffix = f"\n\nКомментарий: {note}" if note else ""
            _send_telegram_message(
                notify_chat_id,
                "❌ Предложение по улучшению Nyan Wallet отклонено." + suffix + "\n\nВы можете отправить новое предложение.",
            )
    return result


def register_suggestions(app) -> None:
    @app.post("/api/suggestions")
    async def create_suggestion(
        payload: SuggestionCreateRequest,
        x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data"),
    ):
        tg_user = core.verify_init_data(x_telegram_init_data or "")
        return {"ok": True, "suggestion": submit_suggestion(tg_user, payload.text)}

    @app.get("/api/suggestions/me")
    async def get_my_suggestion(
        x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data"),
    ):
        tg_user = core.verify_init_data(x_telegram_init_data or "")
        return {"ok": True, **my_suggestion(tg_user)}

    @app.get("/api/owner/suggestions")
    async def owner_suggestions(
        status: str = "pending",
        x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data"),
    ):
        tg_user = core.verify_init_data(x_telegram_init_data or "")
        return {"ok": True, "suggestions": list_suggestions(tg_user, status)}

    @app.post("/api/owner/suggestions/{suggestion_id}/review")
    async def owner_review_suggestion(
        suggestion_id: int,
        payload: SuggestionReviewRequest,
        x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data"),
    ):
        tg_user = core.verify_init_data(x_telegram_init_data or "")
        return {"ok": True, "suggestion": review_suggestion(tg_user, suggestion_id, payload)}
