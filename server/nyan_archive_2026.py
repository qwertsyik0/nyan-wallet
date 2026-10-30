"""Nyanik's Case Zero: a time-gated, persistent story archive.

The first record opens on October 30, 2026, at 22:00 Moscow time. The
following records appear over that evening. No Lapcoin balance is touched.
The answer and future record text never ship in the public JavaScript bundle.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Mapped, mapped_column

from . import backend_app as core


router = APIRouter()
_REGISTERED = False
UTC = timezone.utc
OPEN_AT = datetime(2026, 10, 30, 19, 0, tzinfo=UTC)  # 22:00 MSK
COOLDOWN = timedelta(minutes=5)
FIRST_PRIZE = 500


def now_utc() -> datetime:
    return datetime.now(UTC)


RECORDS = (
    {
        "id": 1,
        "title": "Снимок без номера",
        "subtitle": "Фотоплёнка, проявленная дважды",
        "at": OPEN_AT,
        "kind": "photo",
        "body": (
            "На обороте снимка стоит вчерашняя дата. В комнате нет мебели, "
            "кроме закрытой двери. Фотограф уверял, что пришёл туда один. "
            "На полу видны две тени."
        ),
        "note": "В журнале съёмки этой комнаты нет. На месте номера — пустота.",
    },
    {
        "id": 2,
        "title": "Лист без подписи",
        "subtitle": "Страница, не внесённая в дневник",
        "at": OPEN_AT + timedelta(hours=2),  # October 31, 00:00 MSK
        "kind": "letter",
        "body": (
            "«Он искал того, кто следил за ним, и никогда не замечал, "
            "что наблюдатель повторяет каждый его жест. В протоколе "
            "написано: перед дверью нет никого. После двери — тоже»."
        ),
        "note": "Последняя строка зачёркнута: «Не спрашивай, кто стоит напротив».",
    },
    {
        "id": 3,
        "title": "Показания неизвестного",
        "subtitle": "Аудиозапись · расшифровка",
        "at": OPEN_AT + timedelta(hours=4),  # October 31, 02:00 MSK
        "kind": "transcript",
        "body": (
            "«Я стоял один. Поднял руку — и кто-то сделал то же самое. "
            "Шагнул ближе — он шагнул навстречу. Но когда я отвернулся, "
            "он исчез. Я не слышал, как открывалась дверь»."
        ),
        "note": (
            "В конце протокола значится: «Посетитель №0». Имя Няника "
            "вписано другой рукой."
        ),
    },
    {
        "id": 4,
        "title": "Вопрос, которого не было",
        "subtitle": "Заключительный лист · дело №0",
        "at": OPEN_AT + timedelta(hours=6),  # October 31, 04:00 MSK
        "kind": "question",
        "body": (
            "На последнем листе нет подписи. Только одна фраза: "
            "«Назови то, что впускает второго человека в пустую комнату, "
            "хотя никто не проходит через дверь»."
        ),
        "note": "Ответ скрыт в трёх предыдущих записях. Одного слова достаточно.",
    },
)


class ArchiveCompletion(core.Base):
    __tablename__ = "nyan_archive_2026_completions"

    telegram_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.telegram_id", ondelete="CASCADE"),
        primary_key=True,
    )
    failed_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    solved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ArchiveFirstPrize(core.Base):
    """Single persistent winner. The primary key prevents duplicate payouts."""

    __tablename__ = "nyan_archive_2026_first_prize"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    telegram_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.telegram_id", ondelete="CASCADE"), nullable=False
    )
    awarded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class SolveInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    answer: str = Field(min_length=1, max_length=64)


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _normalize(value: str) -> str:
    return re.sub(r"[^а-яa-z]", "", value.casefold().replace("ё", "е"))


def _record_status(record: dict, *, now: datetime, preview: bool) -> dict:
    available = preview or now >= record["at"]
    result = {
        "id": record["id"],
        "title": record["title"],
        "subtitle": record["subtitle"],
        "opens_at": record["at"].isoformat(),
        "available": available,
    }
    if available:
        result.update(kind=record["kind"], body=record["body"], note=record["note"])
    return result


def _grant_first_prize_if_pending(session, now: datetime) -> int | None:
    """Award the true earliest non-owner solver, including pre-deployment solves."""
    if session.get(ArchiveFirstPrize, 1) is not None:
        return None

    query = (
        select(ArchiveCompletion.telegram_id)
        .where(ArchiveCompletion.solved_at.is_not(None))
        .order_by(ArchiveCompletion.solved_at, ArchiveCompletion.telegram_id)
        .limit(1)
    )
    if core.OWNER_TELEGRAM_ID is not None:
        query = query.where(ArchiveCompletion.telegram_id != core.OWNER_TELEGRAM_ID)
    first_id = session.scalar(query)
    if first_id is None:
        return None

    dialect = session.bind.dialect.name
    if dialect == "postgresql":
        stmt = pg_insert(ArchiveFirstPrize)
    elif dialect == "sqlite":
        stmt = sqlite_insert(ArchiveFirstPrize)
    else:
        raise RuntimeError("Unsupported database for Nyan Archive")
    claimed_id = session.execute(
        stmt.values(id=1, telegram_id=first_id, awarded_at=now)
        .on_conflict_do_nothing(index_elements=["id"])
        .returning(ArchiveFirstPrize.telegram_id)
    ).scalar_one_or_none()
    if claimed_id is None:
        return None

    user = session.scalar(
        select(core.User).where(core.User.telegram_id == claimed_id).with_for_update()
    )
    if user is None:
        raise RuntimeError("Победитель архива не найден в таблице пользователей")
    user.balance = int(user.balance or 0) + FIRST_PRIZE
    session.add(core.Transaction(
        telegram_id=claimed_id,
        amount=FIRST_PRIZE,
        operation_type="nyan_archive_first",
        description="Первое прохождение «Няник · Дело №0»",
        created_at=now,
    ))
    from .advanced_features import WalletNotification
    session.add(WalletNotification(
        telegram_id=claimed_id,
        kind="achievement",
        title="Первое прохождение · Дело №0",
        body=f"Вы первым разгадали дело Няника. На ваш кошелёк начислено {FIRST_PRIZE} 🐾.",
        is_read=False,
        created_at=now,
    ))
    return int(claimed_id)


def _state(now: datetime, telegram_id: int | None = None) -> dict:
    preview = telegram_id is not None and core.is_owner(telegram_id)
    completion = None
    first_winner_id = None
    if telegram_id is not None:
        with core.SessionLocal() as session:
            completion = session.get(ArchiveCompletion, telegram_id)
            first = session.get(ArchiveFirstPrize, 1)
            first_winner_id = first.telegram_id if first else None
    return {
        "ok": True,
        "server_now": now.isoformat(),
        "opens_at": OPEN_AT.isoformat(),
        "is_open": now >= OPEN_AT,
        "owner_preview": preview,
        "authenticated": telegram_id is not None,
        "records": [_record_status(record, now=now, preview=preview) for record in RECORDS],
        "solved": completion is not None and completion.solved_at is not None,
        "badge_awarded": completion is not None and completion.solved_at is not None,
        "first_prize_awarded": first_winner_id == telegram_id and telegram_id is not None,
        "retry_at": completion.retry_at.isoformat() if completion and completion.retry_at else None,
        "failed_attempts": completion.failed_attempts if completion else 0,
        "ending": (
            "Дело восстановлено. В учётной книге лавки найдено имя Няника. "
            "Дата посещения указана раньше даты открытия самой лавки. "
            "Под строкой «Кто оставил эти записи?» стоит пустая графа. "
            "Её пока никто не заполнил."
        ) if completion and completion.solved_at is not None else None,
    }


@router.get("/api/nyan-archive-2026/status")
def archive_status(
    x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data"),
):
    uid = None
    if x_telegram_init_data:
        uid = int(core.verify_init_data(x_telegram_init_data)["id"])
    return _state(now_utc(), uid)


@router.post("/api/nyan-archive-2026/solve")
def archive_solve(
    payload: SolveInput,
    x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data"),
):
    now = now_utc()
    tg = core.verify_init_data(x_telegram_init_data or "")
    uid = int(tg["id"])
    if now < RECORDS[-1]["at"] and not core.is_owner(uid):
        raise HTTPException(status_code=409, detail="Последний лист ещё не открыт")
    correct = _normalize(payload.answer) in {"зеркало", "отражение", "отражения"}
    with core.SessionLocal.begin() as session:
        user_values = dict(
            telegram_id=uid,
            username=tg.get("username"),
            first_name=tg.get("first_name") or "Пользователь",
            last_name=tg.get("last_name"),
            balance=0,
            created_at=now,
            last_seen_at=now,
        )
        dialect = session.bind.dialect.name
        if dialect == "postgresql":
            stmt = pg_insert(core.User).values(**user_values)
        elif dialect == "sqlite":
            stmt = sqlite_insert(core.User).values(**user_values)
        else:
            raise RuntimeError("Unsupported database for Nyan Archive")
        session.execute(stmt.on_conflict_do_nothing(index_elements=["telegram_id"]))
        user = session.scalar(select(core.User).where(core.User.telegram_id == uid).with_for_update())
        core.apply_telegram_profile(user, tg, now)

        if dialect == "postgresql":
            stmt = pg_insert(ArchiveCompletion).values(telegram_id=uid, failed_attempts=0)
        else:
            stmt = sqlite_insert(ArchiveCompletion).values(telegram_id=uid, failed_attempts=0)
        session.execute(stmt.on_conflict_do_nothing(index_elements=["telegram_id"]))
        row = session.scalar(
            select(ArchiveCompletion)
            .where(ArchiveCompletion.telegram_id == uid)
            .with_for_update()
        )
        if row.solved_at is not None:
            return {"ok": True, "correct": True, "already_solved": True}
        if row.retry_at is not None and _utc(row.retry_at) > now:
            raise HTTPException(status_code=429, detail="Подожди пять минут перед следующей попыткой")
        if correct:
            row.solved_at = now
            row.retry_at = None
            row.failed_attempts = 0
            session.flush()
            from .advanced_features import WalletNotification
            if not core.is_owner(uid):
                session.add(WalletNotification(
                    telegram_id=uid,
                    kind="achievement",
                    title="Значок «Тот, кто смотрел»",
                    body="Вы разгадали «Дело №0». Секретный значок добавлен в ваш профиль Nyan Wallet.",
                    is_read=False,
                    created_at=now,
                ))
                _grant_first_prize_if_pending(session, now)
        else:
            row.failed_attempts += 1
            if row.failed_attempts % 3 == 0:
                row.retry_at = now + COOLDOWN
    return {"ok": True, "correct": correct, "already_solved": False}


def register_nyan_archive_2026(app) -> None:
    global _REGISTERED
    if _REGISTERED:
        return
    core.Base.metadata.create_all(
        core.engine, tables=[ArchiveCompletion.__table__, ArchiveFirstPrize.__table__]
    )
    with core.SessionLocal.begin() as session:
        _grant_first_prize_if_pending(session, now_utc())
    app.include_router(router)
    _REGISTERED = True
