from __future__ import annotations

from datetime import date, datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import BigInteger, Date, DateTime, ForeignKey, Integer, String, UniqueConstraint, func, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from . import backend_app as core
from .advanced_features import Referral, WalletNotification, settings
from .extended_features import SpendRequest, send_telegram_message

router = APIRouter()
_REGISTERED = False


class AchievementUnlock(core.Base):
    __tablename__ = "achievement_unlocks"
    __table_args__ = (UniqueConstraint("telegram_id", "achievement_key", name="uq_achievement_user_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telegram_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.telegram_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    achievement_key: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    reward_amount: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    unlocked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AchievementBadge(core.Base):
    __tablename__ = "achievement_badges"

    telegram_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.telegram_id", ondelete="CASCADE"),
        primary_key=True,
    )
    achievement_key: Mapped[str] = mapped_column(String(64), nullable=False)
    selected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class WalletActivityDay(core.Base):
    __tablename__ = "wallet_activity_days"
    __table_args__ = (UniqueConstraint("telegram_id", "activity_date", name="uq_wallet_activity_day"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telegram_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.telegram_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    activity_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class BadgePayload(BaseModel):
    key: str | None = Field(default=None, max_length=64)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# reward=0 means the achievement is collectible only and does not mint лапкоины.
ACHIEVEMENTS = [
    {"key": "first_step", "title": "Первый шаг", "description": "Открыть Nyan Wallet впервые", "icon": "paw", "rarity": "common", "reward": 5, "metric": "first_step", "target": 1},
    {"key": "first_coins", "title": "Первые лапкоины", "description": "Получить первые лапкоины", "icon": "coin", "rarity": "common", "reward": 0, "metric": "positive_tx", "target": 1},
    {"key": "hundred", "title": "Соточка", "description": "Заработать суммарно 100 🐾", "icon": "bag", "rarity": "common", "reward": 10, "metric": "earned", "target": 100},
    {"key": "piggybank", "title": "Копилка", "description": "Заработать суммарно 500 🐾", "icon": "piggy", "rarity": "rare", "reward": 20, "metric": "earned", "target": 500},
    {"key": "thousand", "title": "Тысяча", "description": "Заработать суммарно 1 000 🐾", "icon": "star", "rarity": "rare", "reward": 30, "metric": "earned", "target": 1000},
    {"key": "collector", "title": "Коллекционер", "description": "Заработать суммарно 5 000 🐾", "icon": "gem", "rarity": "epic", "reward": 0, "metric": "earned", "target": 5000},
    {"key": "first_reward", "title": "Первая награда", "description": "Впервые заказать приз", "icon": "gift", "rarity": "common", "reward": 10, "metric": "requests", "target": 1},
    {"key": "reward_hunter", "title": "Охотник за наградами", "description": "Получить 5 выданных наград", "icon": "gift_star", "rarity": "rare", "reward": 25, "metric": "fulfilled", "target": 5},
    {"key": "promocoder", "title": "Промокодер", "description": "Активировать первый промокод", "icon": "ticket", "rarity": "common", "reward": 0, "metric": "promos", "target": 1},
    {"key": "lucky", "title": "Удачливый", "description": "Активировать 5 разных промокодов", "icon": "clover", "rarity": "rare", "reward": 15, "metric": "promos", "target": 5},
    {"key": "first_friend", "title": "Первый друг", "description": "Пригласить 1 пользователя", "icon": "friend", "rarity": "common", "reward": 10, "metric": "invited", "target": 1},
    {"key": "company", "title": "Компания", "description": "Пригласить 5 пользователей", "icon": "group", "rarity": "rare", "reward": 25, "metric": "invited", "target": 5},
    {"key": "own_pack", "title": "Своя стая", "description": "Пригласить 10 пользователей", "icon": "crown", "rarity": "epic", "reward": 0, "metric": "invited", "target": 10},
    {"key": "regular", "title": "Постоянный", "description": "Пользоваться Wallet 7 разных дней", "icon": "calendar", "rarity": "rare", "reward": 15, "metric": "active_days", "target": 7},
    {"key": "long_time", "title": "С нами давно", "description": "Пользоваться Wallet 30 разных дней", "icon": "medal", "rarity": "epic", "reward": 30, "metric": "active_days", "target": 30},
    {"key": "nyan_legend", "title": "Нян Легенда", "description": "Достичь уровня «Легенда»", "icon": "legend", "rarity": "legendary", "reward": 0, "metric": "legend", "target": 1},
]
ACHIEVEMENT_BY_KEY = {item["key"]: item for item in ACHIEVEMENTS}


def _record_activity(session: Session, telegram_id: int, timestamp: datetime) -> None:
    today = timestamp.date()
    exists = session.scalar(
        select(WalletActivityDay.id).where(
            WalletActivityDay.telegram_id == telegram_id,
            WalletActivityDay.activity_date == today,
        )
    )
    if exists is None:
        session.add(
            WalletActivityDay(
                telegram_id=telegram_id,
                activity_date=today,
                first_seen_at=timestamp,
            )
        )
        session.flush()


def _stats(session: Session, telegram_id: int) -> dict[str, int]:
    # Achievement bonuses are deliberately excluded from lifetime earning milestones,
    # otherwise one unlocked achievement could recursively unlock the next one.
    earned = session.scalar(
        select(func.coalesce(func.sum(core.Transaction.amount), 0)).where(
            core.Transaction.telegram_id == telegram_id,
            core.Transaction.amount > 0,
            core.Transaction.operation_type != "achievement",
        )
    ) or 0
    positive_tx = session.scalar(
        select(func.count()).select_from(core.Transaction).where(
            core.Transaction.telegram_id == telegram_id,
            core.Transaction.amount > 0,
            core.Transaction.operation_type != "achievement",
        )
    ) or 0
    requests = session.scalar(
        select(func.count()).select_from(SpendRequest).where(SpendRequest.telegram_id == telegram_id)
    ) or 0
    fulfilled = session.scalar(
        select(func.count()).select_from(SpendRequest).where(
            SpendRequest.telegram_id == telegram_id,
            SpendRequest.status == "fulfilled",
        )
    ) or 0
    promos = session.scalar(
        select(func.count()).select_from(core.PromoRedemption).where(
            core.PromoRedemption.telegram_id == telegram_id
        )
    ) or 0
    invited = session.scalar(
        select(func.count()).select_from(Referral).where(Referral.inviter_id == telegram_id)
    ) or 0
    active_days = session.scalar(
        select(func.count()).select_from(WalletActivityDay).where(
            WalletActivityDay.telegram_id == telegram_id
        )
    ) or 0
    cfg = settings(session)
    return {
        "first_step": 1,
        "earned": int(earned),
        "positive_tx": int(positive_tx),
        "requests": int(requests),
        "fulfilled": int(fulfilled),
        "promos": int(promos),
        "invited": int(invited),
        "active_days": int(active_days),
        "legend": 1 if int(earned) >= int(cfg.get("level_legend", 5000)) else 0,
    }


def _unlock_new(session: Session, user: core.User, stats: dict[str, int], timestamp: datetime) -> list[dict]:
    existing = {
        row.achievement_key
        for row in session.scalars(
            select(AchievementUnlock).where(AchievementUnlock.telegram_id == user.telegram_id)
        ).all()
    }
    unlocked: list[dict] = []

    for item in ACHIEVEMENTS:
        key = item["key"]
        current = int(stats.get(item["metric"], 0))
        if key in existing or current < int(item["target"]):
            continue

        reward = int(item["reward"])
        session.add(
            AchievementUnlock(
                telegram_id=user.telegram_id,
                achievement_key=key,
                reward_amount=reward,
                unlocked_at=timestamp,
            )
        )
        if reward:
            user.balance += reward
            session.add(
                core.Transaction(
                    telegram_id=user.telegram_id,
                    amount=reward,
                    operation_type="achievement",
                    description=f"Достижение: {item['title']}",
                    created_at=timestamp,
                )
            )
        body = f"Открыто достижение «{item['title']}»."
        if reward:
            body += f" Награда +{reward} 🐾."
        session.add(
            WalletNotification(
                telegram_id=user.telegram_id,
                kind="achievement",
                title="Новое достижение",
                body=body,
                is_read=False,
                created_at=timestamp,
            )
        )
        existing.add(key)
        unlocked.append(item)

    return unlocked


def _serialize(session: Session, telegram_id: int, stats: dict[str, int]) -> dict:
    unlock_rows = session.scalars(
        select(AchievementUnlock).where(AchievementUnlock.telegram_id == telegram_id)
    ).all()
    unlock_map = {row.achievement_key: row for row in unlock_rows}
    badge = session.get(AchievementBadge, telegram_id)
    items = []
    for item in ACHIEVEMENTS:
        row = unlock_map.get(item["key"])
        current = int(stats.get(item["metric"], 0))
        target = int(item["target"])
        items.append(
            {
                **item,
                "unlocked": row is not None,
                "unlocked_at": row.unlocked_at.isoformat() if row else None,
                "current": min(current, target),
                "target": target,
                "progress": min(100, round(current * 100 / max(1, target))),
                "selected": badge is not None and badge.achievement_key == item["key"],
            }
        )

    selected = None
    if badge and badge.achievement_key in ACHIEVEMENT_BY_KEY:
        source = ACHIEVEMENT_BY_KEY[badge.achievement_key]
        selected = {"key": source["key"], "title": source["title"], "icon": source["icon"], "rarity": source["rarity"]}

    return {
        "items": items,
        "unlocked_count": len(unlock_map),
        "total": len(ACHIEVEMENTS),
        "selected_badge": selected,
    }


@router.get("/api/achievements")
async def achievements(
    background_tasks: BackgroundTasks,
    x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data"),
):
    tg = core.verify_init_data(x_telegram_init_data or "")
    core.get_or_create_user(tg)
    timestamp = utcnow()

    with core.SessionLocal() as session:
        with session.begin():
            user = session.scalar(
                select(core.User).where(core.User.telegram_id == tg["id"]).with_for_update()
            )
            if user is None:
                raise HTTPException(status_code=404, detail="Пользователь не найден")
            _record_activity(session, user.telegram_id, timestamp)
            stats = _stats(session, user.telegram_id)
            newly_unlocked = _unlock_new(session, user, stats, timestamp)
            balance = int(user.balance)
        stats = _stats(session, tg["id"])
        payload = _serialize(session, tg["id"], stats)

    if newly_unlocked:
        lines = [f"• {item['title']}" + (f"  +{item['reward']} 🐾" if item["reward"] else "") for item in newly_unlocked]
        background_tasks.add_task(
            send_telegram_message,
            tg["id"],
            "Новые достижения Nyan Wallet:\n" + "\n".join(lines),
        )

    return {"ok": True, "balance": balance, "newly_unlocked": [item["key"] for item in newly_unlocked], **payload}


@router.post("/api/achievements/badge")
async def select_badge(
    payload: BadgePayload,
    x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data"),
):
    tg = core.verify_init_data(x_telegram_init_data or "")
    core.get_or_create_user(tg)
    key = (payload.key or "").strip() or None

    with core.SessionLocal() as session:
        with session.begin():
            row = session.get(AchievementBadge, tg["id"])
            if key is None:
                if row:
                    session.delete(row)
                return {"ok": True, "selected_badge": None}

            if key not in ACHIEVEMENT_BY_KEY:
                raise HTTPException(status_code=404, detail="Достижение не найдено")
            unlocked = session.scalar(
                select(AchievementUnlock.id).where(
                    AchievementUnlock.telegram_id == tg["id"],
                    AchievementUnlock.achievement_key == key,
                )
            )
            if unlocked is None:
                raise HTTPException(status_code=409, detail="Сначала откройте это достижение")

            if row is None:
                row = AchievementBadge(
                    telegram_id=tg["id"],
                    achievement_key=key,
                    selected_at=utcnow(),
                )
                session.add(row)
            else:
                row.achievement_key = key
                row.selected_at = utcnow()

    source = ACHIEVEMENT_BY_KEY[key]
    return {
        "ok": True,
        "selected_badge": {
            "key": key,
            "title": source["title"],
            "icon": source["icon"],
            "rarity": source["rarity"],
        },
    }


def register_achievements(app) -> None:
    global _REGISTERED
    if _REGISTERED:
        return
    core.Base.metadata.create_all(core.engine)
    app.include_router(router)
    _REGISTERED = True
