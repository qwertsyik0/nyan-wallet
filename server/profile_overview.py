"""Read-only, authenticated wallet profile summary and cursor-based history."""

from __future__ import annotations

from fastapi import APIRouter, Header, Query
from sqlalchemy import case, func, select

from . import backend_app as core


router = APIRouter()
_REGISTERED = False


@router.get("/api/profile/overview")
def profile_overview(
    before_id: int | None = Query(default=None, ge=1),
    limit: int = Query(default=25, ge=1, le=50),
    x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data"),
):
    tg_user = core.verify_init_data(x_telegram_init_data or "")
    user_id = int(tg_user["id"])
    with core.SessionLocal() as session:
        user = session.get(core.User, user_id)
        if user is None:
            # /api/me normally creates the account. A direct profile launch
            # before it should still return a truthful empty profile.
            return {
                "ok": True,
                "balance": 0,
                "earned": 0,
                "spent": 0,
                "operations_count": 0,
                "achievements_count": 0,
                "requests": [],
                "transactions": [],
                "next_cursor": None,
            }
        amount = core.Transaction.amount
        stats = session.execute(
            select(
                func.count(core.Transaction.id),
                func.coalesce(func.sum(case((amount > 0, amount), else_=0)), 0),
                func.coalesce(func.sum(case((amount < 0, -amount), else_=0)), 0),
            ).where(core.Transaction.telegram_id == user_id)
        ).one()
        query = (
            select(core.Transaction)
            .where(core.Transaction.telegram_id == user_id)
            .order_by(core.Transaction.id.desc())
            .limit(limit + 1)
        )
        if before_id is not None:
            query = query.where(core.Transaction.id < before_id)
        rows = session.scalars(query).all()
        has_more = len(rows) > limit
        rows = rows[:limit]

        # Optional modules may not be installed on older servers. Never let
        # a secondary profile widget block the actual wallet.
        achievements_count = 0
        requests = []
        try:
            from .achievements import AchievementUnlock
            achievements_count = session.scalar(
                select(func.count()).select_from(AchievementUnlock)
                .where(AchievementUnlock.telegram_id == user_id)
            ) or 0
        except (ImportError, AttributeError):
            pass
        try:
            from .appeals import Appeal
            appeals = session.scalars(
                select(Appeal).where(Appeal.telegram_id == user_id)
                .order_by(Appeal.id.desc()).limit(6)
            ).all()
            requests.extend({
                "kind": "appeal",
                "id": row.public_id or str(row.id),
                "title": "Обращение",
                "status": row.status,
                "created_at": row.created_at.isoformat(),
            } for row in appeals)
        except (ImportError, AttributeError):
            pass
        try:
            from .interactive_ideas import InteractiveIdea
            idea = session.scalar(
                select(InteractiveIdea)
                .where(InteractiveIdea.telegram_id == user_id)
            )
            if idea:
                requests.append({
                    "kind": "idea",
                    "id": str(idea.id),
                    "title": idea.title,
                    "status": idea.status,
                    "created_at": idea.created_at.isoformat(),
                })
        except (ImportError, AttributeError):
            pass

        return {
            "ok": True,
            "balance": int(user.balance),
            "earned": int(stats[1]),
            "spent": int(stats[2]),
            "operations_count": int(stats[0]),
            "achievements_count": int(achievements_count),
            "requests": sorted(requests, key=lambda item: item["created_at"], reverse=True)[:7],
            "transactions": [core.serialize_transaction(row) for row in rows],
            "next_cursor": rows[-1].id if has_more and rows else None,
        }


def register_profile_overview(app) -> None:
    global _REGISTERED
    if _REGISTERED:
        return
    app.include_router(router)
    _REGISTERED = True
