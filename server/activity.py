from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Header, HTTPException
from sqlalchemy import BigInteger, Date, DateTime, ForeignKey, Integer, UniqueConstraint, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, mapped_column

from server import backend_app as core

router = APIRouter()
_REGISTERED = False

try:
    NYAN_ACTIVITY_TZ = ZoneInfo("Europe/Moscow")
except Exception:
    NYAN_ACTIVITY_TZ = timezone(timedelta(hours=3))


class ActivityStreak(core.Base):
    __tablename__ = "activity_streaks"

    telegram_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.telegram_id", ondelete="CASCADE"),
        primary_key=True,
    )
    current_streak: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    best_streak: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_checkins: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_checkin_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    last_reward_amount: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ActivityCheckIn(core.Base):
    __tablename__ = "activity_checkins"
    __table_args__ = (
        UniqueConstraint("telegram_id", "checkin_date", name="uq_activity_checkin_day"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telegram_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.telegram_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    checkin_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    streak_day: Mapped[int] = mapped_column(Integer, nullable=False)
    reward_amount: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def activity_today(timestamp: datetime | None = None) -> date:
    source = timestamp or now_utc()
    if source.tzinfo is None:
        source = source.replace(tzinfo=timezone.utc)
    return source.astimezone(NYAN_ACTIVITY_TZ).date()


def activity_reward_for_streak(streak_day: int) -> int:
    if streak_day <= 0:
        return 0
    if streak_day % 30 == 0:
        return 25
    if streak_day % 14 == 0:
        return 15
    if streak_day % 7 == 0:
        return 10
    return min(5, max(1, streak_day))


def serialize_streak(row: ActivityStreak | None, today: date, balance: int, unlimited_balance: bool) -> dict:
    if row is None:
        current = 0
        best = 0
        total = 0
        last_date = None
        last_reward = 0
        checked_today = False
    else:
        checked_today = row.last_checkin_date == today
        current = int(row.current_streak)
        best = int(row.best_streak)
        total = int(row.total_checkins)
        last_date = row.last_checkin_date.isoformat() if row.last_checkin_date else None
        last_reward = int(row.last_reward_amount)

    return {
        "current_streak": current,
        "best_streak": best,
        "total_checkins": total,
        "checked_today": checked_today,
        "last_checkin_date": last_date,
        "last_reward_amount": last_reward,
        "next_reward_amount": activity_reward_for_streak(current + 1),
        "balance": int(balance),
        "unlimited_balance": bool(unlimited_balance),
        "today": today.isoformat(),
        "timezone": "Europe/Moscow",
    }


@router.get("/api/activity/streak")
async def activity_streak(
    x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data"),
):
    tg = core.verify_init_data(x_telegram_init_data or "")
    core.get_or_create_user(tg)
    timestamp = now_utc()
    today = activity_today(timestamp)

    with core.SessionLocal() as session:
        user = session.scalar(select(core.User).where(core.User.telegram_id == tg["id"]))
        if user is None:
            raise HTTPException(status_code=404, detail="Пользователь не найден")
        row = session.get(ActivityStreak, tg["id"])
        return {"ok": True, "activity": serialize_streak(row, today, user.balance, core.is_owner(user.telegram_id))}


@router.post("/api/activity/check-in")
async def activity_check_in(
    x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data"),
):
    tg = core.verify_init_data(x_telegram_init_data or "")
    core.get_or_create_user(tg)
    timestamp = now_utc()
    today = activity_today(timestamp)
    credited_now = 0
    already_checked_today = False

    try:
        with core.SessionLocal() as session:
            with session.begin():
                user = session.scalar(
                    select(core.User)
                    .where(core.User.telegram_id == tg["id"])
                    .with_for_update()
                )
                if user is None:
                    raise HTTPException(status_code=404, detail="Пользователь не найден")

                row = session.get(ActivityStreak, tg["id"])
                if row is None:
                    row = ActivityStreak(
                        telegram_id=tg["id"],
                        current_streak=0,
                        best_streak=0,
                        total_checkins=0,
                        last_checkin_date=None,
                        last_reward_amount=0,
                        updated_at=timestamp,
                    )
                    session.add(row)
                    session.flush()

                if row.last_checkin_date is not None and row.last_checkin_date >= today:
                    already_checked_today = True
                    result = serialize_streak(row, today, user.balance, core.is_owner(user.telegram_id))
                else:
                    yesterday = today - timedelta(days=1)
                    if row.last_checkin_date == yesterday:
                        new_streak = int(row.current_streak) + 1
                    else:
                        new_streak = 1

                    reward = activity_reward_for_streak(new_streak)
                    row.current_streak = new_streak
                    row.best_streak = max(int(row.best_streak), new_streak)
                    row.total_checkins = int(row.total_checkins) + 1
                    row.last_checkin_date = today
                    row.last_reward_amount = reward
                    row.updated_at = timestamp

                    session.add(
                        ActivityCheckIn(
                            telegram_id=tg["id"],
                            checkin_date=today,
                            streak_day=new_streak,
                            reward_amount=reward,
                            created_at=timestamp,
                        )
                    )

                    if reward > 0 and not core.is_owner(user.telegram_id):
                        user.balance += reward
                        credited_now = reward
                        session.add(
                            core.Transaction(
                                telegram_id=user.telegram_id,
                                amount=reward,
                                operation_type="start_bonus",
                                description=f"Серия активности: день {new_streak}",
                                created_at=timestamp,
                            )
                        )

                    result = serialize_streak(row, today, user.balance, core.is_owner(user.telegram_id))

        return {
            "ok": True,
            "activity": result,
            "credited_now": int(credited_now),
            "already_checked_today": bool(already_checked_today),
        }
    except IntegrityError as exc:
        raise HTTPException(status_code=409, detail="Вход за сегодня уже засчитан") from exc


def register_activity(app) -> None:
    global _REGISTERED
    if _REGISTERED:
        return
    core.Base.metadata.create_all(core.engine)
    app.include_router(router)
    _REGISTERED = True
