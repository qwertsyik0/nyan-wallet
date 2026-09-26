from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException
from sqlalchemy import select

from server import backend_app as core
from server.paris_event import (
    EVENT_ID,
    STATUS_NEEDS_CHANGES,
    ParisApplicationPayload,
    ParisEventApplication,
    _fill_application,
    now_utc,
    serialize_application,
)

router = APIRouter()
_REGISTERED = False


@router.post("/api/paris/applications/me")
def post_update_paris_application(
    payload: ParisApplicationPayload,
    x_telegram_init_data: str = Header(default=""),
) -> dict:
    """CORS-safe edit endpoint for applications returned for owner-requested changes."""
    tg_user = core.verify_init_data(x_telegram_init_data)
    core.get_or_create_user(tg_user)

    telegram_id = int(tg_user["id"])
    timestamp = now_utc()

    with core.SessionLocal() as session:
        with session.begin():
            application = session.scalar(
                select(ParisEventApplication)
                .where(
                    ParisEventApplication.event_id == EVENT_ID,
                    ParisEventApplication.telegram_id == telegram_id,
                )
                .with_for_update()
            )
            if application is None:
                raise HTTPException(status_code=404, detail="Заявка ещё не отправлена")
            if application.status != STATUS_NEEDS_CHANGES:
                raise HTTPException(
                    status_code=409,
                    detail="Эту заявку сейчас нельзя редактировать",
                )

            _fill_application(application, payload, timestamp)
            application.status = "pending"
            application.owner_comment = None
            application.reviewer_id = None
            application.reviewed_at = None
            session.flush()
            response = serialize_application(application)

    return {"application": response}


def register_paris_event_compat(app) -> None:
    global _REGISTERED
    if _REGISTERED:
        return
    app.include_router(router)
    _REGISTERED = True
