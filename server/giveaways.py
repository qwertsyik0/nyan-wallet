from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import re
import secrets
import urllib.parse
import urllib.request
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    select,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, mapped_column

from . import backend_app as core
from .achievements import ACHIEVEMENT_BY_KEY, AchievementUnlock
from .advanced_features import level_data, settings
from .extended_features import send_telegram_message

router = APIRouter()
_REGISTERED = False
_STATE_TASK: asyncio.Task | None = None

RANKS = ("Новичок", "Постоянник", "VIP", "Легенда")
GIVEAWAY_STATUSES = {
    "draft",
    "scheduled",
    "active",
    "paused",
    "awaiting_results",
    "completed",
    "cancelled",
}
ACTIVE_TICKET_STATUSES = {"active"}
REFUND_OPERATION_TYPES = {"reward_refund", "giveaway_refund", "giveaway_manual_refund"}
PURCHASE_LINE_RE = re.compile(r"\s*(?:\||;|\t)\s*")
RUS_MONTHS = {
    "января": 1,
    "февраля": 2,
    "марта": 3,
    "апреля": 4,
    "мая": 5,
    "июня": 6,
    "июля": 7,
    "августа": 8,
    "сентября": 9,
    "октября": 10,
    "ноября": 11,
    "декабря": 12,
}


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def norm_dt(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def json_load(raw: str | None, fallback):
    if not raw:
        return fallback
    try:
        value = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return fallback
    return value


def json_dump(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


class ShopPurchase(core.Base):
    __tablename__ = "shop_purchases"
    __table_args__ = (UniqueConstraint("fingerprint", name="uq_shop_purchase_fingerprint"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telegram_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.telegram_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    item_name: Mapped[str] = mapped_column(String(240), nullable=False)
    amount_kopecks: Mapped[int] = mapped_column(Integer, nullable=False)
    purchased_on: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class KnownChannel(core.Base):
    __tablename__ = "giveaway_known_channels"

    chat_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    invite_link: Mapped[str | None] = mapped_column(Text, nullable=True)
    bot_status: Mapped[str] = mapped_column(String(32), nullable=False, default="administrator")
    is_available: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Giveaway(core.Base):
    __tablename__ = "giveaways"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    public_id: Mapped[str | None] = mapped_column(String(20), nullable=True, unique=True, index=True)
    title: Mapped[str] = mapped_column(String(180), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft", index=True)
    ticket_price: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    allow_extra_tickets: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    per_user_limit: Mapped[int] = mapped_column(Integer, nullable=False, default=10)
    global_ticket_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    participant_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    allowed_ranks_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    rank_benefits_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    conditions_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    post_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    start_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    end_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class GiveawayPrize(core.Base):
    __tablename__ = "giveaway_prizes"
    __table_args__ = (UniqueConstraint("giveaway_id", "position", name="uq_giveaway_prize_position"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    giveaway_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("giveaways.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    prize_text: Mapped[str] = mapped_column(String(300), nullable=False)


class GiveawayChannel(core.Base):
    __tablename__ = "giveaway_channels"
    __table_args__ = (UniqueConstraint("giveaway_id", "chat_id", name="uq_giveaway_channel"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    giveaway_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("giveaways.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    invite_link: Mapped[str | None] = mapped_column(Text, nullable=True)
    required_subscription: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    publish_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class GiveawayPost(core.Base):
    __tablename__ = "giveaway_posts"
    __table_args__ = (UniqueConstraint("giveaway_id", "chat_id", "message_id", name="uq_giveaway_post_message"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    giveaway_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("giveaways.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    message_id: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class GiveawayParticipant(core.Base):
    __tablename__ = "giveaway_participants"
    __table_args__ = (UniqueConstraint("giveaway_id", "telegram_id", name="uq_giveaway_participant"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    giveaway_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("giveaways.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    telegram_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.telegram_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_chat_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active", index=True)
    exclusion_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class GiveawayTicket(core.Base):
    __tablename__ = "giveaway_tickets"
    __table_args__ = (UniqueConstraint("giveaway_id", "ticket_number", name="uq_giveaway_ticket_number"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    giveaway_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("giveaways.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    participant_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("giveaway_participants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    telegram_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    ticket_number: Mapped[int] = mapped_column(Integer, nullable=False)
    source: Mapped[str] = mapped_column(String(24), nullable=False)
    paid_amount: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    transaction_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("transactions.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    voided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    void_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    refunded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class GiveawayTicketPurchase(core.Base):
    __tablename__ = "giveaway_ticket_purchases"
    __table_args__ = (
        UniqueConstraint("giveaway_id", "telegram_id", "request_key", name="uq_giveaway_purchase_request"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    giveaway_id: Mapped[int] = mapped_column(Integer, ForeignKey("giveaways.id", ondelete="CASCADE"), nullable=False, index=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    request_key: Mapped[str] = mapped_column(String(80), nullable=False)
    ticket_count: Mapped[int] = mapped_column(Integer, nullable=False)
    total_cost: Mapped[int] = mapped_column(Integer, nullable=False)
    balance_after: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class GiveawaySelectionEvent(core.Base):
    __tablename__ = "giveaway_selection_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    giveaway_id: Mapped[int] = mapped_column(Integer, ForeignKey("giveaways.id", ondelete="CASCADE"), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    snapshot_json: Mapped[str] = mapped_column(Text, nullable=False)
    snapshot_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    eligible_participants: Mapped[int] = mapped_column(Integer, nullable=False)
    eligible_tickets: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class GiveawayResult(core.Base):
    __tablename__ = "giveaway_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    giveaway_id: Mapped[int] = mapped_column(Integer, ForeignKey("giveaways.id", ondelete="CASCADE"), nullable=False, index=True)
    selection_event_id: Mapped[int] = mapped_column(Integer, ForeignKey("giveaway_selection_events.id", ondelete="RESTRICT"), nullable=False, index=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    telegram_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    ticket_number: Mapped[int] = mapped_column(Integer, nullable=False)
    prize_text: Mapped[str] = mapped_column(String(300), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="active", index=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    selected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class GiveawayResultPost(core.Base):
    __tablename__ = "giveaway_result_posts"
    __table_args__ = (UniqueConstraint("giveaway_id", "chat_id", "message_id", name="uq_giveaway_result_post"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    giveaway_id: Mapped[int] = mapped_column(Integer, ForeignKey("giveaways.id", ondelete="CASCADE"), nullable=False, index=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    message_id: Mapped[int] = mapped_column(Integer, nullable=False)
    source_chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    source_message_id: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="published", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PurchaseImportPayload(BaseModel):
    text: str = Field(min_length=1, max_length=200_000)


class PurchaseCreatePayload(BaseModel):
    target: str = Field(min_length=1, max_length=64)
    item_name: str = Field(min_length=1, max_length=240)
    amount_rub: str = Field(min_length=1, max_length=32)
    purchased_on: str = Field(min_length=1, max_length=40)
    force_duplicate: bool = False


class GiveawayCreatePayload(BaseModel):
    title: str = Field(min_length=1, max_length=180)
    kind: str
    ticket_price: int = Field(default=0, ge=0, le=10_000_000)
    allow_extra_tickets: bool = True
    per_user_limit: int = Field(default=10, ge=1, le=10)
    global_ticket_limit: int | None = Field(default=None, ge=1, le=10_000_000)
    participant_limit: int | None = Field(default=None, ge=1, le=10_000_000)
    allowed_ranks: list[str] = Field(default_factory=list)
    rank_benefits: dict[str, dict] = Field(default_factory=dict)
    conditions: dict = Field(default_factory=dict)
    post: dict = Field(default_factory=dict)
    prizes: list[str] = Field(default_factory=list, max_length=100)
    channels: list[dict] = Field(default_factory=list, max_length=100)
    start_at: datetime | None = None
    end_at: datetime | None = None


class GiveawayUpdatePayload(GiveawayCreatePayload):
    pass


class TicketPurchasePayload(BaseModel):
    count: int = Field(ge=1, le=10)
    request_key: str = Field(min_length=8, max_length=80)


class ParticipantAdjustPayload(BaseModel):
    target: str = Field(min_length=1, max_length=64)
    delta: int = Field(ge=-10, le=10)
    reason: str | None = Field(default=None, max_length=300)
    refund_removed: bool = False
    source_chat_id: int | None = None


class ParticipantRemovePayload(BaseModel):
    target: str = Field(min_length=1, max_length=64)
    reason: str = Field(min_length=1, max_length=300)
    refund_paid: bool = False


class ManualRefundPayload(BaseModel):
    target: str = Field(min_length=1, max_length=64)
    amount: int = Field(ge=1, le=10_000_000)
    reason: str = Field(min_length=1, max_length=300)


class ReasonPayload(BaseModel):
    reason: str = Field(min_length=1, max_length=300)


class BotUserPayload(BaseModel):
    telegram_id: int
    username: str | None = Field(default=None, max_length=64)
    first_name: str = Field(default="Пользователь", max_length=255)
    last_name: str | None = Field(default=None, max_length=255)
    source_chat_id: int | None = None


class ChannelUpsertPayload(BaseModel):
    chat_id: int
    title: str = Field(min_length=1, max_length=255)
    username: str | None = Field(default=None, max_length=64)
    invite_link: str | None = Field(default=None, max_length=1000)
    bot_status: str = Field(default="administrator", max_length=32)
    is_available: bool = True


class PostRegistrationPayload(BaseModel):
    chat_id: int
    message_id: int
    status: str = Field(default="active", max_length=32)


class ReplacePostPayload(BaseModel):
    source_chat_id: int
    message_ids: list[int] = Field(min_length=1, max_length=10)


class ResultPublishPayload(BaseModel):
    source_chat_id: int
    source_message_id: int
    channel_ids: list[int] = Field(min_length=1, max_length=100)


def require_user(header: str | None) -> dict:
    tg = core.verify_init_data(header or "")
    core.get_or_create_user(tg)
    return tg


def require_owner(header: str | None) -> dict:
    tg = require_user(header)
    core.require_owner(tg)
    return tg


def bot_key() -> str:
    return hashlib.sha256(f"{core.BOT_TOKEN}:nyan-giveaway-internal:v1".encode()).hexdigest()


def require_bot_key(value: str | None) -> None:
    if not value or not hmac.compare_digest(value, bot_key()):
        raise HTTPException(status_code=403, detail="Неверный внутренний ключ бота")


def parse_amount_kopecks(raw: str) -> int:
    cleaned = raw.strip().lower().replace("₽", "").replace("руб.", "").replace("руб", "").replace(" ", "").replace(",", ".")
    try:
        value = Decimal(cleaned)
    except InvalidOperation as exc:
        raise ValueError("некорректная сумма") from exc
    if not value.is_finite() or value <= 0 or value > Decimal("100000000"):
        raise ValueError("сумма должна быть больше нуля")
    return int((value * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def parse_purchase_date(raw: str) -> date:
    value = raw.strip().lower()
    current_year = now_utc().year
    for fmt in ("%d.%m.%Y", "%d.%m.%y", "%Y-%m-%d", "%d/%m/%Y", "%d/%m/%y"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            pass
    for fmt in ("%d.%m", "%d/%m"):
        try:
            parsed = datetime.strptime(value, fmt)
            return date(current_year, parsed.month, parsed.day)
        except ValueError:
            pass
    parts = value.split()
    if len(parts) in {2, 3} and parts[0].isdigit() and parts[1] in RUS_MONTHS:
        year = int(parts[2]) if len(parts) == 3 and parts[2].isdigit() else current_year
        return date(year, RUS_MONTHS[parts[1]], int(parts[0]))
    raise ValueError("дата должна быть вроде 12.09.2026 или 12 сентября")


def purchase_fingerprint(telegram_id: int, item_name: str, amount_kopecks: int, purchased_on: date) -> str:
    normalized_item = " ".join(item_name.strip().lower().split())
    raw = f"{telegram_id}|{normalized_item}|{amount_kopecks}|{purchased_on.isoformat()}"
    return hashlib.sha256(raw.encode()).hexdigest()


def purchase_dict(row: ShopPurchase) -> dict:
    return {
        "id": row.id,
        "purchase_id": f"NYP-{row.id:06d}",
        "telegram_id": row.telegram_id,
        "item_name": row.item_name,
        "amount_kopecks": row.amount_kopecks,
        "amount_rub": f"{row.amount_kopecks / 100:.2f}",
        "purchased_on": row.purchased_on.isoformat(),
        "created_at": row.created_at.isoformat(),
    }


def giveaway_dict(session, row: Giveaway, include_private: bool = False) -> dict:
    prizes = session.scalars(
        select(GiveawayPrize).where(GiveawayPrize.giveaway_id == row.id).order_by(GiveawayPrize.position.asc())
    ).all()
    channels = session.scalars(
        select(GiveawayChannel).where(GiveawayChannel.giveaway_id == row.id).order_by(GiveawayChannel.id.asc())
    ).all()
    data = {
        "id": row.id,
        "public_id": row.public_id,
        "title": row.title,
        "kind": row.kind,
        "status": row.status,
        "ticket_price": row.ticket_price,
        "allow_extra_tickets": row.allow_extra_tickets,
        "per_user_limit": row.per_user_limit,
        "global_ticket_limit": row.global_ticket_limit,
        "participant_limit": row.participant_limit,
        "allowed_ranks": json_load(row.allowed_ranks_json, []),
        "rank_benefits": json_load(row.rank_benefits_json, {}),
        "conditions": json_load(row.conditions_json, {}),
        "start_at": norm_dt(row.start_at).isoformat() if row.start_at else None,
        "end_at": norm_dt(row.end_at).isoformat() if row.end_at else None,
        "created_at": norm_dt(row.created_at).isoformat(),
        "updated_at": norm_dt(row.updated_at).isoformat(),
        "prizes": [{"position": p.position, "text": p.prize_text} for p in prizes],
        "channels": [
            {
                "chat_id": c.chat_id,
                "title": c.title,
                "username": c.username,
                "invite_link": c.invite_link if include_private else None,
                "required_subscription": c.required_subscription,
                "publish_enabled": c.publish_enabled,
            }
            for c in channels
        ],
    }
    if include_private:
        data["post"] = json_load(row.post_json, {})
        data["started_at"] = norm_dt(row.started_at).isoformat() if row.started_at else None
        data["closed_at"] = norm_dt(row.closed_at).isoformat() if row.closed_at else None
        data["completed_at"] = norm_dt(row.completed_at).isoformat() if row.completed_at else None
        data["cancelled_at"] = norm_dt(row.cancelled_at).isoformat() if row.cancelled_at else None
    return data


def validate_ranks(values: list[str]) -> list[str]:
    result = []
    for value in values:
        if value not in RANKS:
            raise HTTPException(status_code=400, detail=f"Неизвестный ранг: {value}")
        if value not in result:
            result.append(value)
    return result


def validate_rank_benefits(raw: dict[str, dict]) -> dict[str, dict]:
    result: dict[str, dict] = {}
    for rank, value in raw.items():
        if rank not in RANKS or not isinstance(value, dict):
            raise HTTPException(status_code=400, detail="Некорректные преимущества рангов")
        bonus = int(value.get("bonus_free_tickets", 0))
        discount = int(value.get("discount_percent", 0))
        max_raw = value.get("max_tickets")
        max_tickets = int(max_raw) if max_raw is not None else None
        if not 0 <= bonus <= 9:
            raise HTTPException(status_code=400, detail=f"Бесплатные билеты для {rank}: от 0 до 9")
        if not 0 <= discount <= 100:
            raise HTTPException(status_code=400, detail=f"Скидка для {rank}: от 0 до 100%")
        if max_tickets is not None and not 1 <= max_tickets <= 10:
            raise HTTPException(status_code=400, detail=f"Лимит билетов для {rank}: от 1 до 10")
        result[rank] = {
            "bonus_free_tickets": bonus,
            "discount_percent": discount,
        }
        if max_tickets is not None:
            result[rank]["max_tickets"] = max_tickets
    return result


def validate_conditions(raw: dict) -> dict:
    if not isinstance(raw, dict):
        raise HTTPException(status_code=400, detail="Условия должны быть объектом")
    allowed = {
        "min_balance",
        "min_purchase_count",
        "min_shop_spend_rub",
        "min_shop_spend_kopecks",
        "min_lapcoins_spent",
        "min_account_age_days",
        "achievement_key",
        "promo_code",
    }
    unknown = set(raw) - allowed
    if unknown:
        raise HTTPException(status_code=400, detail=f"Неизвестные условия: {', '.join(sorted(unknown))}")
    result = {}
    for key in ("min_balance", "min_purchase_count", "min_lapcoins_spent", "min_account_age_days"):
        if key in raw and raw[key] is not None:
            value = int(raw[key])
            if value < 0 or value > 100_000_000:
                raise HTTPException(status_code=400, detail=f"Некорректное условие: {key}")
            result[key] = value
    if raw.get("min_shop_spend_kopecks") is not None:
        value = int(raw["min_shop_spend_kopecks"])
        if value < 0 or value > 10_000_000_000:
            raise HTTPException(status_code=400, detail="Некорректная сумма покупок")
        result["min_shop_spend_kopecks"] = value
    elif raw.get("min_shop_spend_rub") is not None:
        try:
            result["min_shop_spend_kopecks"] = parse_amount_kopecks(str(raw["min_shop_spend_rub"]))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"Некорректная сумма покупок: {exc}") from exc
    if raw.get("achievement_key"):
        key = str(raw["achievement_key"]).strip()
        if key not in ACHIEVEMENT_BY_KEY:
            raise HTTPException(status_code=400, detail="Такого достижения нет")
        result["achievement_key"] = key
    if raw.get("promo_code"):
        code = core.normalize_promo_code(str(raw["promo_code"]))
        if not core.PROMO_PATTERN.fullmatch(code):
            raise HTTPException(status_code=400, detail="Некорректный промокод в условии")
        result["promo_code"] = code
    return result


def current_rank(session, telegram_id: int) -> str:
    earned = session.scalar(
        select(func.coalesce(func.sum(core.Transaction.amount), 0)).where(
            core.Transaction.telegram_id == telegram_id,
            core.Transaction.amount > 0,
            ~core.Transaction.operation_type.in_(REFUND_OPERATION_TYPES),
        )
    ) or 0
    return level_data(int(earned), settings(session))["name"]


def active_ticket_query(giveaway_id: int, telegram_id: int | None = None):
    stmt = select(GiveawayTicket).where(
        GiveawayTicket.giveaway_id == giveaway_id,
        GiveawayTicket.voided_at.is_(None),
        GiveawayTicket.refunded_at.is_(None),
    )
    if telegram_id is not None:
        stmt = stmt.where(GiveawayTicket.telegram_id == telegram_id)
    return stmt


def ticket_count(session, giveaway_id: int, telegram_id: int | None = None) -> int:
    stmt = select(func.count()).select_from(GiveawayTicket).where(
        GiveawayTicket.giveaway_id == giveaway_id,
        GiveawayTicket.voided_at.is_(None),
        GiveawayTicket.refunded_at.is_(None),
    )
    if telegram_id is not None:
        stmt = stmt.where(GiveawayTicket.telegram_id == telegram_id)
    return int(session.scalar(stmt) or 0)


def next_ticket_number(session, giveaway_id: int) -> int:
    value = session.scalar(
        select(func.coalesce(func.max(GiveawayTicket.ticket_number), 0)).where(GiveawayTicket.giveaway_id == giveaway_id)
    ) or 0
    return int(value) + 1


def user_ticket_limit(session, giveaway: Giveaway, telegram_id: int) -> tuple[int, dict]:
    rank = current_rank(session, telegram_id)
    benefits = json_load(giveaway.rank_benefits_json, {})
    config = benefits.get(rank, {}) if isinstance(benefits, dict) else {}
    configured = int(config.get("max_tickets", giveaway.per_user_limit))
    return min(10, max(1, configured)), config


def user_ticket_price(session, giveaway: Giveaway, telegram_id: int) -> int:
    _, config = user_ticket_limit(session, giveaway, telegram_id)
    discount = min(100, max(0, int(config.get("discount_percent", 0))))
    return max(0, (giveaway.ticket_price * (100 - discount) + 99) // 100)


def free_ticket_entitlement(session, giveaway: Giveaway, telegram_id: int) -> int:
    _, config = user_ticket_limit(session, giveaway, telegram_id)
    base = 1 if giveaway.kind == "free" else 0
    bonus = min(9, max(0, int(config.get("bonus_free_tickets", 0))))
    limit, _ = user_ticket_limit(session, giveaway, telegram_id)
    return min(limit, base + bonus)


def refresh_state(session, giveaway: Giveaway) -> None:
    if giveaway.status in {"completed", "cancelled", "draft", "paused", "awaiting_results"}:
        return
    timestamp = now_utc()
    start_at = norm_dt(giveaway.start_at)
    end_at = norm_dt(giveaway.end_at)

    if giveaway.status == "scheduled":
        return

    if giveaway.status == "active":
        reached_time = bool(end_at and end_at <= timestamp)
        reached_people = False
        if giveaway.participant_limit is not None:
            count = session.scalar(
                select(func.count()).select_from(GiveawayParticipant).where(
                    GiveawayParticipant.giveaway_id == giveaway.id,
                    GiveawayParticipant.status == "active",
                )
            ) or 0
            reached_people = int(count) >= giveaway.participant_limit
        if reached_time or reached_people:
            giveaway.status = "awaiting_results"
            giveaway.closed_at = timestamp
            giveaway.updated_at = timestamp


def telegram_api(method: str, payload: dict, timeout: int = 12):
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{core.BOT_TOKEN}/{method}",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        raise RuntimeError(f"Telegram API {method} недоступен: {exc}") from exc
    if not data.get("ok"):
        raise RuntimeError(data.get("description") or f"Telegram API {method} вернул ошибку")
    return data.get("result")


def giveaway_keyboard(public_id: str, closed: bool = False) -> dict:
    if closed:
        return {
            "inline_keyboard": [[
                {"text": "Розыгрыш завершён", "callback_data": f"nyg:done:{public_id}"}
            ]]
        }
    return {
        "inline_keyboard": [
            [
                {"text": "Участвовать", "callback_data": f"nyg:j:{public_id}"},
                {
                    "text": "Купить билеты",
                    "url": f"https://t.me/nyancash_bot?startapp=giveaway_{public_id}",
                },
            ]
        ]
    }


def _cleanup_telegram_messages(sent: list[tuple[int, list[int]]]) -> None:
    for chat_id, message_ids in reversed(sent):
        if not message_ids:
            continue
        try:
            telegram_api("deleteMessages", {"chat_id": chat_id, "message_ids": message_ids}, timeout=8)
            continue
        except Exception:
            pass
        for message_id in message_ids:
            try:
                telegram_api("deleteMessage", {"chat_id": chat_id, "message_id": message_id}, timeout=6)
            except Exception:
                pass


def publish_giveaway_locked(session, giveaway: Giveaway) -> list[GiveawayPost]:
    existing = session.scalars(
        select(GiveawayPost).where(
            GiveawayPost.giveaway_id == giveaway.id,
            GiveawayPost.status == "active",
        )
    ).all()
    if existing:
        return list(existing)

    post = json_load(giveaway.post_json, {})
    source_chat_id = post.get("source_chat_id")
    raw_ids = post.get("message_ids") or []
    try:
        message_ids = [int(value) for value in raw_ids]
        source_chat_id = int(source_chat_id)
    except (TypeError, ValueError):
        raise HTTPException(status_code=409, detail="Исходный пост розыгрыша настроен некорректно")

    if not message_ids or len(message_ids) > 10:
        raise HTTPException(status_code=409, detail="В исходном посте должно быть от 1 до 10 сообщений")

    channels = session.scalars(
        select(GiveawayChannel)
        .where(
            GiveawayChannel.giveaway_id == giveaway.id,
            GiveawayChannel.publish_enabled.is_(True),
        )
        .order_by(GiveawayChannel.id.asc())
    ).all()
    if not channels:
        raise HTTPException(status_code=409, detail="Не выбран ни один канал для публикации")

    sent: list[tuple[int, list[int]]] = []
    created: list[GiveawayPost] = []
    timestamp = now_utc()
    keyboard = giveaway_keyboard(giveaway.public_id or "")

    try:
        for channel in channels:
            if len(message_ids) == 1:
                result = telegram_api(
                    "copyMessage",
                    {
                        "chat_id": channel.chat_id,
                        "from_chat_id": source_chat_id,
                        "message_id": message_ids[0],
                        "reply_markup": keyboard,
                    },
                )
                copied_ids = [int(result["message_id"])]
            else:
                result = telegram_api(
                    "copyMessages",
                    {
                        "chat_id": channel.chat_id,
                        "from_chat_id": source_chat_id,
                        "message_ids": message_ids,
                    },
                    timeout=20,
                )
                copied_ids = [int(item["message_id"]) for item in result]
                if not copied_ids:
                    raise RuntimeError("Telegram не вернул ID скопированного альбома")
                telegram_api(
                    "editMessageReplyMarkup",
                    {
                        "chat_id": channel.chat_id,
                        "message_id": copied_ids[-1],
                        "reply_markup": keyboard,
                    },
                )

            sent.append((channel.chat_id, copied_ids))
            for copied_id in copied_ids:
                row = GiveawayPost(
                    giveaway_id=giveaway.id,
                    chat_id=channel.chat_id,
                    message_id=copied_id,
                    status="active",
                    last_error=None,
                    created_at=timestamp,
                    updated_at=timestamp,
                )
                session.add(row)
                created.append(row)
        session.flush()
        return created
    except Exception as exc:
        _cleanup_telegram_messages(sent)
        if isinstance(exc, HTTPException):
            raise
        raise HTTPException(status_code=502, detail=f"Не удалось опубликовать розыгрыш: {exc}") from exc


def replace_giveaway_posts_locked(
    session,
    giveaway: Giveaway,
    source_chat_id: int,
    message_ids: list[int],
) -> list[GiveawayPost]:
    if not message_ids or len(message_ids) > 10:
        raise HTTPException(status_code=400, detail="В посте должно быть от 1 до 10 сообщений")

    channels = session.scalars(
        select(GiveawayChannel)
        .where(
            GiveawayChannel.giveaway_id == giveaway.id,
            GiveawayChannel.publish_enabled.is_(True),
        )
        .order_by(GiveawayChannel.id.asc())
    ).all()
    if not channels:
        raise HTTPException(status_code=409, detail="У розыгрыша нет каналов публикации")

    old_posts = session.scalars(
        select(GiveawayPost).where(
            GiveawayPost.giveaway_id == giveaway.id,
            GiveawayPost.status == "active",
        )
    ).all()

    closed = giveaway.status in {"awaiting_results", "completed", "cancelled"}
    keyboard = giveaway_keyboard(giveaway.public_id or "", closed=closed)
    sent: list[tuple[int, list[int]]] = []
    new_posts: list[GiveawayPost] = []
    timestamp = now_utc()

    try:
        for channel in channels:
            if len(message_ids) == 1:
                result = telegram_api(
                    "copyMessage",
                    {
                        "chat_id": channel.chat_id,
                        "from_chat_id": source_chat_id,
                        "message_id": int(message_ids[0]),
                        "reply_markup": keyboard,
                    },
                )
                copied_ids = [int(result["message_id"])]
            else:
                result = telegram_api(
                    "copyMessages",
                    {
                        "chat_id": channel.chat_id,
                        "from_chat_id": source_chat_id,
                        "message_ids": [int(value) for value in message_ids],
                    },
                    timeout=20,
                )
                copied_ids = [int(item["message_id"]) for item in result]
                if not copied_ids:
                    raise RuntimeError("Telegram не вернул ID нового альбома")
                telegram_api(
                    "editMessageReplyMarkup",
                    {
                        "chat_id": channel.chat_id,
                        "message_id": copied_ids[-1],
                        "reply_markup": keyboard,
                    },
                )

            sent.append((channel.chat_id, copied_ids))
            for copied_id in copied_ids:
                row = GiveawayPost(
                    giveaway_id=giveaway.id,
                    chat_id=channel.chat_id,
                    message_id=copied_id,
                    status="active",
                    last_error=None,
                    created_at=timestamp,
                    updated_at=timestamp,
                )
                session.add(row)
                new_posts.append(row)

        session.flush()
    except Exception as exc:
        _cleanup_telegram_messages(sent)
        if isinstance(exc, HTTPException):
            raise
        raise HTTPException(status_code=502, detail=f"Не удалось обновить посты: {exc}") from exc

    # New copies exist everywhere. Only now retire and delete the old copies.
    old_by_chat: dict[int, list[int]] = defaultdict(list)
    for post in old_posts:
        post.status = "replaced"
        post.updated_at = timestamp
        old_by_chat[post.chat_id].append(post.message_id)
    _cleanup_telegram_messages(list(old_by_chat.items()))

    giveaway.post_json = json_dump(
        {"source_chat_id": int(source_chat_id), "message_ids": [int(value) for value in message_ids]}
    )
    giveaway.updated_at = timestamp
    return new_posts


def publish_results_locked(
    session,
    giveaway: Giveaway,
    source_chat_id: int,
    source_message_id: int,
    channel_ids: list[int],
) -> list[GiveawayResultPost]:
    if giveaway.status not in {"awaiting_results", "completed"}:
        raise HTTPException(status_code=409, detail="Итоги можно публиковать только после выбора победителей")

    active_results = session.scalar(
        select(func.count()).select_from(GiveawayResult).where(
            GiveawayResult.giveaway_id == giveaway.id,
            GiveawayResult.status == "active",
        )
    ) or 0
    prizes = session.scalar(
        select(func.count()).select_from(GiveawayPrize).where(
            GiveawayPrize.giveaway_id == giveaway.id
        )
    ) or 0
    if int(active_results) != int(prizes) or int(prizes) == 0:
        raise HTTPException(status_code=409, detail="Список победителей ещё не готов")

    allowed_channels = {
        row.chat_id
        for row in session.scalars(
            select(GiveawayChannel).where(
                GiveawayChannel.giveaway_id == giveaway.id,
                GiveawayChannel.publish_enabled.is_(True),
            )
        ).all()
    }
    requested = []
    for raw in channel_ids:
        channel_id = int(raw)
        if channel_id not in allowed_channels:
            raise HTTPException(status_code=400, detail=f"Канал {channel_id} не относится к этому розыгрышу")
        if channel_id not in requested:
            requested.append(channel_id)
    if not requested:
        raise HTTPException(status_code=400, detail="Выберите хотя бы один канал для итогов")

    timestamp = now_utc()
    sent: list[tuple[int, list[int]]] = []
    created: list[GiveawayResultPost] = []
    try:
        for channel_id in requested:
            result = telegram_api(
                "copyMessage",
                {
                    "chat_id": channel_id,
                    "from_chat_id": int(source_chat_id),
                    "message_id": int(source_message_id),
                },
            )
            message_id = int(result["message_id"])
            sent.append((channel_id, [message_id]))
            row = GiveawayResultPost(
                giveaway_id=giveaway.id,
                chat_id=channel_id,
                message_id=message_id,
                source_chat_id=int(source_chat_id),
                source_message_id=int(source_message_id),
                status="published",
                created_at=timestamp,
            )
            session.add(row)
            created.append(row)
        session.flush()
        return created
    except Exception as exc:
        _cleanup_telegram_messages(sent)
        if isinstance(exc, HTTPException):
            raise
        raise HTTPException(status_code=502, detail=f"Не удалось опубликовать итоги: {exc}") from exc


def sync_giveaway_buttons(session, giveaway: Giveaway, closed: bool) -> None:
    posts = session.scalars(
        select(GiveawayPost).where(
            GiveawayPost.giveaway_id == giveaway.id,
            GiveawayPost.status == "active",
        )
    ).all()
    if not posts:
        return

    # Only the last copied message of each channel carries buttons. Editing all
    # messages is harmless but unnecessary, so choose the maximum message_id.
    last_by_chat: dict[int, GiveawayPost] = {}
    for post in posts:
        current = last_by_chat.get(post.chat_id)
        if current is None or post.message_id > current.message_id:
            last_by_chat[post.chat_id] = post

    keyboard = giveaway_keyboard(giveaway.public_id or "", closed=closed)
    timestamp = now_utc()
    for post in last_by_chat.values():
        try:
            telegram_api(
                "editMessageReplyMarkup",
                {
                    "chat_id": post.chat_id,
                    "message_id": post.message_id,
                    "reply_markup": keyboard,
                },
            )
            post.last_error = None
            post.updated_at = timestamp
        except Exception as exc:
            post.last_error = str(exc)[:2000]
            post.updated_at = timestamp


def telegram_membership(chat_id: int, telegram_id: int) -> tuple[bool | None, str | None]:
    try:
        params = urllib.parse.urlencode({"chat_id": str(chat_id), "user_id": str(telegram_id)})
        url = f"https://api.telegram.org/bot{core.BOT_TOKEN}/getChatMember?{params}"
        request = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(request, timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if not payload.get("ok"):
            return None, "Telegram не подтвердил проверку подписки"
        result = payload.get("result") or {}
        status = result.get("status")
        if status in {"creator", "administrator", "member"}:
            return True, None
        if status == "restricted" and bool(result.get("is_member")):
            return True, None
        return False, None
    except Exception:
        return None, "Не удалось проверить подписку"


def eligibility(session, giveaway: Giveaway, user: core.User, *, check_subscriptions: bool = True) -> tuple[bool, str | None, bool]:
    allowed_ranks = json_load(giveaway.allowed_ranks_json, [])
    rank = current_rank(session, user.telegram_id)
    if allowed_ranks and rank not in allowed_ranks:
        return False, f"Для этого розыгрыша нужен другой ранг. Ваш ранг: {rank}", False

    conditions = json_load(giveaway.conditions_json, {})
    if core.is_owner(user.telegram_id):
        balance = 10**18
    else:
        balance = int(user.balance)

    min_balance = int(conditions.get("min_balance", 0) or 0)
    if balance < min_balance:
        return False, f"Для участия нужен баланс от {min_balance} 🐾", False

    purchase_count = session.scalar(
        select(func.count()).select_from(ShopPurchase).where(ShopPurchase.telegram_id == user.telegram_id)
    ) or 0
    min_purchase_count = int(conditions.get("min_purchase_count", 0) or 0)
    if int(purchase_count) < min_purchase_count:
        return False, f"Для участия нужно минимум {min_purchase_count} покупок в Нян Шопе", False

    shop_spend = session.scalar(
        select(func.coalesce(func.sum(ShopPurchase.amount_kopecks), 0)).where(ShopPurchase.telegram_id == user.telegram_id)
    ) or 0
    min_shop_spend = int(conditions.get("min_shop_spend_kopecks", 0) or 0)
    if int(shop_spend) < min_shop_spend:
        return False, f"Для участия нужно потратить в Нян Шопе минимум {min_shop_spend / 100:.2f} ₽", False

    spent_raw = session.scalar(
        select(func.coalesce(func.sum(core.Transaction.amount), 0)).where(
            core.Transaction.telegram_id == user.telegram_id,
            core.Transaction.amount < 0,
        )
    ) or 0
    min_spent = int(conditions.get("min_lapcoins_spent", 0) or 0)
    if abs(int(spent_raw)) < min_spent:
        return False, f"Для участия нужно потратить минимум {min_spent} 🐾", False

    min_age = int(conditions.get("min_account_age_days", 0) or 0)
    created_at = norm_dt(user.created_at)
    age_days = max(0, (now_utc() - created_at).days)
    if age_days < min_age:
        return False, f"Аккаунту Nyan Cash должно быть минимум {min_age} дней", False

    achievement_key = conditions.get("achievement_key")
    if achievement_key:
        unlocked = session.scalar(
            select(AchievementUnlock.id).where(
                AchievementUnlock.telegram_id == user.telegram_id,
                AchievementUnlock.achievement_key == achievement_key,
            )
        )
        if unlocked is None:
            title = ACHIEVEMENT_BY_KEY.get(achievement_key, {}).get("title", achievement_key)
            return False, f"Для участия нужно достижение «{title}»", False

    promo_code = conditions.get("promo_code")
    if promo_code:
        promo = session.scalar(select(core.PromoCode).where(core.PromoCode.code == promo_code))
        redeemed = None
        if promo:
            redeemed = session.scalar(
                select(core.PromoRedemption.id).where(
                    core.PromoRedemption.promo_id == promo.id,
                    core.PromoRedemption.telegram_id == user.telegram_id,
                )
            )
        if redeemed is None:
            return False, f"Для участия нужно активировать промокод {promo_code}", False

    if check_subscriptions:
        channels = session.scalars(
            select(GiveawayChannel).where(
                GiveawayChannel.giveaway_id == giveaway.id,
                GiveawayChannel.required_subscription.is_(True),
            ).order_by(GiveawayChannel.id.asc())
        ).all()
        for channel in channels:
            member, error = telegram_membership(channel.chat_id, user.telegram_id)
            label = f"@{channel.username}" if channel.username else channel.title
            if member is None:
                return False, f"Не удалось проверить подписку на {label}. Попробуйте позже.", True
            if not member:
                return False, f"Вы не подписаны на {label}", False

    return True, None, False


def ensure_joinable(session, giveaway: Giveaway) -> None:
    refresh_state(session, giveaway)
    if giveaway.status == "paused":
        raise HTTPException(status_code=409, detail="Розыгрыш временно приостановлен")
    if giveaway.status == "scheduled":
        raise HTTPException(status_code=409, detail="Розыгрыш ещё не начался")
    if giveaway.status == "awaiting_results":
        raise HTTPException(status_code=409, detail="Розыгрыш завершён. Ожидаются итоги")
    if giveaway.status in {"completed", "cancelled"}:
        raise HTTPException(status_code=409, detail="Розыгрыш завершён")
    if giveaway.status != "active":
        raise HTTPException(status_code=409, detail="Розыгрыш сейчас недоступен")


def ensure_user_from_bot(session, payload: BotUserPayload) -> core.User:
    timestamp = now_utc()
    user = session.scalar(select(core.User).where(core.User.telegram_id == payload.telegram_id).with_for_update())
    if user is None:
        user = core.User(
            telegram_id=payload.telegram_id,
            username=payload.username,
            first_name=payload.first_name or "Пользователь",
            last_name=payload.last_name,
            balance=0,
            created_at=timestamp,
            last_seen_at=timestamp,
        )
        session.add(user)
        session.flush()
    else:
        user.username = payload.username
        user.first_name = payload.first_name or user.first_name or "Пользователь"
        user.last_name = payload.last_name
        user.last_seen_at = timestamp
    return user


def get_giveaway_locked(session, public_id: str) -> Giveaway:
    row = session.scalar(
        select(Giveaway).where(Giveaway.public_id == public_id).with_for_update()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Розыгрыш не найден")
    return row


def get_or_create_participant(session, giveaway: Giveaway, user: core.User, source_chat_id: int | None = None) -> GiveawayParticipant:
    row = session.scalar(
        select(GiveawayParticipant).where(
            GiveawayParticipant.giveaway_id == giveaway.id,
            GiveawayParticipant.telegram_id == user.telegram_id,
        ).with_for_update()
    )
    timestamp = now_utc()
    if row is None:
        row = GiveawayParticipant(
            giveaway_id=giveaway.id,
            telegram_id=user.telegram_id,
            source_chat_id=source_chat_id,
            status="active",
            exclusion_reason=None,
            joined_at=timestamp,
            updated_at=timestamp,
        )
        session.add(row)
        session.flush()
    elif row.status != "active":
        raise HTTPException(status_code=409, detail="Вы больше не можете участвовать в этом розыгрыше")
    elif row.source_chat_id is None and source_chat_id is not None:
        row.source_chat_id = source_chat_id
        row.updated_at = timestamp
    return row


def add_ticket_rows(session, giveaway: Giveaway, participant: GiveawayParticipant, count: int, source: str, paid_each: int, transaction_id: int | None) -> list[int]:
    start = next_ticket_number(session, giveaway.id)
    timestamp = now_utc()
    numbers = []
    for offset in range(count):
        number = start + offset
        session.add(
            GiveawayTicket(
                giveaway_id=giveaway.id,
                participant_id=participant.id,
                telegram_id=participant.telegram_id,
                ticket_number=number,
                source=source,
                paid_amount=paid_each,
                transaction_id=transaction_id,
                created_at=timestamp,
                voided_at=None,
                void_reason=None,
                refunded_at=None,
            )
        )
        numbers.append(number)
    session.flush()
    return numbers


def join_impl(session, giveaway: Giveaway, user: core.User, source_chat_id: int | None = None) -> dict:
    ensure_joinable(session, giveaway)
    ok, reason, retryable = eligibility(session, giveaway, user, check_subscriptions=True)
    if not ok:
        raise HTTPException(status_code=503 if retryable else 409, detail=reason or "Условия участия не выполнены")

    existing = ticket_count(session, giveaway.id, user.telegram_id)
    if existing > 0:
        limit, _ = user_ticket_limit(session, giveaway, user.telegram_id)
        return {
            "ok": True,
            "already_joined": True,
            "message": f"Вы уже участвуете. У вас {existing} билетов",
            "tickets": existing,
            "limit": limit,
        }

    free_count = free_ticket_entitlement(session, giveaway, user.telegram_id)
    if free_count <= 0:
        return {
            "ok": True,
            "purchase_required": True,
            "message": "Для участия нужно купить билет",
            "tickets": 0,
            "limit": user_ticket_limit(session, giveaway, user.telegram_id)[0],
        }

    participant = get_or_create_participant(session, giveaway, user, source_chat_id)
    global_existing = ticket_count(session, giveaway.id)
    if giveaway.global_ticket_limit is not None:
        free_count = min(free_count, max(0, giveaway.global_ticket_limit - global_existing))
    if free_count <= 0:
        raise HTTPException(status_code=409, detail="Общий лимит билетов исчерпан")

    numbers = add_ticket_rows(session, giveaway, participant, free_count, "free", 0, None)
    refresh_state(session, giveaway)
    return {
        "ok": True,
        "already_joined": False,
        "message": f"Теперь вы участвуете в розыгрыше. Билетов: {free_count}",
        "tickets": free_count,
        "ticket_numbers": numbers,
        "limit": user_ticket_limit(session, giveaway, user.telegram_id)[0],
    }


def purchase_tickets_impl(session, giveaway: Giveaway, user: core.User, count: int, request_key: str, source_chat_id: int | None = None) -> dict:
    previous = session.scalar(
        select(GiveawayTicketPurchase).where(
            GiveawayTicketPurchase.giveaway_id == giveaway.id,
            GiveawayTicketPurchase.telegram_id == user.telegram_id,
            GiveawayTicketPurchase.request_key == request_key,
        )
    )
    if previous:
        return {
            "ok": True,
            "idempotent": True,
            "tickets_added": previous.ticket_count,
            "cost": previous.total_cost,
            "balance": previous.balance_after,
            "tickets": ticket_count(session, giveaway.id, user.telegram_id),
        }

    ensure_joinable(session, giveaway)
    ok, reason, retryable = eligibility(session, giveaway, user, check_subscriptions=True)
    if not ok:
        raise HTTPException(status_code=503 if retryable else 409, detail=reason or "Условия участия не выполнены")

    if giveaway.kind == "free" and not giveaway.allow_extra_tickets:
        raise HTTPException(status_code=409, detail="Дополнительные билеты в этом розыгрыше отключены")

    current = ticket_count(session, giveaway.id, user.telegram_id)
    limit, _ = user_ticket_limit(session, giveaway, user.telegram_id)
    if current + count > limit:
        raise HTTPException(status_code=409, detail=f"Лимит: {limit} билетов на человека")

    total_current = ticket_count(session, giveaway.id)
    if giveaway.global_ticket_limit is not None and total_current + count > giveaway.global_ticket_limit:
        remaining = max(0, giveaway.global_ticket_limit - total_current)
        raise HTTPException(status_code=409, detail=f"Осталось только {remaining} билетов")

    price_each = user_ticket_price(session, giveaway, user.telegram_id)
    if price_each <= 0:
        total_cost = 0
    else:
        total_cost = price_each * count

    if not core.is_owner(user.telegram_id) and user.balance < total_cost:
        raise HTTPException(status_code=409, detail="Недостаточно лапкоинов")

    participant = get_or_create_participant(session, giveaway, user, source_chat_id)
    transaction_id = None
    if total_cost > 0 and not core.is_owner(user.telegram_id):
        user.balance -= total_cost
        tx = core.Transaction(
            telegram_id=user.telegram_id,
            amount=-total_cost,
            operation_type="giveaway_ticket",
            description=f"{count} бил. · {giveaway.public_id}",
            created_at=now_utc(),
        )
        session.add(tx)
        session.flush()
        transaction_id = tx.id

    numbers = add_ticket_rows(session, giveaway, participant, count, "purchased", price_each if not core.is_owner(user.telegram_id) else 0, transaction_id)
    purchase = GiveawayTicketPurchase(
        giveaway_id=giveaway.id,
        telegram_id=user.telegram_id,
        request_key=request_key,
        ticket_count=count,
        total_cost=total_cost if not core.is_owner(user.telegram_id) else 0,
        balance_after=user.balance,
        created_at=now_utc(),
    )
    session.add(purchase)
    session.flush()
    refresh_state(session, giveaway)
    return {
        "ok": True,
        "idempotent": False,
        "tickets_added": count,
        "ticket_numbers": numbers,
        "cost": total_cost if not core.is_owner(user.telegram_id) else 0,
        "balance": user.balance,
        "tickets": current + count,
        "limit": limit,
    }


def parse_purchase_line(line: str, line_no: int, session) -> dict:
    parts = PURCHASE_LINE_RE.split(line.strip())
    if len(parts) != 4:
        raise ValueError(f"строка {line_no}: нужно 4 поля: Telegram ID | товар | сумма | дата")
    target, item_name, amount_raw, date_raw = [part.strip() for part in parts]
    if not target or not item_name:
        raise ValueError(f"строка {line_no}: пустой Telegram ID или товар")
    user = core.find_target_user(session, target, lock=False)
    if user is None:
        raise ValueError(f"строка {line_no}: пользователь {target} не найден в Nyan Cash")
    if len(item_name) > 240:
        raise ValueError(f"строка {line_no}: название покупки слишком длинное")
    try:
        amount = parse_amount_kopecks(amount_raw)
        purchased_on = parse_purchase_date(date_raw)
    except ValueError as exc:
        raise ValueError(f"строка {line_no}: {exc}") from exc
    if purchased_on > now_utc().date():
        raise ValueError(f"строка {line_no}: дата покупки не может быть в будущем")
    return {
        "telegram_id": user.telegram_id,
        "item_name": item_name,
        "amount_kopecks": amount,
        "purchased_on": purchased_on,
        "fingerprint": purchase_fingerprint(user.telegram_id, item_name, amount, purchased_on),
    }


def apply_giveaway_payload(session, row: Giveaway, payload: GiveawayCreatePayload, *, replacing: bool) -> None:
    if payload.kind not in {"free", "paid"}:
        raise HTTPException(status_code=400, detail="Тип розыгрыша: free или paid")
    if payload.kind == "paid" and payload.ticket_price <= 0:
        raise HTTPException(status_code=400, detail="Для платного розыгрыша цена билета должна быть больше нуля")
    if payload.kind == "free" and payload.allow_extra_tickets and payload.ticket_price <= 0:
        raise HTTPException(status_code=400, detail="Укажите цену дополнительных билетов или отключите их покупку")

    allowed_ranks = validate_ranks(payload.allowed_ranks)
    benefits = validate_rank_benefits(payload.rank_benefits)
    conditions = validate_conditions(payload.conditions)

    start_at = norm_dt(payload.start_at)
    end_at = norm_dt(payload.end_at)
    if start_at and end_at and end_at <= start_at:
        raise HTTPException(status_code=400, detail="Время завершения должно быть позже времени старта")

    if not payload.prizes:
        raise HTTPException(status_code=400, detail="Добавьте хотя бы одно призовое место")
    normalized_prizes = []
    for index, value in enumerate(payload.prizes, start=1):
        text = str(value).strip()
        if not text or len(text) > 300:
            raise HTTPException(status_code=400, detail=f"Некорректный приз для места {index}")
        normalized_prizes.append(text)

    seen_channels: set[int] = set()
    normalized_channels = []
    for raw in payload.channels:
        try:
            chat_id = int(raw.get("chat_id"))
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="Некорректный chat_id канала")
        if chat_id in seen_channels:
            raise HTTPException(status_code=400, detail="Один канал указан несколько раз")
        seen_channels.add(chat_id)
        known = session.get(KnownChannel, chat_id)
        title = str(raw.get("title") or (known.title if known else "")).strip()
        if not title:
            raise HTTPException(status_code=400, detail=f"Канал {chat_id} не зарегистрирован")
        normalized_channels.append(
            {
                "chat_id": chat_id,
                "title": title[:255],
                "username": (raw.get("username") or (known.username if known else None)),
                "invite_link": (raw.get("invite_link") or (known.invite_link if known else None)),
                "required_subscription": bool(raw.get("required_subscription", False)),
                "publish_enabled": bool(raw.get("publish_enabled", True)),
            }
        )

    timestamp = now_utc()
    row.title = payload.title.strip()
    row.kind = payload.kind
    row.ticket_price = payload.ticket_price
    row.allow_extra_tickets = payload.allow_extra_tickets
    row.per_user_limit = payload.per_user_limit
    row.global_ticket_limit = payload.global_ticket_limit
    row.participant_limit = payload.participant_limit
    row.allowed_ranks_json = json_dump(allowed_ranks)
    row.rank_benefits_json = json_dump(benefits)
    row.conditions_json = json_dump(conditions)
    row.post_json = json_dump(payload.post)
    row.start_at = start_at
    row.end_at = end_at
    row.updated_at = timestamp

    if replacing:
        session.query(GiveawayPrize).filter(GiveawayPrize.giveaway_id == row.id).delete(synchronize_session=False)
        session.query(GiveawayChannel).filter(GiveawayChannel.giveaway_id == row.id).delete(synchronize_session=False)
        session.flush()

    for position, prize_text in enumerate(normalized_prizes, start=1):
        session.add(GiveawayPrize(giveaway_id=row.id, position=position, prize_text=prize_text))

    for channel in normalized_channels:
        session.add(GiveawayChannel(giveaway_id=row.id, **channel))


def refund_ticket_amounts(session, giveaway: Giveaway, ticket_rows: list[GiveawayTicket], reason: str, operation_type: str = "giveaway_refund") -> dict[int, int]:
    timestamp = now_utc()
    totals: dict[int, int] = defaultdict(int)
    for ticket in ticket_rows:
        if ticket.refunded_at is None and ticket.paid_amount > 0:
            totals[ticket.telegram_id] += int(ticket.paid_amount)
            ticket.refunded_at = timestamp

    for telegram_id, amount in totals.items():
        user = session.scalar(select(core.User).where(core.User.telegram_id == telegram_id).with_for_update())
        if user is None or core.is_owner(telegram_id):
            continue
        user.balance += amount
        session.add(
            core.Transaction(
                telegram_id=telegram_id,
                amount=amount,
                operation_type=operation_type,
                description=reason,
                created_at=timestamp,
            )
        )
    return dict(totals)


def eligible_pool(session, giveaway: Giveaway) -> tuple[list[GiveawayTicket], list[tuple[GiveawayParticipant, str]]]:
    participants = session.scalars(
        select(GiveawayParticipant).where(
            GiveawayParticipant.giveaway_id == giveaway.id,
            GiveawayParticipant.status == "active",
        ).order_by(GiveawayParticipant.id.asc())
    ).all()

    accepted_ids: set[int] = set()
    rejected: list[tuple[GiveawayParticipant, str]] = []
    locally_eligible: list[GiveawayParticipant] = []

    # First evaluate every condition backed by our own database. This keeps
    # Telegram network calls out of the path for users who already fail locally.
    for participant in participants:
        user = session.get(core.User, participant.telegram_id)
        if user is None:
            rejected.append((participant, "Пользователь удалён"))
            continue
        ok, reason, retryable = eligibility(session, giveaway, user, check_subscriptions=False)
        if retryable:
            raise HTTPException(status_code=503, detail=reason or "Временно не удалось проверить условия")
        if ok:
            locally_eligible.append(participant)
        else:
            rejected.append((participant, reason or "Условия больше не выполнены"))

    required_channels = session.scalars(
        select(GiveawayChannel).where(
            GiveawayChannel.giveaway_id == giveaway.id,
            GiveawayChannel.required_subscription.is_(True),
        ).order_by(GiveawayChannel.id.asc())
    ).all()

    if not required_channels:
        accepted_ids.update(participant.telegram_id for participant in locally_eligible)
    elif locally_eligible:
        checks = [
            (participant.telegram_id, channel.chat_id)
            for participant in locally_eligible
            for channel in required_channels
        ]
        workers = min(24, max(1, len(checks)))
        membership: dict[tuple[int, int], tuple[bool | None, str | None]] = {}
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="nyg-member") as executor:
            futures = {
                executor.submit(telegram_membership, chat_id, telegram_id): (telegram_id, chat_id)
                for telegram_id, chat_id in checks
            }
            for future, key in futures.items():
                try:
                    membership[key] = future.result()
                except Exception:
                    membership[key] = (None, "Не удалось проверить подписку")

        # Preserve channel order so the same first failing condition is reported
        # consistently, even though network checks were parallel.
        for participant in locally_eligible:
            failed_reason = None
            for channel in required_channels:
                member, error = membership[(participant.telegram_id, channel.chat_id)]
                label = f"@{channel.username}" if channel.username else channel.title
                if member is None:
                    raise HTTPException(
                        status_code=503,
                        detail=f"Не удалось проверить подписку на {label}. Попробуйте позже.",
                    )
                if not member:
                    failed_reason = f"Вы не подписаны на {label}"
                    break
            if failed_reason:
                rejected.append((participant, failed_reason))
            else:
                accepted_ids.add(participant.telegram_id)

    tickets = session.scalars(
        select(GiveawayTicket).where(
            GiveawayTicket.giveaway_id == giveaway.id,
            GiveawayTicket.telegram_id.in_(accepted_ids) if accepted_ids else False,
            GiveawayTicket.voided_at.is_(None),
            GiveawayTicket.refunded_at.is_(None),
        ).order_by(GiveawayTicket.ticket_number.asc())
    ).all()
    return list(tickets), rejected


def selection_snapshot(tickets: list[GiveawayTicket]) -> tuple[str, str]:
    payload = [
        {"ticket_number": ticket.ticket_number, "telegram_id": ticket.telegram_id}
        for ticket in tickets
    ]
    raw = json_dump(payload)
    return raw, hashlib.sha256(raw.encode()).hexdigest()


def result_user_dict(session, row: GiveawayResult) -> dict:
    user = session.get(core.User, row.telegram_id)
    return {
        "id": row.id,
        "position": row.position,
        "telegram_id": row.telegram_id,
        "username": user.username if user else None,
        "first_name": user.first_name if user else None,
        "last_name": user.last_name if user else None,
        "ticket_number": row.ticket_number,
        "prize_text": row.prize_text,
        "status": row.status,
        "reason": row.reason,
        "selected_at": norm_dt(row.selected_at).isoformat(),
    }


@router.post("/api/owner/purchases/import")
async def owner_purchase_import(
    payload: PurchaseImportPayload,
    x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data"),
):
    require_owner(x_telegram_init_data)
    lines = [(index, line) for index, line in enumerate(payload.text.splitlines(), start=1) if line.strip()]
    if not lines:
        raise HTTPException(status_code=400, detail="Список покупок пуст")
    if len(lines) > 5000:
        raise HTTPException(status_code=400, detail="За один раз можно импортировать до 5000 покупок")

    with core.SessionLocal() as session:
        parsed = []
        errors = []
        seen_batch = set()
        for line_no, line in lines:
            try:
                item = parse_purchase_line(line, line_no, session)
                if item["fingerprint"] in seen_batch:
                    continue
                seen_batch.add(item["fingerprint"])
                parsed.append(item)
            except ValueError as exc:
                errors.append(str(exc))
        if errors:
            raise HTTPException(status_code=400, detail={"message": "Импорт отменён: исправьте ошибки", "errors": errors[:50], "error_count": len(errors)})

        existing = set(
            session.scalars(select(ShopPurchase.fingerprint).where(ShopPurchase.fingerprint.in_([x["fingerprint"] for x in parsed]))).all()
        ) if parsed else set()
        inserted = []
        timestamp = now_utc()
        with session.begin_nested():
            for item in parsed:
                if item["fingerprint"] in existing:
                    continue
                row = ShopPurchase(**item, created_at=timestamp)
                session.add(row)
                inserted.append(row)
        session.commit()
        return {
            "ok": True,
            "imported": len(inserted),
            "duplicates_skipped": len(parsed) - len(inserted),
            "items": [purchase_dict(row) for row in inserted[-100:]],
        }


@router.post("/api/owner/purchases/add")
async def owner_purchase_add(
    payload: PurchaseCreatePayload,
    x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data"),
):
    require_owner(x_telegram_init_data)
    with core.SessionLocal() as session:
        user = core.find_target_user(session, payload.target)
        if user is None:
            raise HTTPException(status_code=404, detail="Пользователь не найден")
        try:
            amount = parse_amount_kopecks(payload.amount_rub)
            purchased_on = parse_purchase_date(payload.purchased_on)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if purchased_on > now_utc().date():
            raise HTTPException(status_code=400, detail="Дата покупки не может быть в будущем")
        fingerprint = purchase_fingerprint(user.telegram_id, payload.item_name, amount, purchased_on)
        if session.scalar(select(ShopPurchase.id).where(ShopPurchase.fingerprint == fingerprint)):
            if not payload.force_duplicate:
                raise HTTPException(status_code=409, detail="Такая покупка уже существует")
            fingerprint = hashlib.sha256(
                f"{fingerprint}:manual:{secrets.token_hex(16)}".encode()
            ).hexdigest()
        row = ShopPurchase(
            telegram_id=user.telegram_id,
            item_name=payload.item_name.strip(),
            amount_kopecks=amount,
            purchased_on=purchased_on,
            fingerprint=fingerprint,
            created_at=now_utc(),
        )
        session.add(row)
        session.commit()
        session.refresh(row)
        return {"ok": True, "purchase": purchase_dict(row)}


@router.get("/api/owner/purchases")
async def owner_purchases(
    q: str = "",
    x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data"),
):
    require_owner(x_telegram_init_data)
    with core.SessionLocal() as session:
        stmt = select(ShopPurchase, core.User).join(core.User, core.User.telegram_id == ShopPurchase.telegram_id)
        target = q.strip().lstrip("@")
        if target:
            if target.isdigit():
                stmt = stmt.where(core.User.telegram_id == int(target))
            else:
                stmt = stmt.where(func.lower(core.User.username) == target.lower())
        rows = session.execute(stmt.order_by(ShopPurchase.id.desc()).limit(500)).all()
        items = []
        for purchase, user in rows:
            item = purchase_dict(purchase)
            item["username"] = user.username
            item["first_name"] = user.first_name
            items.append(item)
        total = sum(item["amount_kopecks"] for item in items)
        return {"ok": True, "items": items, "count": len(items), "total_kopecks": total}


@router.post("/api/owner/purchases/{purchase_id}/delete")
async def owner_purchase_delete(
    purchase_id: int,
    x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data"),
):
    require_owner(x_telegram_init_data)
    with core.SessionLocal() as session:
        row = session.get(ShopPurchase, purchase_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Покупка не найдена")
        session.delete(row)
        session.commit()
    return {"ok": True, "purchase_id": purchase_id}


@router.get("/api/owner/giveaway-channels")
async def owner_channels(
    x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data"),
):
    require_owner(x_telegram_init_data)
    with core.SessionLocal() as session:
        rows = session.scalars(select(KnownChannel).order_by(KnownChannel.title.asc())).all()
        return {
            "ok": True,
            "channels": [
                {
                    "chat_id": row.chat_id,
                    "title": row.title,
                    "username": row.username,
                    "invite_link": row.invite_link,
                    "bot_status": row.bot_status,
                    "is_available": row.is_available,
                    "added_at": norm_dt(row.added_at).isoformat(),
                    "updated_at": norm_dt(row.updated_at).isoformat(),
                }
                for row in rows
            ],
        }


@router.get("/api/internal/giveaway-channels")
async def internal_channels(
    x_nyan_bot_key: str | None = Header(default=None, alias="X-Nyan-Bot-Key"),
):
    require_bot_key(x_nyan_bot_key)
    with core.SessionLocal() as session:
        rows = session.scalars(
            select(KnownChannel)
            .where(KnownChannel.is_available.is_(True))
            .order_by(KnownChannel.title.asc())
        ).all()
        return {
            "ok": True,
            "channels": [
                {
                    "chat_id": row.chat_id,
                    "title": row.title,
                    "username": row.username,
                    "invite_link": row.invite_link,
                    "bot_status": row.bot_status,
                }
                for row in rows
            ],
        }


@router.post("/api/internal/giveaway-channels/upsert")
async def internal_channel_upsert(
    payload: ChannelUpsertPayload,
    x_nyan_bot_key: str | None = Header(default=None, alias="X-Nyan-Bot-Key"),
):
    require_bot_key(x_nyan_bot_key)
    timestamp = now_utc()
    with core.SessionLocal() as session:
        row = session.get(KnownChannel, payload.chat_id)
        added = row is None
        if row is None:
            row = KnownChannel(
                chat_id=payload.chat_id,
                title=payload.title,
                username=payload.username,
                invite_link=payload.invite_link,
                bot_status=payload.bot_status,
                is_available=payload.is_available,
                added_at=timestamp,
                updated_at=timestamp,
            )
            session.add(row)
        else:
            row.title = payload.title
            row.username = payload.username
            row.invite_link = payload.invite_link
            row.bot_status = payload.bot_status
            row.is_available = payload.is_available
            row.updated_at = timestamp
        session.commit()
    return {"ok": True, "added": added}


@router.post("/api/internal/giveaways")
async def internal_giveaway_create(
    payload: GiveawayCreatePayload,
    x_nyan_bot_key: str | None = Header(default=None, alias="X-Nyan-Bot-Key"),
):
    require_bot_key(x_nyan_bot_key)
    timestamp = now_utc()
    with core.SessionLocal() as session:
        with session.begin():
            row = Giveaway(
                public_id=None,
                title=payload.title.strip(),
                kind=payload.kind,
                status="draft",
                ticket_price=0,
                allow_extra_tickets=True,
                per_user_limit=10,
                global_ticket_limit=None,
                participant_limit=None,
                allowed_ranks_json="[]",
                rank_benefits_json="{}",
                conditions_json="{}",
                post_json="{}",
                start_at=None,
                end_at=None,
                created_at=timestamp,
                updated_at=timestamp,
                started_at=None,
                closed_at=None,
                completed_at=None,
                cancelled_at=None,
            )
            session.add(row)
            session.flush()
            row.public_id = f"NYG-{row.id:06d}"
            apply_giveaway_payload(session, row, payload, replacing=False)
        session.refresh(row)
        return {"ok": True, "giveaway": giveaway_dict(session, row, include_private=True)}


@router.post("/api/internal/giveaways/{public_id}/activate")
async def internal_giveaway_activate(
    public_id: str,
    x_nyan_bot_key: str | None = Header(default=None, alias="X-Nyan-Bot-Key"),
):
    require_bot_key(x_nyan_bot_key)
    with core.SessionLocal() as session:
        with session.begin():
            row = get_giveaway_locked(session, public_id)
            if row.status not in {"draft", "scheduled"}:
                if row.status == "active":
                    return {"ok": True, "status": row.status, "already_active": True}
                raise HTTPException(status_code=409, detail="Этот розыгрыш нельзя запустить")
            timestamp = now_utc()
            start_at = norm_dt(row.start_at)
            if start_at and start_at > timestamp:
                row.status = "scheduled"
                row.updated_at = timestamp
                return {"ok": True, "status": "scheduled"}
            publish_giveaway_locked(session, row)
            row.status = "active"
            row.started_at = row.started_at or timestamp
            row.updated_at = timestamp
            return {"ok": True, "status": "active"}


@router.post("/api/owner/giveaways")
async def owner_giveaway_create(
    payload: GiveawayCreatePayload,
    x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data"),
):
    require_owner(x_telegram_init_data)
    timestamp = now_utc()
    with core.SessionLocal() as session:
        with session.begin():
            row = Giveaway(
                public_id=None,
                title=payload.title.strip(),
                kind=payload.kind,
                status="draft",
                ticket_price=0,
                allow_extra_tickets=True,
                per_user_limit=10,
                global_ticket_limit=None,
                participant_limit=None,
                allowed_ranks_json="[]",
                rank_benefits_json="{}",
                conditions_json="{}",
                post_json="{}",
                start_at=None,
                end_at=None,
                created_at=timestamp,
                updated_at=timestamp,
                started_at=None,
                closed_at=None,
                completed_at=None,
                cancelled_at=None,
            )
            session.add(row)
            session.flush()
            row.public_id = f"NYG-{row.id:06d}"
            apply_giveaway_payload(session, row, payload, replacing=False)
            public_id = row.public_id
        session.refresh(row)
        return {"ok": True, "giveaway": giveaway_dict(session, row, include_private=True)}


@router.post("/api/owner/giveaways/{public_id}/update")
async def owner_giveaway_update(
    public_id: str,
    payload: GiveawayUpdatePayload,
    x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data"),
):
    require_owner(x_telegram_init_data)
    with core.SessionLocal() as session:
        with session.begin():
            row = get_giveaway_locked(session, public_id)
            if row.status in {"completed", "cancelled"}:
                raise HTTPException(status_code=409, detail="Завершённый розыгрыш нельзя редактировать")
            apply_giveaway_payload(session, row, payload, replacing=True)
        return {"ok": True, "giveaway": giveaway_dict(session, row, include_private=True)}


@router.get("/api/owner/giveaways")
async def owner_giveaways(
    status: str | None = None,
    x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data"),
):
    require_owner(x_telegram_init_data)
    with core.SessionLocal() as session:
        stmt = select(Giveaway).order_by(Giveaway.id.desc())
        if status:
            stmt = stmt.where(Giveaway.status == status)
        rows = session.scalars(stmt.limit(300)).all()
        for row in rows:
            refresh_state(session, row)
        session.commit()
        return {"ok": True, "items": [giveaway_dict(session, row, include_private=True) for row in rows]}


@router.get("/api/owner/giveaways/{public_id}")
async def owner_giveaway_detail(
    public_id: str,
    x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data"),
):
    require_owner(x_telegram_init_data)
    with core.SessionLocal() as session:
        row = session.scalar(select(Giveaway).where(Giveaway.public_id == public_id))
        if row is None:
            raise HTTPException(status_code=404, detail="Розыгрыш не найден")
        refresh_state(session, row)
        participants = session.execute(
            select(GiveawayParticipant, core.User)
            .join(core.User, core.User.telegram_id == GiveawayParticipant.telegram_id)
            .where(GiveawayParticipant.giveaway_id == row.id)
            .order_by(GiveawayParticipant.id.asc())
        ).all()
        ticket_rows = session.scalars(active_ticket_query(row.id)).all()
        counts = defaultdict(int)
        paid = defaultdict(int)
        for ticket in ticket_rows:
            counts[ticket.telegram_id] += 1
            paid[ticket.telegram_id] += int(ticket.paid_amount)
        participant_items = []
        rank_distribution = defaultdict(int)
        source_distribution = defaultdict(int)
        for participant, user in participants:
            rank = current_rank(session, user.telegram_id)
            rank_distribution[rank] += 1
            if participant.source_chat_id is not None:
                source_distribution[str(participant.source_chat_id)] += 1
            participant_items.append(
                {
                    "telegram_id": user.telegram_id,
                    "username": user.username,
                    "first_name": user.first_name,
                    "last_name": user.last_name,
                    "status": participant.status,
                    "exclusion_reason": participant.exclusion_reason,
                    "rank": rank,
                    "tickets": counts[user.telegram_id],
                    "paid_lapcoins": paid[user.telegram_id],
                    "joined_at": norm_dt(participant.joined_at).isoformat(),
                    "source_chat_id": participant.source_chat_id,
                }
            )
        results = session.scalars(
            select(GiveawayResult).where(GiveawayResult.giveaway_id == row.id).order_by(GiveawayResult.id.asc())
        ).all()
        session.commit()
        return {
            "ok": True,
            "giveaway": giveaway_dict(session, row, include_private=True),
            "stats": {
                "unique_participants": len(participants),
                "active_participants": sum(1 for participant, _ in participants if participant.status == "active"),
                "tickets": len(ticket_rows),
                "paid_lapcoins": sum(int(ticket.paid_amount) for ticket in ticket_rows),
                "rank_distribution": dict(rank_distribution),
                "source_distribution": dict(source_distribution),
            },
            "participants": participant_items,
            "results": [result_user_dict(session, result) for result in results],
            "result_posts": [
                {
                    "chat_id": item.chat_id,
                    "message_id": item.message_id,
                    "status": item.status,
                    "created_at": norm_dt(item.created_at).isoformat(),
                }
                for item in session.scalars(
                    select(GiveawayResultPost)
                    .where(GiveawayResultPost.giveaway_id == row.id)
                    .order_by(GiveawayResultPost.id.asc())
                ).all()
            ],
        }


@router.post("/api/owner/giveaways/{public_id}/activate")
async def owner_giveaway_activate(
    public_id: str,
    x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data"),
):
    require_owner(x_telegram_init_data)
    with core.SessionLocal() as session:
        with session.begin():
            row = get_giveaway_locked(session, public_id)
            if row.status not in {"draft", "scheduled", "paused"}:
                raise HTTPException(status_code=409, detail="Этот розыгрыш нельзя запустить")
            timestamp = now_utc()
            if row.start_at and norm_dt(row.start_at) > timestamp:
                row.status = "scheduled"
            else:
                row.status = "active"
                if row.started_at is None:
                    row.started_at = timestamp
            row.updated_at = timestamp
            refresh_state(session, row)
            status = row.status
    return {"ok": True, "status": status}


@router.post("/api/owner/giveaways/{public_id}/pause")
async def owner_giveaway_pause(
    public_id: str,
    x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data"),
):
    require_owner(x_telegram_init_data)
    with core.SessionLocal() as session:
        with session.begin():
            row = get_giveaway_locked(session, public_id)
            refresh_state(session, row)
            if row.status != "active":
                raise HTTPException(status_code=409, detail="На паузу можно поставить только активный розыгрыш")
            row.status = "paused"
            row.updated_at = now_utc()
    return {"ok": True, "status": "paused"}


@router.post("/api/owner/giveaways/{public_id}/resume")
async def owner_giveaway_resume(
    public_id: str,
    x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data"),
):
    require_owner(x_telegram_init_data)
    with core.SessionLocal() as session:
        with session.begin():
            row = get_giveaway_locked(session, public_id)
            if row.status != "paused":
                raise HTTPException(status_code=409, detail="Розыгрыш не находится на паузе")
            row.status = "active"
            row.updated_at = now_utc()
            refresh_state(session, row)
            status = row.status
    return {"ok": True, "status": status}


@router.post("/api/owner/giveaways/{public_id}/close")
async def owner_giveaway_close(
    public_id: str,
    x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data"),
):
    require_owner(x_telegram_init_data)
    with core.SessionLocal() as session:
        with session.begin():
            row = get_giveaway_locked(session, public_id)
            if row.status not in {"active", "paused", "scheduled"}:
                raise HTTPException(status_code=409, detail="Этот розыгрыш нельзя завершить сейчас")
            row.status = "awaiting_results"
            row.closed_at = now_utc()
            row.updated_at = now_utc()
            sync_giveaway_buttons(session, row, closed=True)
    return {"ok": True, "status": "awaiting_results"}


@router.post("/api/owner/giveaways/{public_id}/cancel")
async def owner_giveaway_cancel(
    public_id: str,
    x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data"),
):
    require_owner(x_telegram_init_data)
    with core.SessionLocal() as session:
        with session.begin():
            row = get_giveaway_locked(session, public_id)
            if row.status == "cancelled":
                return {"ok": True, "status": "cancelled", "already_cancelled": True}
            if row.status == "completed":
                raise HTTPException(status_code=409, detail="Завершённый розыгрыш нельзя отменить")
            tickets = session.scalars(
                select(GiveawayTicket).where(
                    GiveawayTicket.giveaway_id == row.id,
                    GiveawayTicket.paid_amount > 0,
                    GiveawayTicket.refunded_at.is_(None),
                )
            ).all()
            refunded = refund_ticket_amounts(
                session,
                row,
                list(tickets),
                f"Возврат за отменённый розыгрыш {row.public_id}",
            )
            timestamp = now_utc()
            participants = session.scalars(
                select(GiveawayParticipant).where(GiveawayParticipant.giveaway_id == row.id)
            ).all()
            for participant in participants:
                participant.status = "cancelled"
                participant.updated_at = timestamp
            row.status = "cancelled"
            row.cancelled_at = timestamp
            row.updated_at = timestamp
            sync_giveaway_buttons(session, row, closed=True)
        return {"ok": True, "status": "cancelled", "refunded": refunded}


@router.post("/api/owner/giveaways/{public_id}/participants/adjust")
async def owner_participant_adjust(
    public_id: str,
    payload: ParticipantAdjustPayload,
    x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data"),
):
    require_owner(x_telegram_init_data)
    if payload.delta == 0:
        raise HTTPException(status_code=400, detail="Изменение билетов не может быть 0")
    with core.SessionLocal() as session:
        with session.begin():
            giveaway = get_giveaway_locked(session, public_id)
            if giveaway.status in {"completed", "cancelled"}:
                raise HTTPException(status_code=409, detail="Розыгрыш уже завершён")
            user = core.find_target_user(session, payload.target, lock=True)
            if user is None:
                raise HTTPException(status_code=404, detail="Пользователь не найден")
            participant = get_or_create_participant(session, giveaway, user, payload.source_chat_id)
            current = ticket_count(session, giveaway.id, user.telegram_id)
            if payload.delta > 0:
                limit, _ = user_ticket_limit(session, giveaway, user.telegram_id)
                if current + payload.delta > limit:
                    raise HTTPException(status_code=409, detail=f"Лимит пользователя: {limit}")
                if giveaway.global_ticket_limit is not None and ticket_count(session, giveaway.id) + payload.delta > giveaway.global_ticket_limit:
                    raise HTTPException(status_code=409, detail="Будет превышен общий лимит билетов")
                numbers = add_ticket_rows(session, giveaway, participant, payload.delta, "manual", 0, None)
                return {"ok": True, "tickets": current + payload.delta, "ticket_numbers": numbers}
            remove_count = abs(payload.delta)
            tickets = session.scalars(
                active_ticket_query(giveaway.id, user.telegram_id).order_by(GiveawayTicket.ticket_number.desc()).limit(remove_count)
            ).all()
            if len(tickets) < remove_count:
                raise HTTPException(status_code=409, detail="У пользователя недостаточно билетов")
            timestamp = now_utc()
            for ticket in tickets:
                ticket.voided_at = timestamp
                ticket.void_reason = payload.reason or "Удалено владельцем"
            refunded = {}
            if payload.refund_removed:
                refunded = refund_ticket_amounts(
                    session,
                    giveaway,
                    list(tickets),
                    f"Возврат за удалённые билеты {giveaway.public_id}",
                    "giveaway_manual_refund",
                )
            return {"ok": True, "tickets": current - remove_count, "refunded": refunded}


@router.post("/api/owner/giveaways/{public_id}/participants/remove")
async def owner_participant_remove(
    public_id: str,
    payload: ParticipantRemovePayload,
    x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data"),
):
    require_owner(x_telegram_init_data)
    with core.SessionLocal() as session:
        with session.begin():
            giveaway = get_giveaway_locked(session, public_id)
            user = core.find_target_user(session, payload.target, lock=True)
            if user is None:
                raise HTTPException(status_code=404, detail="Пользователь не найден")
            participant = session.scalar(
                select(GiveawayParticipant).where(
                    GiveawayParticipant.giveaway_id == giveaway.id,
                    GiveawayParticipant.telegram_id == user.telegram_id,
                ).with_for_update()
            )
            if participant is None:
                raise HTTPException(status_code=404, detail="Пользователь не участвует")
            tickets = session.scalars(active_ticket_query(giveaway.id, user.telegram_id)).all()
            timestamp = now_utc()
            for ticket in tickets:
                ticket.voided_at = timestamp
                ticket.void_reason = payload.reason
            refunded = {}
            if payload.refund_paid:
                refunded = refund_ticket_amounts(
                    session,
                    giveaway,
                    list(tickets),
                    f"Возврат после исключения из {giveaway.public_id}",
                    "giveaway_manual_refund",
                )
            participant.status = "excluded"
            participant.exclusion_reason = payload.reason
            participant.updated_at = timestamp
            return {"ok": True, "refunded": refunded}


@router.post("/api/owner/giveaways/{public_id}/participants/refund")
async def owner_participant_refund(
    public_id: str,
    payload: ManualRefundPayload,
    x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data"),
):
    require_owner(x_telegram_init_data)
    with core.SessionLocal() as session:
        with session.begin():
            giveaway = get_giveaway_locked(session, public_id)
            user = core.find_target_user(session, payload.target, lock=True)
            if user is None:
                raise HTTPException(status_code=404, detail="Пользователь не найден")
            if core.is_owner(user.telegram_id):
                raise HTTPException(status_code=400, detail="У владельца бесконечный баланс")
            user.balance += payload.amount
            session.add(
                core.Transaction(
                    telegram_id=user.telegram_id,
                    amount=payload.amount,
                    operation_type="giveaway_manual_refund",
                    description=f"{payload.reason} · {giveaway.public_id}",
                    created_at=now_utc(),
                )
            )
            balance = user.balance
    return {"ok": True, "amount": payload.amount, "balance": balance}


@router.post("/api/owner/giveaways/{public_id}/draw")
async def owner_giveaway_draw(
    public_id: str,
    x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data"),
):
    require_owner(x_telegram_init_data)
    with core.SessionLocal() as session:
        with session.begin():
            giveaway = get_giveaway_locked(session, public_id)
            refresh_state(session, giveaway)
            if giveaway.status != "awaiting_results":
                raise HTTPException(status_code=409, detail="Сначала завершите приём участников")
            active_results = session.scalar(
                select(func.count()).select_from(GiveawayResult).where(
                    GiveawayResult.giveaway_id == giveaway.id,
                    GiveawayResult.status == "active",
                )
            ) or 0
            if active_results:
                raise HTTPException(status_code=409, detail="Победители уже выбраны")

            prizes = session.scalars(
                select(GiveawayPrize).where(GiveawayPrize.giveaway_id == giveaway.id).order_by(GiveawayPrize.position.asc())
            ).all()
            if not prizes:
                raise HTTPException(status_code=409, detail="В розыгрыше нет призовых мест")

            pool, rejected = eligible_pool(session, giveaway)
            for participant, reason in rejected:
                participant.status = "excluded"
                participant.exclusion_reason = reason
                participant.updated_at = now_utc()

            unique_people = {ticket.telegram_id for ticket in pool}
            if len(unique_people) < len(prizes):
                raise HTTPException(
                    status_code=409,
                    detail=f"Допущено {len(unique_people)} участников, призовых мест {len(prizes)}. Решите вручную.",
                )

            snapshot_raw, snapshot_hash = selection_snapshot(pool)
            event = GiveawaySelectionEvent(
                giveaway_id=giveaway.id,
                kind="full",
                snapshot_json=snapshot_raw,
                snapshot_sha256=snapshot_hash,
                eligible_participants=len(unique_people),
                eligible_tickets=len(pool),
                reason=None,
                created_at=now_utc(),
            )
            session.add(event)
            session.flush()

            available = list(pool)
            selected = []
            for prize in prizes:
                ticket = secrets.choice(available)
                result = GiveawayResult(
                    giveaway_id=giveaway.id,
                    selection_event_id=event.id,
                    position=prize.position,
                    telegram_id=ticket.telegram_id,
                    ticket_number=ticket.ticket_number,
                    prize_text=prize.prize_text,
                    status="active",
                    reason=None,
                    selected_at=now_utc(),
                )
                session.add(result)
                session.flush()
                selected.append(result)
                available = [item for item in available if item.telegram_id != ticket.telegram_id]

            return {
                "ok": True,
                "snapshot_sha256": snapshot_hash,
                "eligible_participants": len(unique_people),
                "eligible_tickets": len(pool),
                "results": [result_user_dict(session, result) for result in selected],
            }


@router.post("/api/owner/giveaways/{public_id}/results/annul")
async def owner_results_annul(
    public_id: str,
    payload: ReasonPayload,
    x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data"),
):
    require_owner(x_telegram_init_data)
    with core.SessionLocal() as session:
        with session.begin():
            giveaway = get_giveaway_locked(session, public_id)
            rows = session.scalars(
                select(GiveawayResult).where(
                    GiveawayResult.giveaway_id == giveaway.id,
                    GiveawayResult.status == "active",
                ).with_for_update()
            ).all()
            if not rows:
                raise HTTPException(status_code=409, detail="Нет активных результатов")
            for row in rows:
                row.status = "annulled"
                row.reason = payload.reason
            giveaway.status = "awaiting_results"
            giveaway.completed_at = None
            giveaway.updated_at = now_utc()
    return {"ok": True, "annulled": len(rows)}


@router.post("/api/owner/giveaways/{public_id}/results/{position}/replace")
async def owner_result_replace(
    public_id: str,
    position: int,
    payload: ReasonPayload,
    x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data"),
):
    require_owner(x_telegram_init_data)
    with core.SessionLocal() as session:
        with session.begin():
            giveaway = get_giveaway_locked(session, public_id)
            old = session.scalar(
                select(GiveawayResult).where(
                    GiveawayResult.giveaway_id == giveaway.id,
                    GiveawayResult.position == position,
                    GiveawayResult.status == "active",
                ).order_by(GiveawayResult.id.desc()).with_for_update()
            )
            if old is None:
                raise HTTPException(status_code=404, detail="Активный победитель этого места не найден")

            pool, rejected = eligible_pool(session, giveaway)
            for participant, reason in rejected:
                participant.status = "excluded"
                participant.exclusion_reason = reason
                participant.updated_at = now_utc()

            current_winner_ids = set(
                session.scalars(
                    select(GiveawayResult.telegram_id).where(
                        GiveawayResult.giveaway_id == giveaway.id,
                        GiveawayResult.status == "active",
                    )
                ).all()
            )
            historically_replaced = set(
                session.scalars(
                    select(GiveawayResult.telegram_id).where(
                        GiveawayResult.giveaway_id == giveaway.id,
                        GiveawayResult.status == "replaced",
                    )
                ).all()
            )
            excluded = current_winner_ids | historically_replaced | {old.telegram_id}
            available = [ticket for ticket in pool if ticket.telegram_id not in excluded]
            if not available:
                raise HTTPException(status_code=409, detail="Нет подходящих участников для перевыбора")

            snapshot_raw, snapshot_hash = selection_snapshot(available)
            event = GiveawaySelectionEvent(
                giveaway_id=giveaway.id,
                kind="replacement",
                snapshot_json=snapshot_raw,
                snapshot_sha256=snapshot_hash,
                eligible_participants=len({ticket.telegram_id for ticket in available}),
                eligible_tickets=len(available),
                reason=payload.reason,
                created_at=now_utc(),
            )
            session.add(event)
            session.flush()

            ticket = secrets.choice(available)
            old.status = "replaced"
            old.reason = payload.reason
            new_result = GiveawayResult(
                giveaway_id=giveaway.id,
                selection_event_id=event.id,
                position=position,
                telegram_id=ticket.telegram_id,
                ticket_number=ticket.ticket_number,
                prize_text=old.prize_text,
                status="active",
                reason=None,
                selected_at=now_utc(),
            )
            session.add(new_result)
            session.flush()
            return {
                "ok": True,
                "snapshot_sha256": snapshot_hash,
                "result": result_user_dict(session, new_result),
            }


@router.post("/api/owner/giveaways/{public_id}/complete")
async def owner_giveaway_complete(
    public_id: str,
    x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data"),
):
    require_owner(x_telegram_init_data)
    with core.SessionLocal() as session:
        with session.begin():
            giveaway = get_giveaway_locked(session, public_id)
            active_results = session.scalar(
                select(func.count()).select_from(GiveawayResult).where(
                    GiveawayResult.giveaway_id == giveaway.id,
                    GiveawayResult.status == "active",
                )
            ) or 0
            prizes = session.scalar(
                select(func.count()).select_from(GiveawayPrize).where(GiveawayPrize.giveaway_id == giveaway.id)
            ) or 0
            if int(active_results) != int(prizes) or int(prizes) == 0:
                raise HTTPException(status_code=409, detail="Сначала сформируйте полный список победителей")
            giveaway.status = "completed"
            giveaway.completed_at = now_utc()
            giveaway.updated_at = now_utc()
            sync_giveaway_buttons(session, giveaway, closed=True)
    return {"ok": True, "status": "completed"}


@router.get("/api/giveaways/{public_id}")
async def giveaway_public_detail(
    public_id: str,
    x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data"),
):
    tg = require_user(x_telegram_init_data)
    with core.SessionLocal() as session:
        row = session.scalar(select(Giveaway).where(Giveaway.public_id == public_id))
        if row is None:
            raise HTTPException(status_code=404, detail="Розыгрыш не найден")
        refresh_state(session, row)
        participant = session.scalar(
            select(GiveawayParticipant).where(
                GiveawayParticipant.giveaway_id == row.id,
                GiveawayParticipant.telegram_id == tg["id"],
            )
        )
        tickets = ticket_count(session, row.id, tg["id"])
        user = session.get(core.User, tg["id"])
        rank = current_rank(session, tg["id"])
        limit, config = user_ticket_limit(session, row, tg["id"])
        price = user_ticket_price(session, row, tg["id"])
        won = session.scalars(
            select(GiveawayResult).where(
                GiveawayResult.giveaway_id == row.id,
                GiveawayResult.telegram_id == tg["id"],
                GiveawayResult.status == "active",
            )
        ).all()
        session.commit()
        return {
            "ok": True,
            "giveaway": giveaway_dict(session, row, include_private=False),
            "me": {
                "rank": rank,
                "tickets": tickets,
                "limit": limit,
                "ticket_price": price,
                "participant_status": participant.status if participant else None,
                "is_participating": bool(participant and participant.status == "active" and tickets > 0),
                "balance": None if core.is_owner(tg["id"]) else (user.balance if user else 0),
                "unlimited_balance": core.is_owner(tg["id"]),
                "rank_benefit": config,
                "wins": [result_user_dict(session, item) for item in won],
            },
        }


@router.post("/api/giveaways/{public_id}/join")
async def giveaway_join(
    public_id: str,
    x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data"),
):
    tg = require_user(x_telegram_init_data)
    try:
        with core.SessionLocal() as session:
            with session.begin():
                giveaway = get_giveaway_locked(session, public_id)
                user = session.scalar(select(core.User).where(core.User.telegram_id == tg["id"]).with_for_update())
                if user is None:
                    raise HTTPException(status_code=404, detail="Пользователь не найден")
                return join_impl(session, giveaway, user)
    except IntegrityError as exc:
        raise HTTPException(status_code=409, detail="Участие уже зарегистрировано. Обновите розыгрыш.") from exc


@router.post("/api/giveaways/{public_id}/tickets/purchase")
async def giveaway_purchase_tickets(
    public_id: str,
    payload: TicketPurchasePayload,
    x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data"),
):
    tg = require_user(x_telegram_init_data)
    try:
        with core.SessionLocal() as session:
            with session.begin():
                giveaway = get_giveaway_locked(session, public_id)
                user = session.scalar(select(core.User).where(core.User.telegram_id == tg["id"]).with_for_update())
                if user is None:
                    raise HTTPException(status_code=404, detail="Пользователь не найден")
                return purchase_tickets_impl(session, giveaway, user, payload.count, payload.request_key)
    except IntegrityError as exc:
        raise HTTPException(status_code=409, detail="Запрос покупки уже обрабатывается. Обновите страницу.") from exc


@router.get("/api/my-giveaways")
async def my_giveaways(
    x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data"),
):
    tg = require_user(x_telegram_init_data)
    with core.SessionLocal() as session:
        rows = session.execute(
            select(GiveawayParticipant, Giveaway)
            .join(Giveaway, Giveaway.id == GiveawayParticipant.giveaway_id)
            .where(GiveawayParticipant.telegram_id == tg["id"])
            .order_by(GiveawayParticipant.id.desc())
            .limit(200)
        ).all()
        items = []
        for participant, giveaway in rows:
            refresh_state(session, giveaway)
            wins = session.scalars(
                select(GiveawayResult).where(
                    GiveawayResult.giveaway_id == giveaway.id,
                    GiveawayResult.telegram_id == tg["id"],
                    GiveawayResult.status == "active",
                )
            ).all()
            items.append(
                {
                    "giveaway": giveaway_dict(session, giveaway, include_private=False),
                    "tickets": ticket_count(session, giveaway.id, tg["id"]),
                    "participant_status": participant.status,
                    "exclusion_reason": participant.exclusion_reason,
                    "wins": [result_user_dict(session, item) for item in wins],
                }
            )
        session.commit()
        return {"ok": True, "items": items}


@router.post("/api/internal/giveaways/{public_id}/join")
async def internal_giveaway_join(
    public_id: str,
    payload: BotUserPayload,
    x_nyan_bot_key: str | None = Header(default=None, alias="X-Nyan-Bot-Key"),
):
    require_bot_key(x_nyan_bot_key)
    try:
        with core.SessionLocal() as session:
            with session.begin():
                giveaway = get_giveaway_locked(session, public_id)
                user = ensure_user_from_bot(session, payload)
                return join_impl(session, giveaway, user, payload.source_chat_id)
    except IntegrityError as exc:
        raise HTTPException(status_code=409, detail="Участие уже зарегистрировано") from exc


@router.get("/api/internal/giveaways/{public_id}")
async def internal_giveaway_detail(
    public_id: str,
    x_nyan_bot_key: str | None = Header(default=None, alias="X-Nyan-Bot-Key"),
):
    require_bot_key(x_nyan_bot_key)
    with core.SessionLocal() as session:
        giveaway = session.scalar(select(Giveaway).where(Giveaway.public_id == public_id))
        if giveaway is None:
            raise HTTPException(status_code=404, detail="Розыгрыш не найден")
        refresh_state(session, giveaway)
        session.commit()
        return {"ok": True, "giveaway": giveaway_dict(session, giveaway, include_private=True)}


@router.post("/api/internal/giveaways/{public_id}/replace-post")
async def internal_replace_post(
    public_id: str,
    payload: ReplacePostPayload,
    x_nyan_bot_key: str | None = Header(default=None, alias="X-Nyan-Bot-Key"),
):
    require_bot_key(x_nyan_bot_key)
    with core.SessionLocal() as session:
        with session.begin():
            giveaway = get_giveaway_locked(session, public_id)
            if giveaway.status == "cancelled":
                raise HTTPException(status_code=409, detail="Отменённый розыгрыш нельзя редактировать")
            replace_giveaway_posts_locked(
                session,
                giveaway,
                payload.source_chat_id,
                [int(value) for value in payload.message_ids],
            )
    return {"ok": True, "public_id": public_id}


@router.post("/api/internal/giveaways/{public_id}/results/publish")
async def internal_publish_results(
    public_id: str,
    payload: ResultPublishPayload,
    x_nyan_bot_key: str | None = Header(default=None, alias="X-Nyan-Bot-Key"),
):
    require_bot_key(x_nyan_bot_key)
    with core.SessionLocal() as session:
        with session.begin():
            giveaway = get_giveaway_locked(session, public_id)
            rows = publish_results_locked(
                session,
                giveaway,
                payload.source_chat_id,
                payload.source_message_id,
                [int(value) for value in payload.channel_ids],
            )
            if giveaway.status != "completed":
                giveaway.status = "completed"
                giveaway.completed_at = now_utc()
                giveaway.updated_at = now_utc()
                sync_giveaway_buttons(session, giveaway, closed=True)
            response = [
                {"chat_id": row.chat_id, "message_id": row.message_id}
                for row in rows
            ]
    return {"ok": True, "published": response, "status": "completed"}


@router.post("/api/internal/giveaways/{public_id}/posts")
async def internal_register_post(
    public_id: str,
    payload: PostRegistrationPayload,
    x_nyan_bot_key: str | None = Header(default=None, alias="X-Nyan-Bot-Key"),
):
    require_bot_key(x_nyan_bot_key)
    with core.SessionLocal() as session:
        giveaway = session.scalar(select(Giveaway).where(Giveaway.public_id == public_id))
        if giveaway is None:
            raise HTTPException(status_code=404, detail="Розыгрыш не найден")
        existing = session.scalar(
            select(GiveawayPost).where(
                GiveawayPost.giveaway_id == giveaway.id,
                GiveawayPost.chat_id == payload.chat_id,
                GiveawayPost.message_id == payload.message_id,
            )
        )
        timestamp = now_utc()
        if existing is None:
            existing = GiveawayPost(
                giveaway_id=giveaway.id,
                chat_id=payload.chat_id,
                message_id=payload.message_id,
                status=payload.status,
                last_error=None,
                created_at=timestamp,
                updated_at=timestamp,
            )
            session.add(existing)
        else:
            existing.status = payload.status
            existing.updated_at = timestamp
        session.commit()
    return {"ok": True}


def sweep_giveaway_states() -> None:
    timestamp = now_utc()
    notifications: list[str] = []

    # Scheduled giveaways are processed independently, so one Telegram failure
    # cannot roll back or block every other giveaway that is due.
    with core.SessionLocal() as session:
        due_ids = list(
            session.scalars(
                select(Giveaway.id).where(
                    Giveaway.status == "scheduled",
                    Giveaway.start_at.is_not(None),
                    Giveaway.start_at <= timestamp,
                ).order_by(Giveaway.id.asc())
            ).all()
        )

    for giveaway_id in due_ids:
        try:
            with core.SessionLocal() as session:
                with session.begin():
                    row = session.scalar(
                        select(Giveaway)
                        .where(Giveaway.id == giveaway_id)
                        .with_for_update()
                    )
                    if row is None or row.status != "scheduled":
                        continue
                    publish_giveaway_locked(session, row)
                    row.status = "active"
                    row.started_at = row.started_at or timestamp
                    row.updated_at = timestamp
            notifications.append(f"Розыгрыш {row.public_id} опубликован и запущен.")
        except Exception as exc:
            notifications.append(f"Не удалось запустить запланированный розыгрыш #{giveaway_id}: {exc}")

    try:
        with core.SessionLocal() as session:
            with session.begin():
                rows = session.scalars(
                    select(Giveaway)
                    .where(Giveaway.status == "active")
                    .order_by(Giveaway.id.asc())
                    .with_for_update()
                ).all()
                for row in rows:
                    before = row.status
                    refresh_state(session, row)
                    if before != row.status and row.status == "awaiting_results":
                        sync_giveaway_buttons(session, row, closed=True)
                        notifications.append(
                            f"Розыгрыш {row.public_id} завершил приём участников. "
                            "Итоги ждут вашего подтверждения."
                        )
    except Exception as exc:
        print(f"Nyan giveaway active-state sweep failed: {exc}")

    for message in notifications:
        send_telegram_message(core.OWNER_TELEGRAM_ID, message)


async def _state_loop() -> None:
    while True:
        await asyncio.to_thread(sweep_giveaway_states)
        await asyncio.sleep(30)


async def _start_state_loop() -> None:
    global _STATE_TASK
    if _STATE_TASK is None or _STATE_TASK.done():
        _STATE_TASK = asyncio.create_task(_state_loop(), name="nyan-giveaway-state-loop")


def register_giveaways(app) -> None:
    global _REGISTERED
    if _REGISTERED:
        return
    core.Base.metadata.create_all(core.engine)
    app.include_router(router)
    app.add_event_handler("startup", _start_state_loop)
    _REGISTERED = True
