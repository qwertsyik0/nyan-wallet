from __future__ import annotations

from sqlalchemy import select, text

from server import backend_app as core
from server.daily_tasks import DailyTask, DailyTaskSeedState, now_utc

SEED_KEY = "default-daily-tasks-v2"
SEED_LOCK_ID = 920260921002

DEFAULT_TASKS_V2 = [
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
        "repeat_type": "once",
        "max_completions": None,
        "enabled": True,
        "sort_order": 40,
    },
]


def _seed_match(seed: dict):
    conditions = [
        DailyTask.task_type == seed["task_type"],
        DailyTask.action_type == seed.get("action_type"),
    ]
    if seed.get("action_value") is None:
        conditions.append(DailyTask.action_value.is_(None))
    else:
        conditions.append(DailyTask.action_value == seed.get("action_value"))
    return conditions


def register_daily_tasks_defaults_v2() -> None:
    timestamp = now_utc()
    with core.SessionLocal() as session:
        with session.begin():
            session.execute(text("SELECT pg_advisory_xact_lock(:lock_id)"), {"lock_id": SEED_LOCK_ID})
            if session.get(DailyTaskSeedState, SEED_KEY) is not None:
                return

            for seed in DEFAULT_TASKS_V2:
                task = session.scalar(
                    select(DailyTask)
                    .where(*_seed_match(seed))
                    .order_by(DailyTask.id.asc())
                    .with_for_update()
                )
                if task is None:
                    task = DailyTask(
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
                    )
                    session.add(task)
                    continue

                task.title = seed["title"]
                task.description = seed["description"]
                task.reward_type = seed["reward_type"]
                task.reward_amount = seed["reward_amount"]
                task.required_progress = seed["required_progress"]
                task.repeat_type = seed["repeat_type"]
                task.max_completions = seed.get("max_completions")
                task.enabled = seed["enabled"]
                task.sort_order = seed["sort_order"]
                task.deleted_at = None
                task.updated_at = timestamp

            session.add(DailyTaskSeedState(key=SEED_KEY, applied_at=timestamp))
