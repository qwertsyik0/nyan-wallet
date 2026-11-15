"""Unified Nyan ID experience from verified ecosystem activity.

XP is separate from lapcoins and the existing wallet economy rank.
Only completed server-side events count. Quest, Games and Shop award
events are recorded by the wallet owner after confirming completion.
"""
from __future__ import annotations

import re
import hashlib
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, UniqueConstraint, column, func, inspect, or_, select, table, text, union_all
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, mapped_column

from . import backend_app as core
from .activity import ActivityCheckIn
from .achievements import AchievementUnlock
from .daily_tasks import UserTaskProgress
from .interactive_ideas import InteractiveIdea


router = APIRouter()
_REGISTERED = False

# Fixed point values: callers cannot choose XP amounts.
XP_CHECKIN = 5
XP_TASK = 3
XP_ACHIEVEMENT = 12
XP_STUDIO_APPROVAL = 60
EXTERNAL_XP = {
    "quest_completed": ("quest", 70),
    "game_completed": ("games", 30),
    "shop_purchase": ("shop", 20),
}


class NyanExperienceEvent(core.Base):
    __tablename__ = "nyan_experience_events"
    __table_args__ = (
        UniqueConstraint(
            "telegram_id", "kind", "event_key",
            name="uq_nyan_experience_user_kind_event",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telegram_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.telegram_id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    event_key: Mapped[str] = mapped_column(String(96), nullable=False)
    xp: Mapped[int] = mapped_column(Integer, nullable=False)
    awarded_by: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
    )


class ExperienceGrantRequest(BaseModel):
    telegram_id: int = Field(gt=0)
    kind: Literal["quest_completed", "game_completed", "shop_purchase"]
    event_key: str = Field(min_length=3, max_length=96)


def level_for_xp(total_xp: int) -> dict:
    """Monotonically increasing levels: 100 XP, then +25 XP per step."""
    xp = max(0, int(total_xp))
    level = 1
    lower = 0
    needed = 100
    while xp >= lower + needed:
        lower += needed
        level += 1
        needed += 25
    earned_in_level = xp - lower
    return {
        "level": level,
        "total_xp": xp,
        "current_level_xp": earned_in_level,
        "next_level_xp": needed,
        "remaining_xp": needed - earned_in_level,
        "progress_percent": round(100 * earned_in_level / needed),
    }


def experience_for_user(session, telegram_id: int) -> dict:
    """Read-only aggregate of completed events, with no balance-derived XP."""
    uid = int(telegram_id)

    checkins = int(session.scalar(
        select(func.count()).select_from(ActivityCheckIn)
        .where(ActivityCheckIn.telegram_id == uid)
    ) or 0)
    tasks = int(session.scalar(
        select(func.count()).select_from(UserTaskProgress)
        .where(
            UserTaskProgress.telegram_id == uid,
            UserTaskProgress.reward_claimed.is_(True),
        )
    ) or 0)
    achievements = int(session.scalar(
        select(func.count()).select_from(AchievementUnlock)
        .where(AchievementUnlock.telegram_id == uid)
    ) or 0)
    ideas = int(session.scalar(
        select(func.count()).select_from(InteractiveIdea)
        .where(
            InteractiveIdea.telegram_id == uid,
            InteractiveIdea.status == "approved",
        )
    ) or 0)

    # Mafia is optional and may run in a separate deployment. Count only
    # genuinely finished rounds with a winner, never mere registration.
    # An absent game schema must not prevent the Nyan ID card from loading.
    inspector = inspect(session.get_bind())
    mafia_rounds = 0
    if (inspector.has_table("nyan_mafia_rounds")
            and inspector.has_table("nyan_mafia_players")):
        mafia_rounds = int(session.scalar(text(
            "SELECT count(*) FROM nyan_mafia_players p "
            "JOIN nyan_mafia_rounds r ON r.id = p.round_id "
            "WHERE p.telegram_id = :uid AND r.phase = 'finished' "
            "AND r.winner IS NOT NULL"
        ), {"uid": uid}) or 0)

    totals = {
        "wallet": [checkins * XP_CHECKIN + tasks * XP_TASK
                   + achievements * XP_ACHIEVEMENT, checkins + tasks + achievements],
        "games": [mafia_rounds * 30, mafia_rounds],
        "quest": [0, 0],
        "shop": [0, 0],
        "studio": [ideas * XP_STUDIO_APPROVAL, ideas],
    }

    external = session.execute(
        select(
            NyanExperienceEvent.kind,
            func.coalesce(func.sum(NyanExperienceEvent.xp), 0),
            func.count(NyanExperienceEvent.id),
        )
        .where(NyanExperienceEvent.telegram_id == uid)
        .group_by(NyanExperienceEvent.kind)
    ).all()
    for kind, xp, count in external:
        rule = EXTERNAL_XP.get(kind)
        if rule is None:
            continue
        source = rule[0]
        totals[source][0] += int(xp)
        totals[source][1] += int(count)

    labels = (
        ("wallet", "Nyan Wallet"),
        ("games", "Nyan Games"),
        ("quest", "Nyan Quest"),
        ("shop", "Nyan Shop"),
        ("studio", "Nyan Studio"),
    )
    sources = [
        {"key": key, "label": label, "xp": totals[key][0], "events": totals[key][1]}
        for key, label in labels
    ]
    summary = level_for_xp(sum(source["xp"] for source in sources))
    summary["sources"] = sources
    return summary



def _leaderboard_query(session, current_id: int, limit: int = 20):
    """Aggregate the same XP sources as an individual Nyan ID, for all users.

    Each source is grouped before UNION ALL, so even large histories cannot
    produce Cartesian products. Ties share a place (RANK); display order is
    stable by the user ID. The viewer is included even when outside the top 20.
    """
    sources = [
        select(
            ActivityCheckIn.telegram_id.label("telegram_id"),
            (func.count(ActivityCheckIn.id) * XP_CHECKIN).label("xp"),
        ).group_by(ActivityCheckIn.telegram_id),
        select(
            UserTaskProgress.telegram_id.label("telegram_id"),
            (func.count(UserTaskProgress.id) * XP_TASK).label("xp"),
        ).where(UserTaskProgress.reward_claimed.is_(True))
        .group_by(UserTaskProgress.telegram_id),
        select(
            AchievementUnlock.telegram_id.label("telegram_id"),
            (func.count(AchievementUnlock.id) * XP_ACHIEVEMENT).label("xp"),
        ).group_by(AchievementUnlock.telegram_id),
        select(
            InteractiveIdea.telegram_id.label("telegram_id"),
            (func.count(InteractiveIdea.id) * XP_STUDIO_APPROVAL).label("xp"),
        ).where(InteractiveIdea.status == "approved")
        .group_by(InteractiveIdea.telegram_id),
        select(
            NyanExperienceEvent.telegram_id.label("telegram_id"),
            func.sum(NyanExperienceEvent.xp).label("xp"),
        ).where(NyanExperienceEvent.kind.in_(tuple(EXTERNAL_XP)))
        .group_by(NyanExperienceEvent.telegram_id),
    ]

    # Mafia is an optional module. It is counted only when both production
    # tables are present and only when there is an actual game result.
    inspector = inspect(session.get_bind())
    if (inspector.has_table("nyan_mafia_rounds")
            and inspector.has_table("nyan_mafia_players")):
        players = table(
            "nyan_mafia_players",
            column("round_id"), column("telegram_id"),
        )
        rounds = table(
            "nyan_mafia_rounds",
            column("id"), column("phase"), column("winner"),
        )
        sources.append(
            select(
                players.c.telegram_id.label("telegram_id"),
                (func.count() * 30).label("xp"),
            )
            .select_from(players.join(rounds, players.c.round_id == rounds.c.id))
            .where(rounds.c.phase == "finished", rounds.c.winner.is_not(None))
            .group_by(players.c.telegram_id)
        )

    events = union_all(*sources).subquery("xp_events")
    totals = (
        select(
            events.c.telegram_id.label("telegram_id"),
            func.sum(events.c.xp).label("xp"),
        )
        .group_by(events.c.telegram_id)
        .having(func.sum(events.c.xp) > 0)
        .subquery("xp_totals")
    )
    ranked = (
        select(
            totals.c.telegram_id,
            totals.c.xp,
            core.User.username,
            func.rank().over(order_by=totals.c.xp.desc()).label("place"),
            func.row_number().over(
                order_by=(totals.c.xp.desc(), totals.c.telegram_id.asc())
            ).label("row_number"),
        )
        .join(core.User, core.User.telegram_id == totals.c.telegram_id)
        .subquery("xp_ranked")
    )
    query = (
        select(
            ranked.c.telegram_id, ranked.c.username, ranked.c.xp,
            ranked.c.place, ranked.c.row_number,
        )
        .where(or_(
            ranked.c.row_number <= limit,
            ranked.c.telegram_id == int(current_id),
        ))
        .order_by(ranked.c.row_number)
    )
    return session.execute(query).all()


def _leaderboard_label(telegram_id: int, username: str | None) -> str:
    """Use public @username if present, otherwise a stable anonymous nickname.

    Never expose Telegram IDs, real names or wallet data to other users.
    """
    if username and re.fullmatch(r"[A-Za-z0-9_]{5,32}", username):
        return "@" + username
    digest = hashlib.blake2s(
        f"nyan-leaderboard:v1:{int(telegram_id)}".encode("ascii"),
        digest_size=5,
    ).hexdigest().upper()
    return "Участник " + digest[:8]


def leaderboard_for_user(session, telegram_id: int, limit: int = 20) -> dict:
    rows = _leaderboard_query(session, telegram_id, limit)
    leaders = []
    own = {"place": None, "xp": 0, "level": 1}
    for row in rows:
        uid = int(row.telegram_id)
        xp = max(0, int(row.xp))
        entry = {
            "place": int(row.place),
            "name": _leaderboard_label(uid, row.username),
            "xp": xp,
            "level": level_for_xp(xp)["level"],
            "is_me": uid == int(telegram_id),
        }
        if int(row.row_number) <= limit:
            leaders.append(entry)
        if uid == int(telegram_id):
            own = {"place": int(row.place), "xp": xp,
                   "level": entry["level"]}
    return {"leaders": leaders, "me": own}


@router.get("/api/nyan-id/leaderboard")
def nyan_id_leaderboard(
    x_telegram_init_data: str | None = Header(
        default=None, alias="X-Telegram-Init-Data",
    ),
):
    """Private authenticated leaderboard, top 20 and viewer position only."""
    telegram = core.verify_init_data(x_telegram_init_data or "")
    with core.SessionLocal() as session:
        result = leaderboard_for_user(session, int(telegram["id"]))
    return {"ok": True, **result}


@router.post("/api/owner/nyan-id/experience")
def award_verified_experience(
    payload: ExperienceGrantRequest,
    x_telegram_init_data: str | None = Header(
        default=None, alias="X-Telegram-Init-Data",
    ),
):
    """Owner-only recording of one verified external event per participant.

    event_key must be the stable identifier of a completed quest, game
    or order. Re-sending the same key for the same user/kind is idempotent.
    """
    owner = core.verify_init_data(x_telegram_init_data or "")
    core.require_owner(owner)
    event_key = payload.event_key.strip()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9:_-]{2,95}", event_key):
        raise HTTPException(
            status_code=422,
            detail="event_key: 3–96 символов, латиница, цифры, :, _ или -",
        )
    _, xp = EXTERNAL_XP[payload.kind]
    already_recorded = False

    try:
        with core.SessionLocal.begin() as session:
            if session.get(core.User, payload.telegram_id) is None:
                raise HTTPException(status_code=404, detail="Пользователь Nyan Wallet не найден")
            row = session.scalar(
                select(NyanExperienceEvent)
                .where(
                    NyanExperienceEvent.telegram_id == payload.telegram_id,
                    NyanExperienceEvent.kind == payload.kind,
                    NyanExperienceEvent.event_key == event_key,
                )
            )
            if row is None:
                session.add(NyanExperienceEvent(
                    telegram_id=payload.telegram_id,
                    kind=payload.kind,
                    event_key=event_key,
                    xp=xp,
                    awarded_by=int(owner["id"]),
                    created_at=core.now_utc(),
                ))
                session.flush()
            else:
                already_recorded = True
    except IntegrityError:
        # Another owner request committed this same event concurrently.
        with core.SessionLocal() as session:
            already_recorded = session.scalar(
                select(NyanExperienceEvent.id).where(
                    NyanExperienceEvent.telegram_id == payload.telegram_id,
                    NyanExperienceEvent.kind == payload.kind,
                    NyanExperienceEvent.event_key == event_key,
                )
            ) is not None
        if not already_recorded:
            raise

    with core.SessionLocal() as session:
        summary = experience_for_user(session, payload.telegram_id)
    return {
        "ok": True,
        "already_recorded": already_recorded,
        "awarded_xp": 0 if already_recorded else xp,
        "experience": summary,
    }


def register_nyan_experience(app) -> None:
    global _REGISTERED
    if _REGISTERED:
        return
    core.Base.metadata.create_all(core.engine)
    app.include_router(router)
    _REGISTERED = True
