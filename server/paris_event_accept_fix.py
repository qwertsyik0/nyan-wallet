from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select

from server import backend_app as core
from server.extended_features import audit, send_telegram_message
from server.paris_event import (
    APPLICATION_STATUSES,
    EVENT_ID,
    STATUS_ACCEPTED,
    STATUS_NEEDS_CHANGES,
    ParisEventApplication,
    now_utc,
    serialize_application,
)

router = APIRouter()
_REGISTERED = False


class ParisStatusUpdateWithRolePayload(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    status: str = Field(min_length=1, max_length=24)
    owner_comment: str | None = Field(default=None, max_length=600)
    assigned_role: str | None = Field(default=None, max_length=120)

    @field_validator("status")
    @classmethod
    def validate_status(cls, value: str) -> str:
        normalized = value.strip()
        if normalized not in APPLICATION_STATUSES:
            raise ValueError("Некорректный статус заявки")
        return normalized

    @field_validator("owner_comment", "assigned_role")
    @classmethod
    def clean_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = " ".join(value.split())
        return normalized or None


def _remove_legacy_status_route(app) -> None:
    routes = getattr(app.router, "routes", [])
    app.router.routes = [
        route
        for route in routes
        if not (
            getattr(route, "path", None) == "/api/owner/paris/applications/{application_id}/status"
            and "POST" in set(getattr(route, "methods", set()) or set())
        )
    ]


@router.post("/api/owner/paris/applications/{application_id}/status")
def update_owner_paris_application_status_with_role(
    application_id: int,
    payload: ParisStatusUpdateWithRolePayload,
    background_tasks: BackgroundTasks,
    x_telegram_init_data: str = Header(default=""),
) -> dict:
    tg_user = core.verify_init_data(x_telegram_init_data)
    core.require_owner(tg_user)

    timestamp = now_utc()
    assigned_role = payload.assigned_role

    if payload.status == STATUS_ACCEPTED and not assigned_role:
        raise HTTPException(status_code=400, detail="Для принятия анкеты нужно указать роль")
    if payload.status == STATUS_NEEDS_CHANGES and not payload.owner_comment:
        raise HTTPException(status_code=400, detail="Для правок нужен комментарий владельца")

    notify_user_id: int | None = None
    notify_text: str | None = None

    with core.SessionLocal() as session:
        with session.begin():
            application = session.scalar(
                select(ParisEventApplication)
                .where(ParisEventApplication.id == application_id)
                .with_for_update()
            )
            if application is None or application.event_id != EVENT_ID:
                raise HTTPException(status_code=404, detail="Заявка не найдена")

            application.status = payload.status
            if payload.status == STATUS_ACCEPTED:
                application.owner_comment = assigned_role
            else:
                application.owner_comment = payload.owner_comment
            application.reviewer_id = int(tg_user["id"])
            application.reviewed_at = timestamp
            application.updated_at = timestamp

            user = session.get(core.User, application.telegram_id)
            audit_details = f"Заявка #{application.id}: {application.status}"
            if assigned_role:
                audit_details += f" · роль: {assigned_role}"
            audit(session, "paris_application_status", application.telegram_id, audit_details)

            session.flush()
            response = serialize_application(application, user, include_private=True)

            if payload.status == STATUS_ACCEPTED and assigned_role:
                notify_user_id = int(application.telegram_id)
                notify_text = (
                    "🇫🇷 Le Nyan Paris\n"
                    "Ваша анкета принята.\n"
                    f"Роль: {assigned_role}\n\n"
                    "С вами свяжутся в течение 3 часов для добавления в чат."
                )

    if notify_user_id and notify_text:
        background_tasks.add_task(send_telegram_message, notify_user_id, notify_text)

    return {"application": response}


def register_paris_event_accept_fix(app) -> None:
    global _REGISTERED
    if _REGISTERED:
        return
    _remove_legacy_status_route(app)
    app.include_router(router)
    _REGISTERED = True
