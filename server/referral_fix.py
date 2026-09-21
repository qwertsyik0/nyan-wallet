from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from server import backend_app as core
from server.advanced_features import Referral, ReferralCode, settings, now
from server.extended_features import audit, send_telegram_message


router = APIRouter()
_REGISTERED = False


class ReferralApplyPayload(BaseModel):
    code: str = Field(min_length=4, max_length=24)


def _remove_legacy_referral_route(app) -> None:
    routes = getattr(app.router, "routes", [])
    app.router.routes = [
        route
        for route in routes
        if not (
            getattr(route, "path", None) == "/api/referrals/apply"
            and "POST" in set(getattr(route, "methods", set()) or set())
        )
    ]


@router.post("/api/referrals/apply")
async def referral_apply_fixed(
    payload: ReferralApplyPayload,
    background_tasks: BackgroundTasks,
    x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data"),
):
    tg = core.verify_init_data(x_telegram_init_data or "")
    core.get_or_create_user(tg)
    timestamp = now()
    code = payload.code.strip().upper()

    try:
        with core.SessionLocal() as session:
            with session.begin():
                invited = session.scalar(
                    select(core.User)
                    .where(core.User.telegram_id == tg["id"])
                    .with_for_update()
                )
                if invited is None:
                    raise HTTPException(status_code=404, detail="Пользователь не найден")

                used_referral = session.scalar(
                    select(Referral.id)
                    .where(Referral.invited_id == invited.telegram_id)
                )
                if used_referral is not None:
                    raise HTTPException(status_code=409, detail="Реферальный код уже использован")

                ref = session.scalar(
                    select(ReferralCode)
                    .where(ReferralCode.code == code)
                    .with_for_update()
                )
                if ref is None:
                    raise HTTPException(status_code=404, detail="Реферальный код не найден")
                if ref.telegram_id == invited.telegram_id:
                    raise HTTPException(status_code=400, detail="Нельзя использовать собственный код")

                inviter = session.scalar(
                    select(core.User)
                    .where(core.User.telegram_id == ref.telegram_id)
                    .with_for_update()
                )
                if inviter is None:
                    raise HTTPException(status_code=404, detail="Пригласивший не найден")

                cfg = settings(session)
                inviter_bonus = int(cfg["referral_inviter_bonus"])
                invited_bonus = int(cfg["referral_invitee_bonus"])

                inviter.balance += inviter_bonus
                invited.balance += invited_bonus

                session.add(
                    Referral(
                        inviter_id=inviter.telegram_id,
                        invited_id=invited.telegram_id,
                        inviter_reward=inviter_bonus,
                        invited_reward=invited_bonus,
                        created_at=timestamp,
                    )
                )

                if inviter_bonus:
                    session.add(
                        core.Transaction(
                            telegram_id=inviter.telegram_id,
                            amount=inviter_bonus,
                            operation_type="referral_inviter",
                            description=f"Приглашён ID {invited.telegram_id}",
                            created_at=timestamp,
                        )
                    )
                if invited_bonus:
                    session.add(
                        core.Transaction(
                            telegram_id=invited.telegram_id,
                            amount=invited_bonus,
                            operation_type="referral_invitee",
                            description="Реферальный код",
                            created_at=timestamp,
                        )
                    )

                audit(
                    session,
                    "referral_applied",
                    invited.telegram_id,
                    f"Код {ref.code} · пригласил ID {inviter.telegram_id}",
                )
                balance = invited.balance
                inviter_id = inviter.telegram_id

    except IntegrityError as exc:
        raise HTTPException(status_code=409, detail="Реферальный код уже использован") from exc

    background_tasks.add_task(
        send_telegram_message,
        tg["id"],
        f"Реферальный код активирован.\nНачислено +{invited_bonus} 🐾.\nБаланс: {balance} 🐾",
    )
    background_tasks.add_task(
        send_telegram_message,
        inviter_id,
        f"По вашему реферальному коду пришёл пользователь.\nНачислено +{inviter_bonus} 🐾.",
    )
    return {
        "ok": True,
        "balance": balance,
        "invited_bonus": invited_bonus,
        "inviter_bonus": inviter_bonus,
    }


def register_referral_fix(app) -> None:
    global _REGISTERED
    if _REGISTERED:
        return
    _remove_legacy_referral_route(app)
    app.include_router(router)
    _REGISTERED = True
