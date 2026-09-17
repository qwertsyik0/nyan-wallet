from __future__ import annotations

import json
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, Text, func, select
from sqlalchemy.orm import Mapped, mapped_column

from server import backend_app as core


class Reward(core.Base):
    __tablename__ = "reward_catalog"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    cost: Mapped[int] = mapped_column(Integer, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class SpendRequest(core.Base):
    __tablename__ = "spend_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telegram_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.telegram_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    reward_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("reward_catalog.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    reward_title: Mapped[str] = mapped_column(String(120), nullable=False)
    cost: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AdminAudit(core.Base):
    __tablename__ = "admin_audit"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    action: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    target_telegram_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    details: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)


class PromoLimitUpdateRequest(BaseModel):
    max_uses: int | None = Field(default=None, ge=1, le=1_000_000)


router = APIRouter()


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def serialize_reward(reward: Reward) -> dict:
    return {
        "id": reward.id,
        "title": reward.title,
        "description": reward.description,
        "cost": reward.cost,
        "is_active": reward.is_active,
    }


def serialize_spend_request(item: SpendRequest) -> dict:
    return {
        "id": item.id,
        "telegram_id": item.telegram_id,
        "reward_id": item.reward_id,
        "reward_title": item.reward_title,
        "cost": item.cost,
        "status": item.status,
        "created_at": item.created_at.isoformat(),
        "processed_at": item.processed_at.isoformat() if item.processed_at else None,
    }


def audit(session, action: str, target_telegram_id: int | None = None, details: str | None = None) -> None:
    session.add(
        AdminAudit(
            action=action,
            target_telegram_id=target_telegram_id,
            details=details,
            created_at=now_utc(),
        )
    )


def send_telegram_message(chat_id: int | None, text: str) -> None:
    if not chat_id or not core.BOT_TOKEN:
        return
    try:
        url = f"https://api.telegram.org/bot{core.BOT_TOKEN}/sendMessage"
        payload = urllib.parse.urlencode({"chat_id": str(chat_id), "text": text}).encode()
        request = urllib.request.Request(url, data=payload, method="POST")
        with urllib.request.urlopen(request, timeout=6) as response:
            response.read()
    except Exception:
        return


def user_label(user: core.User) -> str:
    if user.username:
        return f"@{user.username}"
    full_name = " ".join(part for part in [user.first_name, user.last_name] if part).strip()
    return full_name or f"ID {user.telegram_id}"


def seed_rewards() -> None:
    with core.SessionLocal() as session:
        existing = session.scalar(select(func.count()).select_from(Reward)) or 0
        if existing:
            return
        timestamp = now_utc()
        session.add_all(
            [
                Reward(
                    title="50 Telegram Stars",
                    description="Заявка на выдачу 50 Stars",
                    cost=300,
                    is_active=True,
                    sort_order=10,
                    created_at=timestamp,
                ),
                Reward(
                    title="100 Telegram Stars",
                    description="Заявка на выдачу 100 Stars",
                    cost=550,
                    is_active=True,
                    sort_order=20,
                    created_at=timestamp,
                ),
                Reward(
                    title="250 Telegram Stars",
                    description="Заявка на выдачу 250 Stars",
                    cost=1250,
                    is_active=True,
                    sort_order=30,
                    created_at=timestamp,
                ),
                Reward(
                    title="500 Telegram Stars",
                    description="Заявка на выдачу 500 Stars",
                    cost=2300,
                    is_active=True,
                    sort_order=40,
                    created_at=timestamp,
                ),
            ]
        )
        session.commit()


@router.get("/api/rewards")
async def rewards(
    x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data"),
):
    tg_user = core.verify_init_data(x_telegram_init_data or "")
    core.get_or_create_user(tg_user)

    with core.SessionLocal() as session:
        items = session.scalars(
            select(Reward)
            .where(Reward.is_active.is_(True))
            .order_by(Reward.sort_order.asc(), Reward.id.asc())
        ).all()
        requests = session.scalars(
            select(SpendRequest)
            .where(SpendRequest.telegram_id == tg_user["id"])
            .order_by(SpendRequest.id.desc())
            .limit(20)
        ).all()
        return {
            "ok": True,
            "rewards": [serialize_reward(item) for item in items],
            "requests": [serialize_spend_request(item) for item in requests],
        }


@router.post("/api/rewards/{reward_id}/request")
async def create_spend_request(
    reward_id: int,
    background_tasks: BackgroundTasks,
    x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data"),
):
    tg_user = core.verify_init_data(x_telegram_init_data or "")
    timestamp = now_utc()

    with core.SessionLocal() as session:
        with session.begin():
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

            reward = session.scalar(
                select(Reward)
                .where(Reward.id == reward_id, Reward.is_active.is_(True))
                .with_for_update()
            )
            if reward is None:
                raise HTTPException(status_code=404, detail="Награда недоступна")

            if core.is_owner(user.telegram_id):
                raise HTTPException(status_code=400, detail="Владельцу не нужно списывать бесконечный баланс")

            if user.balance < reward.cost:
                raise HTTPException(
                    status_code=409,
                    detail=f"Недостаточно лапкоинов. Нужно {reward.cost} 🐾, у вас {user.balance} 🐾",
                )

            user.balance -= reward.cost
            item = SpendRequest(
                telegram_id=user.telegram_id,
                reward_id=reward.id,
                reward_title=reward.title,
                cost=reward.cost,
                status="pending",
                created_at=timestamp,
                processed_at=None,
            )
            session.add(item)
            session.flush()

            session.add(
                core.Transaction(
                    telegram_id=user.telegram_id,
                    amount=-reward.cost,
                    operation_type="reward_request",
                    description=f"Заявка: {reward.title}",
                    created_at=timestamp,
                )
            )

            request_id = item.id
            new_balance = user.balance
            owner_text = (
                "🐾 Новая заявка Nyan Wallet\n"
                f"Заявка #{request_id}\n"
                f"Пользователь: {user_label(user)}\n"
                f"Telegram ID: {user.telegram_id}\n"
                f"Награда: {reward.title}\n"
                f"Стоимость: {reward.cost} 🐾"
            )
            user_text = (
                f"Заявка #{request_id} создана.\n"
                f"Награда: {reward.title}\n"
                "Мы выдадим приз в ближайшее время."
            )

    background_tasks.add_task(send_telegram_message, core.OWNER_TELEGRAM_ID, owner_text)
    background_tasks.add_task(send_telegram_message, tg_user["id"], user_text)

    return {
        "ok": True,
        "request": {
            "id": request_id,
            "reward_title": reward.title,
            "cost": reward.cost,
            "status": "pending",
            "created_at": timestamp.isoformat(),
        },
        "balance": new_balance,
        "message": "Заявка создана. Мы выдадим приз вам в ближайшее время.",
    }


@router.get("/api/owner/spend-requests")
async def owner_spend_requests(
    x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data"),
):
    tg_user = core.verify_init_data(x_telegram_init_data or "")
    core.require_owner(tg_user)

    with core.SessionLocal() as session:
        rows = session.execute(
            select(SpendRequest, core.User)
            .join(core.User, core.User.telegram_id == SpendRequest.telegram_id)
            .order_by(SpendRequest.id.desc())
            .limit(100)
        ).all()
        result = []
        for item, user in rows:
            data = serialize_spend_request(item)
            data["username"] = user.username
            data["first_name"] = user.first_name
            result.append(data)
        return {"ok": True, "requests": result}


@router.post("/api/owner/spend-requests/{request_id}/complete")
async def complete_spend_request(
    request_id: int,
    background_tasks: BackgroundTasks,
    x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data"),
):
    tg_user = core.verify_init_data(x_telegram_init_data or "")
    core.require_owner(tg_user)
    timestamp = now_utc()

    with core.SessionLocal() as session:
        with session.begin():
            item = session.scalar(
                select(SpendRequest)
                .where(SpendRequest.id == request_id)
                .with_for_update()
            )
            if item is None:
                raise HTTPException(status_code=404, detail="Заявка не найдена")
            if item.status != "pending":
                raise HTTPException(status_code=409, detail="Заявка уже обработана")

            item.status = "fulfilled"
            item.processed_at = timestamp
            audit(
                session,
                "reward_fulfilled",
                item.telegram_id,
                f"Заявка #{item.id}: {item.reward_title}, {item.cost} 🐾",
            )
            recipient = item.telegram_id
            reward_title = item.reward_title

    background_tasks.add_task(
        send_telegram_message,
        recipient,
        f"Заявка #{request_id} выполнена.\nПриз: {reward_title}\nСпасибо, что пользуетесь Nyan Wallet.",
    )
    return {"ok": True, "request_id": request_id, "status": "fulfilled"}


@router.get("/api/owner/stats")
async def owner_stats(
    x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data"),
):
    tg_user = core.verify_init_data(x_telegram_init_data or "")
    core.require_owner(tg_user)
    today = now_utc().replace(hour=0, minute=0, second=0, microsecond=0)

    with core.SessionLocal() as session:
        total_users = session.scalar(select(func.count()).select_from(core.User)) or 0
        circulation_query = select(func.coalesce(func.sum(core.User.balance), 0))
        if core.OWNER_TELEGRAM_ID is not None:
            circulation_query = circulation_query.where(core.User.telegram_id != core.OWNER_TELEGRAM_ID)
        circulation = session.scalar(circulation_query) or 0
        granted_today = session.scalar(
            select(func.coalesce(func.sum(core.Transaction.amount), 0)).where(
                core.Transaction.operation_type == "owner_grant",
                core.Transaction.created_at >= today,
            )
        ) or 0
        spent_today_raw = session.scalar(
            select(func.coalesce(func.sum(core.Transaction.amount), 0)).where(
                core.Transaction.amount < 0,
                core.Transaction.created_at >= today,
            )
        ) or 0
        promo_uses = session.scalar(select(func.count()).select_from(core.PromoRedemption)) or 0
        pending_requests = session.scalar(
            select(func.count()).select_from(SpendRequest).where(SpendRequest.status == "pending")
        ) or 0

        return {
            "ok": True,
            "stats": {
                "total_users": int(total_users),
                "circulation": int(circulation),
                "granted_today": int(granted_today),
                "spent_today": abs(int(spent_today_raw)),
                "promo_uses": int(promo_uses),
                "pending_requests": int(pending_requests),
            },
        }


@router.get("/api/owner/audit")
async def owner_audit(
    x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data"),
):
    tg_user = core.verify_init_data(x_telegram_init_data or "")
    core.require_owner(tg_user)

    with core.SessionLocal() as session:
        rows = session.scalars(
            select(AdminAudit).order_by(AdminAudit.id.desc()).limit(100)
        ).all()
        return {
            "ok": True,
            "items": [
                {
                    "id": row.id,
                    "action": row.action,
                    "target_telegram_id": row.target_telegram_id,
                    "details": row.details,
                    "created_at": row.created_at.isoformat(),
                }
                for row in rows
            ],
        }


@router.post("/api/owner/action/grant")
async def owner_action_grant(
    payload: core.OwnerGrantRequest,
    background_tasks: BackgroundTasks,
    x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data"),
):
    tg_user = core.verify_init_data(x_telegram_init_data or "")
    result = core.grant_lapcoins(tg_user, payload)

    with core.SessionLocal() as session:
        audit(
            session,
            "owner_grant",
            result["telegram_id"],
            f"+{result['amount']} 🐾" + (f" · {result['reason']}" if result.get("reason") else ""),
        )
        session.commit()

    text = f"Вам начислено +{result['amount']} 🐾."
    if result.get("reason"):
        text += f"\nПричина: {result['reason']}"
    text += f"\nБаланс: {result['balance']} 🐾"
    background_tasks.add_task(send_telegram_message, result["telegram_id"], text)
    return {"ok": True, "grant": result}


@router.post("/api/owner/action/debit")
async def owner_action_debit(
    payload: core.OwnerGrantRequest,
    background_tasks: BackgroundTasks,
    x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data"),
):
    tg_user = core.verify_init_data(x_telegram_init_data or "")
    result = core.debit_lapcoins(tg_user, payload)

    with core.SessionLocal() as session:
        audit(
            session,
            "owner_debit",
            result["telegram_id"],
            f"-{result['amount']} 🐾" + (f" · {result['reason']}" if result.get("reason") else ""),
        )
        session.commit()

    text = f"С вашего баланса списано {result['amount']} 🐾."
    if result.get("reason"):
        text += f"\nПричина: {result['reason']}"
    text += f"\nБаланс: {result['balance']} 🐾"
    background_tasks.add_task(send_telegram_message, result["telegram_id"], text)
    return {"ok": True, "debit": result}


@router.post("/api/owner/manage/promos")
async def owner_manage_promo_create(
    payload: core.OwnerPromoCreateRequest,
    x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data"),
):
    tg_user = core.verify_init_data(x_telegram_init_data or "")
    promo = core.create_owner_promo(tg_user, payload)
    with core.SessionLocal() as session:
        audit(session, "promo_created", None, f"{promo['code']} · +{promo['reward_amount']} 🐾")
        session.commit()
    return {"ok": True, "promo": promo}


@router.post("/api/owner/promos/{promo_id}/toggle")
async def owner_promo_toggle(
    promo_id: int,
    x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data"),
):
    tg_user = core.verify_init_data(x_telegram_init_data or "")
    core.require_owner(tg_user)

    with core.SessionLocal() as session:
        with session.begin():
            promo = session.scalar(
                select(core.PromoCode).where(core.PromoCode.id == promo_id).with_for_update()
            )
            if promo is None:
                raise HTTPException(status_code=404, detail="Промокод не найден")
            promo.is_active = not promo.is_active
            audit(session, "promo_toggled", None, f"{promo.code} · {'включён' if promo.is_active else 'отключён'}")
            result = core.serialize_promo(promo)
    return {"ok": True, "promo": result}


@router.post("/api/owner/promos/{promo_id}/limit")
async def owner_promo_limit(
    promo_id: int,
    payload: PromoLimitUpdateRequest,
    x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data"),
):
    tg_user = core.verify_init_data(x_telegram_init_data or "")
    core.require_owner(tg_user)

    with core.SessionLocal() as session:
        with session.begin():
            promo = session.scalar(
                select(core.PromoCode).where(core.PromoCode.id == promo_id).with_for_update()
            )
            if promo is None:
                raise HTTPException(status_code=404, detail="Промокод не найден")
            if payload.max_uses is not None and payload.max_uses < promo.uses_count:
                raise HTTPException(
                    status_code=409,
                    detail=f"Лимит не может быть меньше уже использованных активаций: {promo.uses_count}",
                )
            promo.max_uses = payload.max_uses
            label = "без лимита" if payload.max_uses is None else str(payload.max_uses)
            audit(session, "promo_limit_changed", None, f"{promo.code} · лимит {label}")
            result = core.serialize_promo(promo)
    return {"ok": True, "promo": result}


@router.get("/api/owner/promos/{promo_id}/redemptions")
async def owner_promo_redemptions(
    promo_id: int,
    x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data"),
):
    tg_user = core.verify_init_data(x_telegram_init_data or "")
    core.require_owner(tg_user)

    with core.SessionLocal() as session:
        promo = session.get(core.PromoCode, promo_id)
        if promo is None:
            raise HTTPException(status_code=404, detail="Промокод не найден")
        rows = session.execute(
            select(core.PromoRedemption, core.User)
            .join(core.User, core.User.telegram_id == core.PromoRedemption.telegram_id)
            .where(core.PromoRedemption.promo_id == promo_id)
            .order_by(core.PromoRedemption.id.desc())
        ).all()
        return {
            "ok": True,
            "code": promo.code,
            "items": [
                {
                    "telegram_id": redemption.telegram_id,
                    "username": user.username,
                    "first_name": user.first_name,
                    "reward_amount": redemption.reward_amount,
                    "created_at": redemption.created_at.isoformat(),
                }
                for redemption, user in rows
            ],
        }


@router.post("/api/owner/promos/{promo_id}/delete")
async def owner_promo_delete(
    promo_id: int,
    x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data"),
):
    tg_user = core.verify_init_data(x_telegram_init_data or "")
    core.require_owner(tg_user)

    with core.SessionLocal() as session:
        with session.begin():
            promo = session.scalar(
                select(core.PromoCode).where(core.PromoCode.id == promo_id).with_for_update()
            )
            if promo is None:
                raise HTTPException(status_code=404, detail="Промокод не найден")
            if promo.uses_count > 0:
                raise HTTPException(
                    status_code=409,
                    detail="Использованный промокод нельзя удалить. Его можно отключить.",
                )
            code = promo.code
            session.delete(promo)
            audit(session, "promo_deleted", None, code)
    return {"ok": True, "deleted": promo_id}


def register_extended_features(app) -> None:
    core.Base.metadata.create_all(core.engine)
    seed_rewards()
    app.include_router(router)
