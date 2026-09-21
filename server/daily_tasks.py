from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, mapped_column

from server import backend_app as core

try:
    TASK_TZ = ZoneInfo("Europe/Moscow")
except Exception:
    TASK_TZ = timezone(timedelta(hours=3))

router = APIRouter()
_REGISTERED = False
TASK_TYPES = {"automatic", "manual", "link"}
REWARD_TYPES = {"lapcoins"}
REPEAT_TYPES = {"daily", "once"}
SERVER_VERIFIED_ACTION_TYPES = {"activity_check_in_confirmed", "referral_completed"}
DEFAULT_TASK_SEED_KEY = "default-daily-tasks-v1"
DEFAULT_DAILY_TASKS = [
    {
        "title": "Зайди в кошелёк",
        "description": "Открой Nyan Wallet сегодня и забери ежедневный бонус.",
        "task_type": "automatic",
        "action_type": "open_wallet",
        "action_value": None,
        "reward_type": "lapcoins",
        "reward_amount": 10,
        "required_progress": 1,
        "repeat_type": "daily",
        "max_completions": None,
        "enabled": True,
        "sort_order": 1,
    },
    {
        "title": "Активируй серию",
        "description": "Забери ежедневную серию активности через существующую механику Nyan Wallet.",
        "task_type": "automatic",
        "action_type": "activity_check_in_confirmed",
        "action_value": None,
        "reward_type": "lapcoins",
        "reward_amount": 5,
        "required_progress": 1,
        "repeat_type": "daily",
        "max_completions": None,
        "enabled": True,
        "sort_order": 5,
    },
    {
        "title": "Открой каталог",
        "description": "Посмотри, какие награды и товары сейчас доступны за лапкоины.",
        "task_type": "automatic",
        "action_type": "open_catalog",
        "action_value": None,
        "reward_type": "lapcoins",
        "reward_amount": 15,
        "required_progress": 1,
        "repeat_type": "daily",
        "max_completions": None,
        "enabled": True,
        "sort_order": 10,
    },
    {
        "title": "Напиши отзыв",
        "description": "Оставь отзыв о Нян Шопе или Nyan Wallet, затем отправь выполнение на проверку.",
        "task_type": "manual",
        "action_type": "custom_event",
        "action_value": "review_submit",
        "reward_type": "lapcoins",
        "reward_amount": 50,
        "required_progress": 1,
        "repeat_type": "daily",
        "max_completions": None,
        "enabled": True,
        "sort_order": 30,
    },
    {
        "title": "Пригласи 3 друзей",
        "description": "Пригласи 3 друзей по своему реферальному коду. Прогресс засчитывается по реальным рефералам.",
        "task_type": "automatic",
        "action_type": "referral_completed",
        "action_value": None,
        "reward_type": "lapcoins",
        "reward_amount": 170,
        "required_progress": 3,
        "repeat_type": "daily",
        "max_completions": None,
        "enabled": True,
        "sort_order": 40,
    },
]


class DailyTask(core.Base):
    __tablename__ = "daily_tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    task_type: Mapped[str] = mapped_column(String(24), nullable=False, default="automatic")
    action_type: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    action_value: Mapped[str | None] = mapped_column(String(255), nullable=True)
    reward_type: Mapped[str] = mapped_column(String(24), nullable=False, default="lapcoins")
    reward_amount: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    required_progress: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    repeat_type: Mapped[str] = mapped_column(String(16), nullable=False, default="daily")
    start_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    end_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    max_completions: Mapped[int | None] = mapped_column(Integer, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)


class UserTaskProgress(core.Base):
    __tablename__ = "user_task_progress"
    __table_args__ = (UniqueConstraint("telegram_id", "task_id", "period_key", name="uq_user_task_period"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.telegram_id", ondelete="CASCADE"), nullable=False, index=True)
    task_id: Mapped[int] = mapped_column(Integer, ForeignKey("daily_tasks.id", ondelete="CASCADE"), nullable=False, index=True)
    period_key: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    progress: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reward_claimed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    reward_claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    claimed_reward_amount: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    review_status: Mapped[str] = mapped_column(String(24), nullable=False, default="none", index=True)
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class DailyTaskSeedState(core.Base):
    __tablename__ = "daily_task_seed_state"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    applied_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class TaskCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=1200)
    task_type: str = Field(default="automatic", max_length=24)
    action_type: str | None = Field(default=None, max_length=64)
    action_value: str | None = Field(default=None, max_length=255)
    reward_type: str = Field(default="lapcoins", max_length=24)
    reward_amount: int = Field(ge=0, le=10_000_000)
    required_progress: int = Field(default=1, ge=1, le=1_000_000)
    repeat_type: str = Field(default="daily", max_length=16)
    start_at: datetime | None = None
    end_at: datetime | None = None
    max_completions: int | None = Field(default=None, ge=1, le=1_000_000)
    enabled: bool = True
    sort_order: int = Field(default=100, ge=-1_000_000, le=1_000_000)


class TaskUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=1200)
    task_type: str | None = Field(default=None, max_length=24)
    action_type: str | None = Field(default=None, max_length=64)
    action_value: str | None = Field(default=None, max_length=255)
    reward_type: str | None = Field(default=None, max_length=24)
    reward_amount: int | None = Field(default=None, ge=0, le=10_000_000)
    required_progress: int | None = Field(default=None, ge=1, le=1_000_000)
    repeat_type: str | None = Field(default=None, max_length=16)
    start_at: datetime | None = None
    end_at: datetime | None = None
    max_completions: int | None = Field(default=None, ge=1, le=1_000_000)
    enabled: bool | None = None
    sort_order: int | None = Field(default=None, ge=-1_000_000, le=1_000_000)


class TaskEventRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action_type: str = Field(min_length=1, max_length=64)
    action_value: str | None = Field(default=None, max_length=255)
    amount: int = Field(default=1, ge=1, le=10_000)


class ManualSubmitRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    note: str | None = Field(default=None, max_length=1000)


class ReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    note: str | None = Field(default=None, max_length=1000)


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def today_key(timestamp: datetime | None = None) -> str:
    source = timestamp or now_utc()
    if source.tzinfo is None:
        source = source.replace(tzinfo=timezone.utc)
    return source.astimezone(TASK_TZ).date().isoformat()


def today_date(timestamp: datetime | None = None):
    return datetime.fromisoformat(today_key(timestamp)).date()


def norm_dt(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def clean(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


def period_key(task: DailyTask, timestamp: datetime | None = None) -> str:
    return today_key(timestamp) if task.repeat_type == "daily" else "once"


def validate_values(payload: TaskCreateRequest | TaskUpdateRequest, partial: bool) -> dict:
    values = payload.model_dump(exclude_unset=partial)
    if "title" in values and values["title"] is not None:
        values["title"] = values["title"].strip()
        if not values["title"]:
            raise HTTPException(status_code=400, detail="Название задания не может быть пустым")
    if "description" in values:
        values["description"] = clean(values["description"])
    if "action_type" in values:
        values["action_type"] = clean(values["action_type"])
        if values["action_type"]:
            values["action_type"] = values["action_type"].lower()
    if "action_value" in values:
        values["action_value"] = clean(values["action_value"])
    if "task_type" in values and values["task_type"] is not None:
        values["task_type"] = values["task_type"].lower().strip()
        if values["task_type"] not in TASK_TYPES:
            raise HTTPException(status_code=400, detail="Некорректный тип задания")
    if "reward_type" in values and values["reward_type"] is not None:
        values["reward_type"] = values["reward_type"].lower().strip()
        if values["reward_type"] not in REWARD_TYPES:
            raise HTTPException(status_code=400, detail="Сейчас поддерживается только награда lapcoins")
    if "repeat_type" in values and values["repeat_type"] is not None:
        values["repeat_type"] = values["repeat_type"].lower().strip()
        if values["repeat_type"] not in REPEAT_TYPES:
            raise HTTPException(status_code=400, detail="Некорректный тип повтора")
    if "start_at" in values:
        values["start_at"] = norm_dt(values["start_at"])
    if "end_at" in values:
        values["end_at"] = norm_dt(values["end_at"])
    if values.get("start_at") and values.get("end_at") and values["end_at"] <= values["start_at"]:
        raise HTTPException(status_code=400, detail="Дата окончания должна быть позже даты начала")
    return values


def lifecycle(task: DailyTask, timestamp: datetime) -> str:
    if task.deleted_at:
        return "deleted"
    if not task.enabled:
        return "disabled"
    if task.start_at and norm_dt(task.start_at) > timestamp:
        return "future"
    if task.end_at and norm_dt(task.end_at) <= timestamp:
        return "expired"
    return "active"


def status_for(task: DailyTask, progress: UserTaskProgress | None, timestamp: datetime) -> str:
    state = lifecycle(task, timestamp)
    if state != "active":
        return state
    if progress is None:
        return "available"
    if progress.review_status == "pending_review":
        return "awaiting_confirmation"
    if progress.review_status == "rejected":
        return "available"
    if progress.completed and progress.reward_claimed:
        return "reward_claimed"
    if progress.completed:
        return "reward_available"
    if progress.progress > 0:
        return "in_progress"
    return "available"


def serialize_task(task: DailyTask, progress: UserTaskProgress | None, timestamp: datetime, owner: bool = False) -> dict:
    required = max(1, int(task.required_progress or 1))
    current = min(required, int(progress.progress if progress else 0))
    item = {
        "id": task.id,
        "title": task.title,
        "description": task.description,
        "task_type": task.task_type,
        "action_type": task.action_type,
        "action_value": task.action_value,
        "reward_type": task.reward_type,
        "reward_amount": int(task.reward_amount or 0),
        "required_progress": required,
        "progress": current,
        "repeat_type": task.repeat_type,
        "start_at": task.start_at.isoformat() if task.start_at else None,
        "end_at": task.end_at.isoformat() if task.end_at else None,
        "max_completions": task.max_completions,
        "enabled": bool(task.enabled),
        "sort_order": int(task.sort_order or 0),
        "status": status_for(task, progress, timestamp),
        "completed": bool(progress.completed) if progress else False,
        "reward_claimed": bool(progress.reward_claimed) if progress else False,
        "review_status": progress.review_status if progress else "none",
        "review_note": progress.review_note if progress else None,
        "completed_at": progress.completed_at.isoformat() if progress and progress.completed_at else None,
        "reward_claimed_at": progress.reward_claimed_at.isoformat() if progress and progress.reward_claimed_at else None,
    }
    if owner:
        item["lifecycle"] = lifecycle(task, timestamp)
        item["created_at"] = task.created_at.isoformat()
        item["updated_at"] = task.updated_at.isoformat()
        item["deleted_at"] = task.deleted_at.isoformat() if task.deleted_at else None
    return item


def ensure_user(session, tg_user: dict, timestamp: datetime) -> core.User:
    user = session.scalar(select(core.User).where(core.User.telegram_id == tg_user["id"]).with_for_update())
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


def claimed_count(session, task_id: int) -> int:
    return int(session.scalar(select(func.count()).select_from(UserTaskProgress).where(UserTaskProgress.task_id == task_id, UserTaskProgress.reward_claimed.is_(True))) or 0)


def get_progress(session, user: core.User, task: DailyTask, timestamp: datetime) -> UserTaskProgress:
    key = period_key(task, timestamp)
    progress = session.scalar(
        select(UserTaskProgress).where(
            UserTaskProgress.telegram_id == user.telegram_id,
            UserTaskProgress.task_id == task.id,
            UserTaskProgress.period_key == key,
        ).with_for_update()
    )
    if progress:
        return progress
    progress = UserTaskProgress(
        telegram_id=user.telegram_id,
        task_id=task.id,
        period_key=key,
        progress=0,
        completed=False,
        completed_at=None,
        reward_claimed=False,
        reward_claimed_at=None,
        claimed_reward_amount=0,
        review_status="none",
        review_note=None,
        reviewed_at=None,
        created_at=timestamp,
        updated_at=timestamp,
    )
    session.add(progress)
    session.flush()
    return progress


def award_task(session, user: core.User, task: DailyTask, progress: UserTaskProgress, timestamp: datetime) -> int:
    if not progress.completed or progress.reward_claimed or lifecycle(task, timestamp) != "active":
        return 0
    if task.max_completions is not None and claimed_count(session, task.id) >= int(task.max_completions):
        return 0
    amount = int(task.reward_amount or 0)
    credited = 0
    if amount > 0 and task.reward_type == "lapcoins" and not core.is_owner(user.telegram_id):
        user.balance += amount
        credited = amount
        session.add(core.Transaction(
            telegram_id=user.telegram_id,
            amount=amount,
            operation_type="daily_task",
            description=f"Ежедневное задание: {task.title}",
            created_at=timestamp,
        ))
    progress.reward_claimed = True
    progress.reward_claimed_at = timestamp
    progress.claimed_reward_amount = credited
    progress.updated_at = timestamp
    return credited


def record_event_for_session(session, user: core.User, action_type: str, timestamp: datetime | None = None, action_value: str | None = None, amount: int = 1) -> dict:
    timestamp = timestamp or now_utc()
    action_type = action_type.strip().lower()
    action_value = clean(action_value)
    amount = max(1, min(int(amount), 10_000))
    if not action_type:
        return {"changed": [], "credited_total": 0}
    tasks = session.scalars(
        select(DailyTask).where(
            DailyTask.deleted_at.is_(None),
            DailyTask.enabled.is_(True),
            DailyTask.task_type == "automatic",
            DailyTask.action_type == action_type,
        ).with_for_update()
    ).all()
    changed = []
    credited_total = 0
    for task in tasks:
        if lifecycle(task, timestamp) != "active":
            continue
        if task.action_value and action_value != task.action_value:
            continue
        progress = get_progress(session, user, task, timestamp)
        if progress.reward_claimed or progress.review_status == "pending_review":
            changed.append({"task_id": task.id, "credited": 0, "status": status_for(task, progress, timestamp)})
            continue
        if progress.review_status == "rejected":
            progress.review_status = "none"
            progress.review_note = None
        required = max(1, int(task.required_progress or 1))
        progress.progress = min(required, max(0, int(progress.progress)) + amount)
        progress.updated_at = timestamp
        if progress.progress >= required:
            progress.completed = True
            progress.completed_at = progress.completed_at or timestamp
        credited = award_task(session, user, task, progress, timestamp)
        credited_total += credited
        changed.append({"task_id": task.id, "credited": credited, "status": status_for(task, progress, timestamp)})
    return {"changed": changed, "credited_total": credited_total}


def sync_verified_tasks(session, user: core.User, timestamp: datetime) -> dict:
    tasks = session.scalars(
        select(DailyTask).where(
            DailyTask.deleted_at.is_(None),
            DailyTask.enabled.is_(True),
            DailyTask.task_type == "automatic",
            DailyTask.action_type.in_(SERVER_VERIFIED_ACTION_TYPES),
        ).with_for_update()
    ).all()
    if not tasks:
        return {"changed": [], "credited_total": 0}

    activity_done: bool | None = None
    referral_count: int | None = None
    changed = []
    credited_total = 0

    for task in tasks:
        if lifecycle(task, timestamp) != "active":
            continue

        verified_amount = 0
        if task.action_type == "activity_check_in_confirmed":
            if activity_done is None:
                try:
                    from server.activity import ActivityCheckIn
                    activity_done = session.scalar(
                        select(ActivityCheckIn.id).where(
                            ActivityCheckIn.telegram_id == user.telegram_id,
                            ActivityCheckIn.checkin_date == today_date(timestamp),
                        )
                    ) is not None
                except Exception:
                    activity_done = False
            verified_amount = 1 if activity_done else 0
        elif task.action_type == "referral_completed":
            if referral_count is None:
                try:
                    from server.advanced_features import Referral
                    referral_count = int(session.scalar(
                        select(func.count()).select_from(Referral).where(Referral.inviter_id == user.telegram_id)
                    ) or 0)
                except Exception:
                    referral_count = 0
            verified_amount = referral_count

        if verified_amount <= 0:
            continue

        progress = get_progress(session, user, task, timestamp)
        if progress.reward_claimed or progress.review_status == "pending_review":
            changed.append({"task_id": task.id, "credited": 0, "status": status_for(task, progress, timestamp)})
            continue
        if progress.review_status == "rejected":
            progress.review_status = "none"
            progress.review_note = None
        required = max(1, int(task.required_progress or 1))
        progress.progress = min(required, max(int(progress.progress), int(verified_amount)))
        progress.updated_at = timestamp
        if progress.progress >= required:
            progress.completed = True
            progress.completed_at = progress.completed_at or timestamp
        credited = award_task(session, user, task, progress, timestamp)
        credited_total += credited
        changed.append({"task_id": task.id, "credited": credited, "status": status_for(task, progress, timestamp)})

    return {"changed": changed, "credited_total": credited_total}


def record_task_event(telegram_id: int, action_type: str, action_value: str | None = None, amount: int = 1) -> dict:
    action_type = action_type.strip().lower()
    if action_type in SERVER_VERIFIED_ACTION_TYPES:
        raise HTTPException(status_code=403, detail="Это событие подтверждается сервером")
    timestamp = now_utc()
    with core.SessionLocal() as session:
        with session.begin():
            user = session.scalar(select(core.User).where(core.User.telegram_id == telegram_id).with_for_update())
            if user is None:
                raise HTTPException(status_code=404, detail="Пользователь не найден")
            return record_event_for_session(session, user, action_type, timestamp, action_value, amount)


def owner_stats_for(session) -> dict[int, dict]:
    rows = session.scalars(select(UserTaskProgress)).all()
    result: dict[int, dict] = {}
    for row in rows:
        data = result.setdefault(row.task_id, {"progress_rows": 0, "completed": 0, "reward_claimed": 0, "pending_review": 0})
        data["progress_rows"] += 1
        if row.completed:
            data["completed"] += 1
        if row.reward_claimed:
            data["reward_claimed"] += 1
        if row.review_status == "pending_review":
            data["pending_review"] += 1
    return result


def audit_safe(session, action: str, target: int | None, details: str) -> None:
    try:
        from server.extended_features import audit
        audit(session, action, target, details)
    except Exception:
        return


def task_seed_match(seed: dict):
    conditions = [
        DailyTask.task_type == seed["task_type"],
        DailyTask.action_type == seed.get("action_type"),
        DailyTask.repeat_type == seed["repeat_type"],
    ]
    if seed.get("action_value") is None:
        conditions.append(DailyTask.action_value.is_(None))
    else:
        conditions.append(DailyTask.action_value == seed.get("action_value"))
    return conditions


def seed_default_daily_tasks() -> None:
    timestamp = now_utc()
    with core.SessionLocal() as session:
        with session.begin():
            session.execute(text("SELECT pg_advisory_xact_lock(:lock_id)"), {"lock_id": 920260921001})
            if session.get(DailyTaskSeedState, DEFAULT_TASK_SEED_KEY) is not None:
                return

            for seed in DEFAULT_DAILY_TASKS:
                existing = session.scalar(
                    select(DailyTask).where(*task_seed_match(seed)).order_by(DailyTask.id.asc()).with_for_update()
                )
                if existing is None:
                    session.add(DailyTask(
                        title=seed["title"],
                        description=seed["description"],
                        task_type=seed["task_type"],
                        action_type=seed["action_type"],
                        action_value=seed.get("action_value"),
                        reward_type=seed["reward_type"],
                        reward_amount=seed["reward_amount"],
                        required_progress=seed["required_progress"],
                        repeat_type=seed["repeat_type"],
                        start_at=None,
                        end_at=None,
                        max_completions=seed.get("max_completions"),
                        enabled=seed["enabled"],
                        sort_order=seed["sort_order"],
                        created_at=timestamp,
                        updated_at=timestamp,
                        deleted_at=None,
                    ))
                    continue

                existing.title = seed["title"]
                existing.description = seed["description"]
                existing.reward_type = seed["reward_type"]
                existing.reward_amount = seed["reward_amount"]
                existing.required_progress = seed["required_progress"]
                existing.max_completions = seed.get("max_completions")
                existing.enabled = seed["enabled"]
                existing.sort_order = seed["sort_order"]
                existing.deleted_at = None
                existing.updated_at = timestamp

            session.add(DailyTaskSeedState(key=DEFAULT_TASK_SEED_KEY, applied_at=timestamp))


@router.get("/api/tasks")
async def list_tasks(x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data")):
    tg_user = core.verify_init_data(x_telegram_init_data or "")
    timestamp = now_utc()
    with core.SessionLocal() as session:
        with session.begin():
            user = ensure_user(session, tg_user, timestamp)
            record_event_for_session(session, user, "open_wallet", timestamp)
            sync_verified_tasks(session, user, timestamp)
            tasks = session.scalars(select(DailyTask).where(DailyTask.deleted_at.is_(None)).order_by(DailyTask.sort_order.asc(), DailyTask.id.asc())).all()
            rows = session.scalars(select(UserTaskProgress).where(UserTaskProgress.telegram_id == user.telegram_id)).all()
            by_key = {(row.task_id, row.period_key): row for row in rows}
            visible = []
            for task in tasks:
                state = lifecycle(task, timestamp)
                if state == "disabled":
                    continue
                progress = by_key.get((task.id, period_key(task, timestamp)))
                item = serialize_task(task, progress, timestamp)
                if state in {"active", "future"} or item["status"] in {"reward_claimed", "awaiting_confirmation"}:
                    visible.append(item)
            total = len([item for item in visible if item["status"] not in {"expired", "disabled"}])
            completed = len([item for item in visible if item["status"] == "reward_claimed"])
            balance = user.balance
    return {"ok": True, "period": today_key(timestamp), "balance": balance, "tasks": visible, "summary": {"completed": completed, "total": total}}


@router.post("/api/tasks/events")
async def task_event(payload: TaskEventRequest, x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data")):
    tg_user = core.verify_init_data(x_telegram_init_data or "")
    action_type = payload.action_type.strip().lower()
    if action_type in SERVER_VERIFIED_ACTION_TYPES:
        raise HTTPException(status_code=403, detail="Это событие подтверждается сервером")
    timestamp = now_utc()
    with core.SessionLocal() as session:
        with session.begin():
            user = ensure_user(session, tg_user, timestamp)
            result = record_event_for_session(session, user, action_type, timestamp, payload.action_value, payload.amount)
            balance = user.balance
    return {"ok": True, "event": action_type, "result": result, "balance": balance}


@router.post("/api/tasks/{task_id}/submit")
async def submit_manual_task(task_id: int, payload: ManualSubmitRequest, x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data")):
    tg_user = core.verify_init_data(x_telegram_init_data or "")
    timestamp = now_utc()
    try:
        with core.SessionLocal() as session:
            with session.begin():
                user = ensure_user(session, tg_user, timestamp)
                task = session.scalar(select(DailyTask).where(DailyTask.id == task_id, DailyTask.deleted_at.is_(None)).with_for_update())
                if task is None:
                    raise HTTPException(status_code=404, detail="Задание не найдено")
                if lifecycle(task, timestamp) != "active":
                    raise HTTPException(status_code=409, detail="Задание сейчас недоступно")
                if task.task_type not in {"manual", "link"}:
                    raise HTTPException(status_code=400, detail="Это задание подтверждается автоматически")
                progress = get_progress(session, user, task, timestamp)
                if progress.reward_claimed:
                    raise HTTPException(status_code=409, detail="Награда уже получена")
                if progress.review_status == "pending_review":
                    raise HTTPException(status_code=409, detail="Заявка уже ожидает подтверждения")
                progress.progress = max(1, progress.progress)
                progress.completed = False
                progress.completed_at = None
                progress.review_status = "pending_review"
                progress.review_note = clean(payload.note)
                progress.reviewed_at = None
                progress.updated_at = timestamp
                return {"ok": True, "task": serialize_task(task, progress, timestamp)}
    except IntegrityError as exc:
        raise HTTPException(status_code=409, detail="Заявка уже создана") from exc


@router.get("/api/owner/tasks")
async def owner_tasks(x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data")):
    tg_user = core.verify_init_data(x_telegram_init_data or "")
    core.require_owner(tg_user)
    timestamp = now_utc()
    with core.SessionLocal() as session:
        tasks = session.scalars(select(DailyTask).where(DailyTask.deleted_at.is_(None)).order_by(DailyTask.sort_order.asc(), DailyTask.id.desc())).all()
        stats = owner_stats_for(session)
        items = []
        for task in tasks:
            item = serialize_task(task, None, timestamp, owner=True)
            item["stats"] = stats.get(task.id, {"progress_rows": 0, "completed": 0, "reward_claimed": 0, "pending_review": 0})
            items.append(item)
    return {"ok": True, "tasks": items}


@router.post("/api/owner/tasks")
async def owner_create_task(payload: TaskCreateRequest, x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data")):
    tg_user = core.verify_init_data(x_telegram_init_data or "")
    core.require_owner(tg_user)
    timestamp = now_utc()
    values = validate_values(payload, partial=False)
    task = DailyTask(
        title=values["title"], description=values.get("description"), task_type=values.get("task_type", "automatic"),
        action_type=values.get("action_type"), action_value=values.get("action_value"), reward_type=values.get("reward_type", "lapcoins"),
        reward_amount=values.get("reward_amount", 0), required_progress=values.get("required_progress", 1), repeat_type=values.get("repeat_type", "daily"),
        start_at=values.get("start_at"), end_at=values.get("end_at"), max_completions=values.get("max_completions"),
        enabled=values.get("enabled", True), sort_order=values.get("sort_order", 100), created_at=timestamp, updated_at=timestamp, deleted_at=None,
    )
    with core.SessionLocal() as session:
        with session.begin():
            session.add(task)
            session.flush()
            audit_safe(session, "task_created", None, f"#{task.id} · {task.title} · +{task.reward_amount} 🐾")
            item = serialize_task(task, None, timestamp, owner=True)
    return {"ok": True, "task": item}


@router.post("/api/owner/tasks/{task_id}")
async def owner_update_task(task_id: int, payload: TaskUpdateRequest, x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data")):
    tg_user = core.verify_init_data(x_telegram_init_data or "")
    core.require_owner(tg_user)
    timestamp = now_utc()
    values = validate_values(payload, partial=True)
    with core.SessionLocal() as session:
        with session.begin():
            task = session.scalar(select(DailyTask).where(DailyTask.id == task_id, DailyTask.deleted_at.is_(None)).with_for_update())
            if task is None:
                raise HTTPException(status_code=404, detail="Задание не найдено")
            for key, value in values.items():
                setattr(task, key, value)
            if task.start_at and task.end_at and norm_dt(task.end_at) <= norm_dt(task.start_at):
                raise HTTPException(status_code=400, detail="Дата окончания должна быть позже даты начала")
            task.updated_at = timestamp
            audit_safe(session, "task_updated", None, f"#{task.id} · {task.title}")
            item = serialize_task(task, None, timestamp, owner=True)
    return {"ok": True, "task": item}


@router.post("/api/owner/tasks/{task_id}/toggle")
async def owner_toggle_task(task_id: int, x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data")):
    tg_user = core.verify_init_data(x_telegram_init_data or "")
    core.require_owner(tg_user)
    timestamp = now_utc()
    with core.SessionLocal() as session:
        with session.begin():
            task = session.scalar(select(DailyTask).where(DailyTask.id == task_id, DailyTask.deleted_at.is_(None)).with_for_update())
            if task is None:
                raise HTTPException(status_code=404, detail="Задание не найдено")
            task.enabled = not task.enabled
            task.updated_at = timestamp
            audit_safe(session, "task_toggled", None, f"#{task.id} · {'включено' if task.enabled else 'отключено'}")
            item = serialize_task(task, None, timestamp, owner=True)
    return {"ok": True, "task": item}


@router.post("/api/owner/tasks/{task_id}/delete")
async def owner_delete_task(task_id: int, x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data")):
    tg_user = core.verify_init_data(x_telegram_init_data or "")
    core.require_owner(tg_user)
    timestamp = now_utc()
    with core.SessionLocal() as session:
        with session.begin():
            task = session.scalar(select(DailyTask).where(DailyTask.id == task_id, DailyTask.deleted_at.is_(None)).with_for_update())
            if task is None:
                raise HTTPException(status_code=404, detail="Задание не найдено")
            task.enabled = False
            task.deleted_at = timestamp
            task.updated_at = timestamp
            audit_safe(session, "task_deleted", None, f"#{task.id} · {task.title}")
    return {"ok": True, "deleted": task_id}


@router.get("/api/owner/tasks/reviews")
async def owner_task_reviews(x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data")):
    tg_user = core.verify_init_data(x_telegram_init_data or "")
    core.require_owner(tg_user)
    timestamp = now_utc()
    with core.SessionLocal() as session:
        rows = session.execute(
            select(UserTaskProgress, DailyTask, core.User)
            .join(DailyTask, DailyTask.id == UserTaskProgress.task_id)
            .join(core.User, core.User.telegram_id == UserTaskProgress.telegram_id)
            .where(UserTaskProgress.review_status == "pending_review")
            .order_by(UserTaskProgress.id.asc()).limit(100)
        ).all()
        items = [{
            "progress_id": progress.id,
            "task": serialize_task(task, progress, timestamp),
            "telegram_id": user.telegram_id,
            "username": user.username,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "note": progress.review_note,
            "created_at": progress.created_at.isoformat(),
            "updated_at": progress.updated_at.isoformat(),
        } for progress, task, user in rows]
    return {"ok": True, "items": items}


@router.post("/api/owner/tasks/reviews/{progress_id}/approve")
async def owner_approve_review(progress_id: int, payload: ReviewRequest, x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data")):
    tg_user = core.verify_init_data(x_telegram_init_data or "")
    core.require_owner(tg_user)
    timestamp = now_utc()
    with core.SessionLocal() as session:
        with session.begin():
            progress = session.scalar(select(UserTaskProgress).where(UserTaskProgress.id == progress_id).with_for_update())
            if progress is None:
                raise HTTPException(status_code=404, detail="Заявка не найдена")
            if progress.review_status != "pending_review":
                raise HTTPException(status_code=409, detail="Заявка уже обработана")
            task = session.scalar(select(DailyTask).where(DailyTask.id == progress.task_id).with_for_update())
            user = session.scalar(select(core.User).where(core.User.telegram_id == progress.telegram_id).with_for_update())
            if task is None or user is None:
                raise HTTPException(status_code=404, detail="Задание или пользователь не найдены")
            progress.progress = max(progress.progress, max(1, task.required_progress))
            progress.completed = True
            progress.completed_at = progress.completed_at or timestamp
            progress.review_status = "approved"
            progress.review_note = clean(payload.note) or progress.review_note
            progress.reviewed_at = timestamp
            progress.updated_at = timestamp
            credited = award_task(session, user, task, progress, timestamp)
            audit_safe(session, "task_approved", user.telegram_id, f"#{task.id} · {task.title} · +{credited} 🐾")
            balance = user.balance
    return {"ok": True, "progress_id": progress_id, "credited": credited, "balance": balance}


@router.post("/api/owner/tasks/reviews/{progress_id}/reject")
async def owner_reject_review(progress_id: int, payload: ReviewRequest, x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data")):
    tg_user = core.verify_init_data(x_telegram_init_data or "")
    core.require_owner(tg_user)
    timestamp = now_utc()
    with core.SessionLocal() as session:
        with session.begin():
            progress = session.scalar(select(UserTaskProgress).where(UserTaskProgress.id == progress_id).with_for_update())
            if progress is None:
                raise HTTPException(status_code=404, detail="Заявка не найдена")
            if progress.review_status != "pending_review":
                raise HTTPException(status_code=409, detail="Заявка уже обработана")
            task = session.get(DailyTask, progress.task_id)
            progress.review_status = "rejected"
            progress.review_note = clean(payload.note) or progress.review_note
            progress.reviewed_at = timestamp
            progress.updated_at = timestamp
            audit_safe(session, "task_rejected", progress.telegram_id, f"#{progress.task_id} · {task.title if task else 'задание'}")
    return {"ok": True, "progress_id": progress_id, "status": "rejected"}


def register_daily_tasks(app) -> None:
    global _REGISTERED
    if _REGISTERED:
        return
    core.Base.metadata.create_all(core.engine)
    seed_default_daily_tasks()
    app.include_router(router)
    _REGISTERED = True
