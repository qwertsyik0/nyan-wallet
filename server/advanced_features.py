from __future__ import annotations

import csv
import hashlib
import io
import zipfile
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, event, func, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from server import backend_app as core
from server.extended_features import Reward, SpendRequest, audit, send_telegram_message

router = APIRouter()
_REGISTERED = False

DEFAULTS = {
    "cashback_percent": 5,
    "first_purchase_bonus": 25,
    "review_bonus": 10,
    "activity_min": 5,
    "activity_max": 100,
    "referral_inviter_bonus": 25,
    "referral_invitee_bonus": 25,
    "level_regular": 500,
    "level_vip": 2000,
    "level_legend": 5000,
}


def now() -> datetime:
    return datetime.now(timezone.utc)


def norm_dt(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


class RewardMeta(core.Base):
    __tablename__ = "reward_meta"
    reward_id: Mapped[int] = mapped_column(Integer, ForeignKey("reward_catalog.id", ondelete="CASCADE"), primary_key=True)
    image_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    stock_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    available_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class RequestMeta(core.Base):
    __tablename__ = "spend_request_meta"
    request_id: Mapped[int] = mapped_column(Integer, ForeignKey("spend_requests.id", ondelete="CASCADE"), primary_key=True)
    owner_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class WalletNotification(core.Base):
    __tablename__ = "wallet_notifications"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.telegram_id", ondelete="CASCADE"), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    is_read: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)


class ReferralCode(core.Base):
    __tablename__ = "referral_codes"
    telegram_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.telegram_id", ondelete="CASCADE"), primary_key=True)
    code: Mapped[str] = mapped_column(String(24), nullable=False, unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Referral(core.Base):
    __tablename__ = "referrals"
    __table_args__ = (UniqueConstraint("invited_id", name="uq_referral_invited"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    inviter_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.telegram_id", ondelete="CASCADE"), nullable=False, index=True)
    invited_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.telegram_id", ondelete="CASCADE"), nullable=False, index=True)
    inviter_reward: Mapped[int] = mapped_column(Integer, nullable=False)
    invited_reward: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class WalletEvent(core.Base):
    __tablename__ = "wallet_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    badge: Mapped[str | None] = mapped_column(String(60), nullable=True)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class EconomySetting(core.Base):
    __tablename__ = "economy_settings"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class RewardPayload(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    cost: int = Field(ge=1, le=100_000_000)
    image_url: str | None = Field(default=None, max_length=1000)
    stock_limit: int | None = Field(default=None, ge=1, le=1_000_000)
    available_until: datetime | None = None
    sort_order: int = Field(default=0, ge=-1_000_000, le=1_000_000)


class RequestStatusPayload(BaseModel):
    status: str = Field(min_length=3, max_length=20)
    comment: str | None = Field(default=None, max_length=500)


class ReferralPayload(BaseModel):
    code: str = Field(min_length=4, max_length=24)


class MassGrantPayload(BaseModel):
    targets: list[str] = Field(min_length=1, max_length=100)
    amount: int = Field(ge=1, le=1_000_000)
    reason: str | None = Field(default=None, max_length=200)


class EventPayload(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    badge: str | None = Field(default=None, max_length=60)
    starts_at: datetime
    ends_at: datetime


class EconomyPayload(BaseModel):
    values: dict[str, int]


def settings(session: Session) -> dict[str, int]:
    values = dict(DEFAULTS)
    for row in session.scalars(select(EconomySetting)).all():
        values[row.key] = int(row.value)
    return values


def ensure_settings() -> None:
    with core.SessionLocal() as session:
        present = {row.key for row in session.scalars(select(EconomySetting)).all()}
        timestamp = now()
        for key, value in DEFAULTS.items():
            if key not in present:
                session.add(EconomySetting(key=key, value=value, updated_at=timestamp))
        session.commit()


def notify(session: Session, telegram_id: int, kind: str, title: str, body: str) -> None:
    session.add(WalletNotification(telegram_id=telegram_id, kind=kind, title=title, body=body, is_read=False, created_at=now()))


def tx_notification(mapper, connection, target: core.Transaction) -> None:
    amount = int(target.amount)
    desc = target.description or ""
    data = {
        "owner_grant": ("Начисление лапкоинов", f"+{amount} 🐾"),
        "owner_debit": ("Списание лапкоинов", f"Списано {abs(amount)} 🐾"),
        "promo": ("Промокод активирован", f"+{amount} 🐾"),
        "reward_request": ("Заявка создана", desc or "Создана заявка на приз"),
        "reward_refund": ("Возврат лапкоинов", f"+{amount} 🐾 возвращено"),
        "referral_inviter": ("Реферальный бонус", f"+{amount} 🐾 за приглашённого пользователя"),
        "referral_invitee": ("Реферальный бонус", f"+{amount} 🐾 за приглашение"),
        "mass_grant": ("Начисление лапкоинов", f"+{amount} 🐾"),
    }.get(target.operation_type)
    if not data:
        return
    title, body = data
    if desc and target.operation_type not in {"reward_request"}:
        body += f"\n{desc}"
    connection.execute(WalletNotification.__table__.insert().values(telegram_id=target.telegram_id, kind=target.operation_type, title=title, body=body, is_read=False, created_at=target.created_at or now()))


def reward_guard(session: Session, flush_context, instances) -> None:
    timestamp = now()
    for obj in list(session.new):
        if not isinstance(obj, SpendRequest):
            continue
        meta = session.get(RewardMeta, obj.reward_id)
        if not meta:
            continue
        until = norm_dt(meta.available_until)
        if until and until <= timestamp:
            raise HTTPException(status_code=409, detail="Срок доступности награды закончился")
        if meta.stock_limit is not None:
            used = session.scalar(select(func.count()).select_from(SpendRequest).where(SpendRequest.reward_id == obj.reward_id, SpendRequest.status != "cancelled")) or 0
            if int(used) >= meta.stock_limit:
                raise HTTPException(status_code=409, detail="Лимит этой награды закончился")


def ensure_ref_code(session: Session, telegram_id: int) -> ReferralCode:
    row = session.get(ReferralCode, telegram_id)
    if row:
        return row
    digest = hashlib.blake2s(f"{telegram_id}:{core.BOT_TOKEN}".encode(), digest_size=5).hexdigest().upper()
    row = ReferralCode(telegram_id=telegram_id, code=f"NYAN{digest}", created_at=now())
    session.add(row)
    session.flush()
    return row


def level_data(earned: int, cfg: dict[str, int]) -> dict:
    levels = [("Новичок", 0), ("Постоянник", cfg["level_regular"]), ("VIP", cfg["level_vip"]), ("Легенда", cfg["level_legend"])]
    current = levels[0]
    next_level = None
    for item in levels:
        if earned >= item[1]:
            current = item
        elif next_level is None:
            next_level = item
            break
    if not next_level:
        return {"name": current[0], "lifetime_earned": earned, "progress": 100, "next_name": None, "remaining": 0}
    span = max(1, next_level[1] - current[1])
    progress = min(100, max(0, round((earned - current[1]) * 100 / span)))
    return {"name": current[0], "lifetime_earned": earned, "progress": progress, "next_name": next_level[0], "remaining": max(0, next_level[1] - earned)}


def catalog_item(session: Session, reward: Reward) -> dict:
    meta = session.get(RewardMeta, reward.id)
    used = session.scalar(select(func.count()).select_from(SpendRequest).where(SpendRequest.reward_id == reward.id, SpendRequest.status != "cancelled")) or 0
    limit = meta.stock_limit if meta else None
    remaining = None if limit is None else max(0, limit - int(used))
    until = norm_dt(meta.available_until) if meta else None
    available = reward.is_active and (not until or until > now()) and (remaining is None or remaining > 0)
    return {"id": reward.id, "title": reward.title, "description": reward.description, "cost": reward.cost, "is_active": reward.is_active, "sort_order": reward.sort_order, "image_url": meta.image_url if meta else None, "stock_limit": limit, "stock_used": int(used), "stock_remaining": remaining, "available_until": until.isoformat() if until else None, "available": available}


@router.get("/api/catalog")
async def catalog(x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data")):
    tg = core.verify_init_data(x_telegram_init_data or "")
    core.get_or_create_user(tg)
    with core.SessionLocal() as session:
        rows = session.scalars(select(Reward).order_by(Reward.sort_order.asc(), Reward.id.asc())).all()
        items = [catalog_item(session, row) for row in rows]
        return {"ok": True, "rewards": [item for item in items if item["available"]]}


@router.get("/api/profile")
async def profile(x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data")):
    tg = core.verify_init_data(x_telegram_init_data or "")
    core.get_or_create_user(tg)
    with core.SessionLocal() as session:
        code = ensure_ref_code(session, tg["id"])
        cfg = settings(session)
        user = session.scalar(select(core.User).where(core.User.telegram_id == tg["id"]))
        earned = session.scalar(
            select(func.coalesce(func.sum(core.Transaction.amount), 0)).where(
                core.Transaction.telegram_id == tg["id"],
                core.Transaction.amount > 0,
            )
        ) or 0
        spent_raw = session.scalar(
            select(func.coalesce(func.sum(core.Transaction.amount), 0)).where(
                core.Transaction.telegram_id == tg["id"],
                core.Transaction.amount < 0,
            )
        ) or 0
        invited = session.scalar(select(func.count()).select_from(Referral).where(Referral.inviter_id == tg["id"])) or 0
        fulfilled = session.scalar(
            select(func.count()).select_from(SpendRequest).where(
                SpendRequest.telegram_id == tg["id"],
                SpendRequest.status == "fulfilled",
            )
        ) or 0
        promo_uses = session.scalar(
            select(func.count()).select_from(core.PromoRedemption).where(
                core.PromoRedemption.telegram_id == tg["id"]
            )
        ) or 0
        used = session.scalar(select(Referral.id).where(Referral.invited_id == tg["id"])) is not None
        session.commit()
        return {
            "ok": True,
            "level": level_data(int(earned), cfg),
            "referral": {
                "code": code.code,
                "invited_count": int(invited),
                "already_used_code": used,
            },
            "stats": {
                "balance": int(user.balance) if user else 0,
                "unlimited_balance": bool(user.unlimited_balance) if user else False,
                "lifetime_earned": int(earned),
                "lifetime_spent": abs(int(spent_raw)),
                "fulfilled_rewards": int(fulfilled),
                "promo_uses": int(promo_uses),
                "invited_count": int(invited),
            },
        }


@router.post("/api/referrals/apply")
async def referral_apply(payload: ReferralPayload, background_tasks: BackgroundTasks, x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data")):
    tg = core.verify_init_data(x_telegram_init_data or "")
    core.get_or_create_user(tg)
    timestamp = now()
    with core.SessionLocal() as session:
        with session.begin():
            invited = session.scalar(select(core.User).where(core.User.telegram_id == tg["id"]).with_for_update())
            if not invited:
                raise HTTPException(status_code=404, detail="Пользователь не найден")
            if timestamp - norm_dt(invited.created_at) > timedelta(days=7):
                raise HTTPException(status_code=409, detail="Код можно применить только в первые 7 дней")
            if session.scalar(select(Referral.id).where(Referral.invited_id == tg["id"])) is not None:
                raise HTTPException(status_code=409, detail="Реферальный код уже использован")
            positive = session.scalar(select(func.count()).select_from(core.Transaction).where(core.Transaction.telegram_id == tg["id"], core.Transaction.amount > 0)) or 0
            if positive:
                raise HTTPException(status_code=409, detail="Код можно применить до первых начислений")
            ref = session.scalar(select(ReferralCode).where(ReferralCode.code == payload.code.strip().upper()))
            if not ref:
                raise HTTPException(status_code=404, detail="Реферальный код не найден")
            if ref.telegram_id == tg["id"]:
                raise HTTPException(status_code=400, detail="Нельзя использовать собственный код")
            inviter = session.scalar(select(core.User).where(core.User.telegram_id == ref.telegram_id).with_for_update())
            if not inviter:
                raise HTTPException(status_code=404, detail="Пригласивший не найден")
            cfg = settings(session)
            a, b = cfg["referral_inviter_bonus"], cfg["referral_invitee_bonus"]
            inviter.balance += a
            invited.balance += b
            session.add(Referral(inviter_id=inviter.telegram_id, invited_id=invited.telegram_id, inviter_reward=a, invited_reward=b, created_at=timestamp))
            if a:
                session.add(core.Transaction(telegram_id=inviter.telegram_id, amount=a, operation_type="referral_inviter", description=f"Приглашён ID {invited.telegram_id}", created_at=timestamp))
            if b:
                session.add(core.Transaction(telegram_id=invited.telegram_id, amount=b, operation_type="referral_invitee", description="Реферальный код", created_at=timestamp))
            audit(session, "referral_applied", invited.telegram_id, f"Код {ref.code} · пригласил ID {inviter.telegram_id}")
            balance = invited.balance
            inviter_id = inviter.telegram_id
    background_tasks.add_task(send_telegram_message, tg["id"], f"Реферальный код активирован.\nНачислено +{b} 🐾.\nБаланс: {balance} 🐾")
    background_tasks.add_task(send_telegram_message, inviter_id, f"По вашему реферальному коду пришёл пользователь.\nНачислено +{a} 🐾.")
    return {"ok": True, "balance": balance, "invited_bonus": b, "inviter_bonus": a}


@router.get("/api/notifications")
async def notifications(x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data")):
    tg = core.verify_init_data(x_telegram_init_data or "")
    core.get_or_create_user(tg)
    with core.SessionLocal() as session:
        rows = session.scalars(select(WalletNotification).where(WalletNotification.telegram_id == tg["id"]).order_by(WalletNotification.id.desc()).limit(100)).all()
        return {"ok": True, "unread": sum(1 for row in rows if not row.is_read), "items": [{"id": row.id, "kind": row.kind, "title": row.title, "body": row.body, "is_read": row.is_read, "created_at": row.created_at.isoformat()} for row in rows]}


@router.post("/api/notifications/read-all")
async def read_all(x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data")):
    tg = core.verify_init_data(x_telegram_init_data or "")
    with core.SessionLocal() as session:
        rows = session.scalars(select(WalletNotification).where(WalletNotification.telegram_id == tg["id"], WalletNotification.is_read.is_(False))).all()
        for row in rows:
            row.is_read = True
        session.commit()
    return {"ok": True}


@router.get("/api/events")
async def events_user(x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data")):
    tg = core.verify_init_data(x_telegram_init_data or "")
    core.get_or_create_user(tg)
    timestamp = now()
    with core.SessionLocal() as session:
        rows = session.scalars(select(WalletEvent).where(WalletEvent.is_active.is_(True), WalletEvent.starts_at <= timestamp, WalletEvent.ends_at > timestamp).order_by(WalletEvent.ends_at.asc())).all()
        return {"ok": True, "events": [{"id": row.id, "title": row.title, "description": row.description, "badge": row.badge, "starts_at": row.starts_at.isoformat(), "ends_at": row.ends_at.isoformat()} for row in rows]}


@router.get("/api/economy")
async def economy_user(x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data")):
    tg = core.verify_init_data(x_telegram_init_data or "")
    core.get_or_create_user(tg)
    with core.SessionLocal() as session:
        return {"ok": True, "settings": settings(session)}


@router.get("/api/owner/catalog")
async def owner_catalog(x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data")):
    tg = core.verify_init_data(x_telegram_init_data or "")
    core.require_owner(tg)
    with core.SessionLocal() as session:
        rows = session.scalars(select(Reward).order_by(Reward.sort_order.asc(), Reward.id.asc())).all()
        return {"ok": True, "rewards": [catalog_item(session, row) for row in rows]}


@router.post("/api/owner/catalog")
async def owner_catalog_create(payload: RewardPayload, x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data")):
    tg = core.verify_init_data(x_telegram_init_data or "")
    core.require_owner(tg)
    timestamp = now()
    until = norm_dt(payload.available_until)
    if until and until <= timestamp:
        raise HTTPException(status_code=400, detail="Срок доступности должен быть в будущем")
    with core.SessionLocal() as session:
        with session.begin():
            reward = Reward(title=payload.title.strip(), description=(payload.description or "").strip() or None, cost=payload.cost, is_active=True, sort_order=payload.sort_order, created_at=timestamp)
            session.add(reward)
            session.flush()
            session.add(RewardMeta(reward_id=reward.id, image_url=(payload.image_url or "").strip() or None, stock_limit=payload.stock_limit, available_until=until, updated_at=timestamp))
            audit(session, "reward_created", None, f"{reward.title} · {reward.cost} 🐾")
            rid = reward.id
        result = catalog_item(session, session.get(Reward, rid))
    return {"ok": True, "reward": result}


@router.post("/api/owner/catalog/{reward_id}/update")
async def owner_catalog_update(reward_id: int, payload: RewardPayload, x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data")):
    tg = core.verify_init_data(x_telegram_init_data or "")
    core.require_owner(tg)
    timestamp = now()
    until = norm_dt(payload.available_until)
    if until and until <= timestamp:
        raise HTTPException(status_code=400, detail="Срок доступности должен быть в будущем")
    with core.SessionLocal() as session:
        with session.begin():
            reward = session.scalar(select(Reward).where(Reward.id == reward_id).with_for_update())
            if not reward:
                raise HTTPException(status_code=404, detail="Награда не найдена")
            reward.title, reward.description, reward.cost, reward.sort_order = payload.title.strip(), (payload.description or "").strip() or None, payload.cost, payload.sort_order
            meta = session.get(RewardMeta, reward_id)
            if not meta:
                meta = RewardMeta(reward_id=reward_id, image_url=None, stock_limit=None, available_until=None, updated_at=timestamp)
                session.add(meta)
            meta.image_url, meta.stock_limit, meta.available_until, meta.updated_at = (payload.image_url or "").strip() or None, payload.stock_limit, until, timestamp
            audit(session, "reward_updated", None, f"#{reward.id} · {reward.title}")
        result = catalog_item(session, session.get(Reward, reward_id))
    return {"ok": True, "reward": result}


@router.post("/api/owner/catalog/{reward_id}/toggle")
async def owner_catalog_toggle(reward_id: int, x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data")):
    tg = core.verify_init_data(x_telegram_init_data or "")
    core.require_owner(tg)
    with core.SessionLocal() as session:
        with session.begin():
            reward = session.scalar(select(Reward).where(Reward.id == reward_id).with_for_update())
            if not reward:
                raise HTTPException(status_code=404, detail="Награда не найдена")
            reward.is_active = not reward.is_active
            audit(session, "reward_toggled", None, f"#{reward.id} · {'включена' if reward.is_active else 'отключена'}")
        result = catalog_item(session, session.get(Reward, reward_id))
    return {"ok": True, "reward": result}


@router.get("/api/owner/spend-requests-advanced")
async def owner_requests_advanced(x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data")):
    tg = core.verify_init_data(x_telegram_init_data or "")
    core.require_owner(tg)
    with core.SessionLocal() as session:
        rows = session.execute(select(SpendRequest, core.User).join(core.User, core.User.telegram_id == SpendRequest.telegram_id).order_by(SpendRequest.id.desc()).limit(150)).all()
        items = []
        for item, user in rows:
            meta = session.get(RequestMeta, item.id)
            items.append({"id": item.id, "telegram_id": item.telegram_id, "username": user.username, "first_name": user.first_name, "reward_title": item.reward_title, "cost": item.cost, "status": item.status, "comment": meta.owner_comment if meta else None, "created_at": item.created_at.isoformat(), "processed_at": item.processed_at.isoformat() if item.processed_at else None})
        return {"ok": True, "requests": items}


@router.post("/api/owner/spend-requests/{request_id}/status")
async def owner_request_status(request_id: int, payload: RequestStatusPayload, background_tasks: BackgroundTasks, x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data")):
    tg = core.verify_init_data(x_telegram_init_data or "")
    core.require_owner(tg)
    status = payload.status.strip().lower()
    if status not in {"pending", "processing", "fulfilled", "cancelled"}:
        raise HTTPException(status_code=400, detail="Недопустимый статус")
    timestamp = now()
    with core.SessionLocal() as session:
        with session.begin():
            item = session.scalar(select(SpendRequest).where(SpendRequest.id == request_id).with_for_update())
            if not item:
                raise HTTPException(status_code=404, detail="Заявка не найдена")
            if item.status == "fulfilled" and status != "fulfilled":
                raise HTTPException(status_code=409, detail="Выданную заявку нельзя изменить")
            previous = item.status
            if previous != "cancelled" and status == "cancelled":
                user = session.scalar(select(core.User).where(core.User.telegram_id == item.telegram_id).with_for_update())
                user.balance += item.cost
                session.add(core.Transaction(telegram_id=item.telegram_id, amount=item.cost, operation_type="reward_refund", description=f"Отмена заявки #{item.id}: {item.reward_title}", created_at=timestamp))
            item.status = status
            item.processed_at = timestamp if status in {"fulfilled", "cancelled"} else None
            meta = session.get(RequestMeta, request_id)
            if not meta:
                meta = RequestMeta(request_id=request_id, owner_comment=None, updated_at=timestamp)
                session.add(meta)
            meta.owner_comment = (payload.comment or "").strip() or None
            meta.updated_at = timestamp
            labels = {"pending": "создана", "processing": "в работе", "fulfilled": "выдана", "cancelled": "отменена"}
            body = f"Заявка #{item.id} на «{item.reward_title}» теперь: {labels[status]}."
            if meta.owner_comment:
                body += f"\nКомментарий: {meta.owner_comment}"
            notify(session, item.telegram_id, "reward_status", "Статус заявки изменён", body)
            audit(session, "reward_status", item.telegram_id, f"Заявка #{item.id}: {previous} → {status}")
            recipient = item.telegram_id
    background_tasks.add_task(send_telegram_message, recipient, body)
    return {"ok": True, "request_id": request_id, "status": status}


@router.post("/api/owner/mass-grant")
async def owner_mass_grant(payload: MassGrantPayload, background_tasks: BackgroundTasks, x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data")):
    tg = core.verify_init_data(x_telegram_init_data or "")
    core.require_owner(tg)
    timestamp = now()
    reason = (payload.reason or "").strip() or "Массовое начисление"
    targets = list(dict.fromkeys(value.strip() for value in payload.targets if value.strip()))
    granted, missing = [], []
    with core.SessionLocal() as session:
        with session.begin():
            for raw in targets:
                user = core.find_target_user(session, raw, lock=True)
                if not user:
                    missing.append(raw)
                    continue
                if core.is_owner(user.telegram_id):
                    continue
                user.balance += payload.amount
                session.add(core.Transaction(telegram_id=user.telegram_id, amount=payload.amount, operation_type="mass_grant", description=reason, created_at=timestamp))
                granted.append({"telegram_id": user.telegram_id, "username": user.username, "balance": user.balance})
            audit(session, "mass_grant", None, f"{len(granted)} пользователей · +{payload.amount} 🐾 · {reason}")
    for item in granted:
        background_tasks.add_task(send_telegram_message, item["telegram_id"], f"Вам начислено +{payload.amount} 🐾.\nПричина: {reason}\nБаланс: {item['balance']} 🐾")
    return {"ok": True, "granted": granted, "missing": missing}


@router.get("/api/owner/events")
async def owner_events(x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data")):
    tg = core.verify_init_data(x_telegram_init_data or "")
    core.require_owner(tg)
    with core.SessionLocal() as session:
        rows = session.scalars(select(WalletEvent).order_by(WalletEvent.id.desc())).all()
        return {"ok": True, "events": [{"id": row.id, "title": row.title, "description": row.description, "badge": row.badge, "starts_at": row.starts_at.isoformat(), "ends_at": row.ends_at.isoformat(), "is_active": row.is_active} for row in rows]}


@router.post("/api/owner/events")
async def owner_event_create(payload: EventPayload, x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data")):
    tg = core.verify_init_data(x_telegram_init_data or "")
    core.require_owner(tg)
    starts, ends = norm_dt(payload.starts_at), norm_dt(payload.ends_at)
    if not starts or not ends or ends <= starts:
        raise HTTPException(status_code=400, detail="Дата окончания должна быть позже начала")
    with core.SessionLocal() as session:
        item = WalletEvent(title=payload.title.strip(), description=(payload.description or "").strip() or None, badge=(payload.badge or "").strip() or None, starts_at=starts, ends_at=ends, is_active=True, created_at=now())
        session.add(item)
        audit(session, "event_created", None, item.title)
        session.commit()
        session.refresh(item)
        return {"ok": True, "event_id": item.id}


@router.post("/api/owner/events/{event_id}/toggle")
async def owner_event_toggle(event_id: int, x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data")):
    tg = core.verify_init_data(x_telegram_init_data or "")
    core.require_owner(tg)
    with core.SessionLocal() as session:
        with session.begin():
            item = session.scalar(select(WalletEvent).where(WalletEvent.id == event_id).with_for_update())
            if not item:
                raise HTTPException(status_code=404, detail="Событие не найдено")
            item.is_active = not item.is_active
            audit(session, "event_toggled", None, f"{item.title} · {'включено' if item.is_active else 'отключено'}")
            state = item.is_active
    return {"ok": True, "is_active": state}


@router.get("/api/owner/economy")
async def owner_economy(x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data")):
    tg = core.verify_init_data(x_telegram_init_data or "")
    core.require_owner(tg)
    with core.SessionLocal() as session:
        return {"ok": True, "settings": settings(session)}


@router.post("/api/owner/economy")
async def owner_economy_update(payload: EconomyPayload, x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data")):
    tg = core.verify_init_data(x_telegram_init_data or "")
    core.require_owner(tg)
    allowed = set(DEFAULTS)
    timestamp = now()
    for key, value in payload.values.items():
        if key not in allowed or value < 0 or value > 100_000_000:
            raise HTTPException(status_code=400, detail=f"Некорректное значение: {key}")
    with core.SessionLocal() as session:
        with session.begin():
            existing = {row.key: row for row in session.scalars(select(EconomySetting)).all()}
            for key, value in payload.values.items():
                if key in existing:
                    existing[key].value, existing[key].updated_at = int(value), timestamp
                else:
                    session.add(EconomySetting(key=key, value=int(value), updated_at=timestamp))
            cfg = settings(session)
            cfg.update({key: int(value) for key, value in payload.values.items()})
            if not (cfg["level_regular"] < cfg["level_vip"] < cfg["level_legend"]):
                raise HTTPException(status_code=400, detail="Пороги уровней должны идти по возрастанию")
            if cfg["activity_min"] > cfg["activity_max"]:
                raise HTTPException(status_code=400, detail="Минимум активности не может быть больше максимума")
            audit(session, "economy_updated", None, ", ".join(f"{k}={v}" for k, v in payload.values.items()))
    return {"ok": True, "settings": cfg}


@router.get("/api/owner/integrity")
async def owner_integrity(x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data")):
    tg = core.verify_init_data(x_telegram_init_data or "")
    core.require_owner(tg)
    with core.SessionLocal() as session:
        negative = session.scalar(select(func.count()).select_from(core.User).where(core.User.balance < 0, core.User.telegram_id != (core.OWNER_TELEGRAM_ID or -1))) or 0
        users = session.scalar(select(func.count()).select_from(core.User)) or 0
        txs = session.scalar(select(func.count()).select_from(core.Transaction)) or 0
        requests = session.scalar(select(func.count()).select_from(SpendRequest)) or 0
        promo_rows = session.execute(select(core.PromoCode.id, core.PromoCode.uses_count, func.count(core.PromoRedemption.id)).outerjoin(core.PromoRedemption, core.PromoRedemption.promo_id == core.PromoCode.id).group_by(core.PromoCode.id, core.PromoCode.uses_count)).all()
        mismatches = sum(1 for _, declared, actual in promo_rows if int(declared) != int(actual))
        issues = []
        if negative:
            issues.append(f"Отрицательных балансов: {negative}")
        if mismatches:
            issues.append(f"Промокодов с несовпадающим счётчиком: {mismatches}")
        return {"ok": True, "healthy": not issues, "issues": issues, "counts": {"users": int(users), "transactions": int(txs), "requests": int(requests)}}


def csv_bytes(headers: list[str], rows: list[list]) -> bytes:
    stream = io.StringIO()
    writer = csv.writer(stream)
    writer.writerow(headers)
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8-sig")


@router.get("/api/owner/export")
async def owner_export(x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data")):
    tg = core.verify_init_data(x_telegram_init_data or "")
    core.require_owner(tg)
    output = io.BytesIO()
    with core.SessionLocal() as session, zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        users = session.scalars(select(core.User).order_by(core.User.created_at.asc())).all()
        archive.writestr("users.csv", csv_bytes(["telegram_id", "username", "first_name", "last_name", "balance", "created_at", "last_seen_at"], [[u.telegram_id, u.username, u.first_name, u.last_name, u.balance, u.created_at.isoformat(), u.last_seen_at.isoformat()] for u in users]))
        txs = session.scalars(select(core.Transaction).order_by(core.Transaction.id.asc())).all()
        archive.writestr("transactions.csv", csv_bytes(["id", "telegram_id", "amount", "operation_type", "description", "created_at"], [[t.id, t.telegram_id, t.amount, t.operation_type, t.description, t.created_at.isoformat()] for t in txs]))
        requests = session.scalars(select(SpendRequest).order_by(SpendRequest.id.asc())).all()
        archive.writestr("spend_requests.csv", csv_bytes(["id", "telegram_id", "reward_title", "cost", "status", "created_at", "processed_at"], [[r.id, r.telegram_id, r.reward_title, r.cost, r.status, r.created_at.isoformat(), r.processed_at.isoformat() if r.processed_at else ""] for r in requests]))
        refs = session.scalars(select(Referral).order_by(Referral.id.asc())).all()
        archive.writestr("referrals.csv", csv_bytes(["id", "inviter_id", "invited_id", "inviter_reward", "invited_reward", "created_at"], [[r.id, r.inviter_id, r.invited_id, r.inviter_reward, r.invited_reward, r.created_at.isoformat()] for r in refs]))
    output.seek(0)
    filename = f"nyan-wallet-backup-{now().date().isoformat()}.zip"
    return StreamingResponse(output, media_type="application/zip", headers={"Content-Disposition": f'attachment; filename="{filename}"'})


def register_advanced_features(app) -> None:
    global _REGISTERED
    if _REGISTERED:
        return
    core.Base.metadata.create_all(core.engine)
    ensure_settings()
    event.listen(core.Transaction, "after_insert", tx_notification)
    event.listen(Session, "before_flush", reward_guard)
    app.include_router(router)
    _REGISTERED = True
