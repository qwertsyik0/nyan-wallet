"""Read-only authenticated Nyan ID cards based on existing wallet data.

The public-facing card number is a non-authorizing, stable pseudonymous label.
It never grants access to wallet functions and deliberately omits balances,
raw Telegram IDs, transaction history and referral codes.
"""
from __future__ import annotations

import hashlib

from fastapi import APIRouter, Header, HTTPException
from sqlalchemy import func, select

from . import backend_app as core
from .advanced_features import level_data, settings
from .achievements import (
    ACHIEVEMENT_BY_KEY,
    AchievementBadge,
    AchievementUnlock,
)

router = APIRouter()
_REGISTERED = False


def make_nyan_id(telegram_id: int) -> str:
    """Stable public label; not an authentication token or proof of identity."""
    digest = hashlib.blake2s(
        f"nyan-id:v1:{int(telegram_id)}".encode("ascii"),
        digest_size=8,
    ).hexdigest().upper()
    return f"NW-{digest[:4]}-{digest[4:8]}-{digest[8:12]}-{digest[12:]}"


@router.get("/api/nyan-id")
async def nyan_id(
    x_telegram_init_data: str | None = Header(
        default=None, alias="X-Telegram-Init-Data"
    ),
):
    telegram = core.verify_init_data(x_telegram_init_data or "")
    core.get_or_create_user(telegram)
    with core.SessionLocal() as session:
        user = session.get(core.User, telegram["id"])
        if user is None:
            raise HTTPException(status_code=404, detail="Кошелёк не найден")

        earned = session.scalar(
            select(func.coalesce(func.sum(core.Transaction.amount), 0)).where(
                core.Transaction.telegram_id == user.telegram_id,
                core.Transaction.amount > 0,
                ~core.Transaction.operation_type.in_((
                    "reward_refund",
                    "giveaway_refund",
                    "giveaway_manual_refund",
                )),
            )
        ) or 0

        level = level_data(int(earned), settings(session))
        unlocked = session.scalars(
            select(AchievementUnlock)
            .where(AchievementUnlock.telegram_id == user.telegram_id)
            .order_by(AchievementUnlock.unlocked_at.desc())
        ).all()
        unlocked_keys = {row.achievement_key for row in unlocked}
        badge_row = session.get(AchievementBadge, user.telegram_id)
        badge_source = (
            ACHIEVEMENT_BY_KEY.get(badge_row.achievement_key)
            if badge_row and badge_row.achievement_key in unlocked_keys
            else None
        )

        titles = [
            ACHIEVEMENT_BY_KEY[row.achievement_key]["title"]
            for row in unlocked
            if row.achievement_key in ACHIEVEMENT_BY_KEY
        ][:3]
        display_name = " ".join(
            part.strip() for part in (user.first_name, user.last_name)
            if part and part.strip()
        )[:96] or "Пользователь"
        username = user.username if user.username and user.username.isascii() else None

        return {
            "ok": True,
            "number": make_nyan_id(user.telegram_id),
            "display_name": display_name,
            "username": username,
            "member_since": user.created_at.isoformat(),
            "rank": "Владелец" if core.is_owner(user.telegram_id) else level["name"],
            "owner": bool(core.is_owner(user.telegram_id)),
            "achievement_count": len(unlocked),
            "recent_achievements": titles,
            "badge": (
                {"title": badge_source["title"], "rarity": badge_source["rarity"]}
                if badge_source else None
            ),
        }


def register_nyan_id(app) -> None:
    global _REGISTERED
    if _REGISTERED:
        return
    app.include_router(router)
    _REGISTERED = True
