from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, mapped_column

from server import backend_app as core

router = APIRouter()
_REGISTERED = False

EVENT_ID = "le-nyan-paris"
STATUS_PENDING = "pending"
STATUS_ACCEPTED = "accepted"
STATUS_REJECTED = "rejected"
STATUS_NEEDS_CHANGES = "needs_changes"
APPLICATION_STATUSES = {
    STATUS_PENDING,
    STATUS_ACCEPTED,
    STATUS_REJECTED,
    STATUS_NEEDS_CHANGES,
}
AFFILIATIONS = {
    "двор",
    "армия",
    "город",
    "пресса",
    "суд",
    "полиция",
    "рынок",
    "подполье",
    "другое",
}


class ParisEventApplication(core.Base):
    __tablename__ = "paris_event_applications"
    __table_args__ = (
        UniqueConstraint("telegram_id", name="uq_paris_event_application_user"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(String(48), nullable=False, default=EVENT_ID, index=True)
    telegram_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.telegram_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    telegram_username: Mapped[str] = mapped_column(String(80), nullable=False)
    character_first_name: Mapped[str] = mapped_column(String(40), nullable=False)
    character_last_name: Mapped[str] = mapped_column(String(40), nullable=False)
    character_age: Mapped[int] = mapped_column(Integer, nullable=False)
    character_gender: Mapped[str] = mapped_column(String(40), nullable=False)
    character_orientation: Mapped[str] = mapped_column(String(80), nullable=False)
    role_preference: Mapped[str | None] = mapped_column(String(80), nullable=True)
    character_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    character_personality: Mapped[str | None] = mapped_column(Text, nullable=True)
    affiliation: Mapped[str | None] = mapped_column(String(50), nullable=True)
    roleplay_experience: Mapped[str | None] = mapped_column(Text, nullable=True)
    applicant_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default=STATUS_PENDING, index=True)
    owner_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewer_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ParisApplicationPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    character_first_name: str = Field(min_length=1, max_length=40)
    character_last_name: str = Field(min_length=1, max_length=40)
    character_age: int = Field(ge=1, le=120)
    character_gender: str = Field(min_length=1, max_length=40)
    character_orientation: str = Field(min_length=1, max_length=80)
    telegram_username: str = Field(min_length=1, max_length=80)
    role_preference: str | None = Field(default=None, max_length=80)
    character_description: str | None = Field(default=None, max_length=600)
    character_personality: str | None = Field(default=None, max_length=300)
    affiliation: str | None = Field(default=None, max_length=50)
    roleplay_experience: str | None = Field(default=None, max_length=300)
    applicant_comment: str | None = Field(default=None, max_length=400)

    @field_validator(
        "character_first_name",
        "character_last_name",
        "character_gender",
        "character_orientation",
        "telegram_username",
    )
    @classmethod
    def required_clean_text(cls, value: str) -> str:
        normalized = " ".join(str(value).split())
        if not normalized:
            raise ValueError("Поле обязательно")
        return normalized

    @field_validator(
        "role_preference",
        "character_description",
        "character_personality",
        "affiliation",
        "roleplay_experience",
        "applicant_comment",
    )
    @classmethod
    def optional_clean_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = " ".join(str(value).split())
        return normalized or None

    @field_validator("telegram_username")
    @classmethod
    def validate_telegram_username(cls, value: str) -> str:
        normalized = value.strip()
        raw = normalized[1:] if normalized.startswith("@") else normalized
        if not raw or len(raw) > 64 or any(char.isspace() for char in raw):
            raise ValueError("Некорректный Telegram username")
        return f"@{raw}"

    @field_validator("affiliation")
    @classmethod
    def validate_affiliation(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().lower()
        if normalized not in AFFILIATIONS:
            raise ValueError("Некорректная принадлежность")
        return normalized


class ParisStatusUpdatePayload(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    status: str = Field(min_length=1, max_length=24)
    owner_comment: str | None = Field(default=None, max_length=600)

    @field_validator("status")
    @classmethod
    def validate_status(cls, value: str) -> str:
        normalized = value.strip()
        if normalized not in APPLICATION_STATUSES:
            raise ValueError("Некорректный статус заявки")
        return normalized

    @field_validator("owner_comment")
    @classmethod
    def clean_owner_comment(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = " ".join(value.split())
        return normalized or None


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def user_label(user: core.User | None, telegram_id: int) -> str:
    if user is None:
        return f"ID {telegram_id}"
    if user.username:
        return f"@{user.username}"
    name = " ".join(part for part in (user.first_name, user.last_name) if part).strip()
    return name or f"ID {telegram_id}"


def serialize_application(
    application: ParisEventApplication,
    user: core.User | None = None,
    *,
    include_private: bool = False,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "id": application.id,
        "event_id": application.event_id,
        "telegram_id": application.telegram_id,
        "telegram_username": application.telegram_username,
        "character_first_name": application.character_first_name,
        "character_last_name": application.character_last_name,
        "character_age": application.character_age,
        "character_gender": application.character_gender,
        "character_orientation": application.character_orientation,
        "role_preference": application.role_preference,
        "character_description": application.character_description,
        "character_personality": application.character_personality,
        "affiliation": application.affiliation,
        "roleplay_experience": application.roleplay_experience,
        "applicant_comment": application.applicant_comment,
        "status": application.status,
        "owner_comment": application.owner_comment,
        "created_at": application.created_at.isoformat(),
        "updated_at": application.updated_at.isoformat(),
        "reviewed_at": application.reviewed_at.isoformat() if application.reviewed_at else None,
    }

    if include_private:
        result["reviewer_id"] = application.reviewer_id
        result["applicant"] = {
            "telegram_id": application.telegram_id,
            "label": user_label(user, int(application.telegram_id)),
            "username": user.username if user else None,
            "first_name": user.first_name if user else None,
            "last_name": user.last_name if user else None,
            "last_seen_at": user.last_seen_at.isoformat() if user and user.last_seen_at else None,
        }

    return result


def _find_application(session, telegram_id: int) -> ParisEventApplication | None:
    return session.scalar(
        select(ParisEventApplication).where(
            ParisEventApplication.event_id == EVENT_ID,
            ParisEventApplication.telegram_id == telegram_id,
        )
    )


def _fill_application(
    application: ParisEventApplication,
    payload: ParisApplicationPayload,
    timestamp: datetime,
) -> None:
    application.telegram_username = payload.telegram_username
    application.character_first_name = payload.character_first_name
    application.character_last_name = payload.character_last_name
    application.character_age = payload.character_age
    application.character_gender = payload.character_gender
    application.character_orientation = payload.character_orientation
    application.role_preference = payload.role_preference
    application.character_description = payload.character_description
    application.character_personality = payload.character_personality
    application.affiliation = payload.affiliation
    application.roleplay_experience = payload.roleplay_experience
    application.applicant_comment = payload.applicant_comment
    application.updated_at = timestamp


@router.get("/api/paris/applications/me")
def my_paris_application(x_telegram_init_data: str = Header(default="")) -> dict[str, Any]:
    tg_user = core.verify_init_data(x_telegram_init_data)
    telegram_id = int(tg_user["id"])

    with core.SessionLocal() as session:
        application = _find_application(session, telegram_id)
        if application is None:
            raise HTTPException(status_code=404, detail="Заявка ещё не отправлена")
        return {"application": serialize_application(application)}


@router.post("/api/paris/applications")
def create_paris_application(
    payload: ParisApplicationPayload,
    x_telegram_init_data: str = Header(default=""),
) -> dict[str, Any]:
    tg_user = core.verify_init_data(x_telegram_init_data)
    core.get_or_create_user(tg_user)

    telegram_id = int(tg_user["id"])
    timestamp = now_utc()

    try:
        with core.SessionLocal() as session:
            with session.begin():
                user = session.scalar(
                    select(core.User)
                    .where(core.User.telegram_id == telegram_id)
                    .with_for_update()
                )
                if user is None:
                    raise HTTPException(status_code=404, detail="Пользователь кошелька не найден")

                existing = session.scalar(
                    select(ParisEventApplication)
                    .where(
                        ParisEventApplication.event_id == EVENT_ID,
                        ParisEventApplication.telegram_id == telegram_id,
                    )
                    .with_for_update()
                )
                if existing is not None:
                    raise HTTPException(
                        status_code=409,
                        detail="Вы уже отправили анкету на Le Nyan Paris",
                    )

                application = ParisEventApplication(
                    event_id=EVENT_ID,
                    telegram_id=telegram_id,
                    status=STATUS_PENDING,
                    owner_comment=None,
                    reviewer_id=None,
                    reviewed_at=None,
                    created_at=timestamp,
                    updated_at=timestamp,
                )
                _fill_application(application, payload, timestamp)
                session.add(application)
                session.flush()
                response = serialize_application(application)

        return {"application": response}
    except IntegrityError as exc:
        raise HTTPException(
            status_code=409,
            detail="Вы уже отправили анкету на Le Nyan Paris",
        ) from exc


@router.put("/api/paris/applications/me")
def update_paris_application(
    payload: ParisApplicationPayload,
    x_telegram_init_data: str = Header(default=""),
) -> dict[str, Any]:
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
            application.status = STATUS_PENDING
            application.owner_comment = None
            application.reviewer_id = None
            application.reviewed_at = None
            session.flush()
            response = serialize_application(application)

    return {"application": response}


@router.get("/api/owner/paris/applications")
def owner_paris_applications(
    status: str | None = Query(default=None, max_length=24),
    limit: int = Query(default=100, ge=1, le=200),
    x_telegram_init_data: str = Header(default=""),
) -> dict[str, Any]:
    tg_user = core.verify_init_data(x_telegram_init_data)
    core.require_owner(tg_user)

    normalized_status = status.strip() if status else None
    if normalized_status and normalized_status not in APPLICATION_STATUSES:
        raise HTTPException(status_code=400, detail="Некорректный статус заявки")

    with core.SessionLocal() as session:
        query = select(ParisEventApplication).where(ParisEventApplication.event_id == EVENT_ID)
        if normalized_status:
            query = query.where(ParisEventApplication.status == normalized_status)
        applications = session.scalars(
            query.order_by(
                ParisEventApplication.created_at.desc(),
                ParisEventApplication.id.desc(),
            ).limit(limit)
        ).all()

        counts = {
            item: int(
                session.scalar(
                    select(func.count(ParisEventApplication.id)).where(
                        ParisEventApplication.event_id == EVENT_ID,
                        ParisEventApplication.status == item,
                    )
                )
                or 0
            )
            for item in sorted(APPLICATION_STATUSES)
        }

        users = {
            int(user.telegram_id): user
            for user in session.scalars(
                select(core.User).where(
                    core.User.telegram_id.in_([app.telegram_id for app in applications] or [0])
                )
            ).all()
        }

        return {
            "applications": [
                serialize_application(
                    application,
                    users.get(int(application.telegram_id)),
                    include_private=True,
                )
                for application in applications
            ],
            "counts": counts,
        }


@router.get("/api/owner/paris/applications/{application_id}")
def owner_paris_application(
    application_id: int,
    x_telegram_init_data: str = Header(default=""),
) -> dict[str, Any]:
    tg_user = core.verify_init_data(x_telegram_init_data)
    core.require_owner(tg_user)

    with core.SessionLocal() as session:
        application = session.get(ParisEventApplication, application_id)
        if application is None or application.event_id != EVENT_ID:
            raise HTTPException(status_code=404, detail="Заявка не найдена")
        user = session.get(core.User, application.telegram_id)
        return {
            "application": serialize_application(
                application,
                user,
                include_private=True,
            )
        }


@router.post("/api/owner/paris/applications/{application_id}/status")
def update_owner_paris_application_status(
    application_id: int,
    payload: ParisStatusUpdatePayload,
    x_telegram_init_data: str = Header(default=""),
) -> dict[str, Any]:
    tg_user = core.verify_init_data(x_telegram_init_data)
    core.require_owner(tg_user)

    if payload.status == STATUS_NEEDS_CHANGES and not payload.owner_comment:
        raise HTTPException(
            status_code=400,
            detail="Для статуса «нужны правки» нужен комментарий владельца",
        )

    timestamp = now_utc()
    with core.SessionLocal() as session:
        with session.begin():
            application = session.scalar(
                select(ParisEventApplication)
                .where(
                    ParisEventApplication.id == application_id,
                    ParisEventApplication.event_id == EVENT_ID,
                )
                .with_for_update()
            )
            if application is None:
                raise HTTPException(status_code=404, detail="Заявка не найдена")

            application.status = payload.status
            application.owner_comment = payload.owner_comment
            application.reviewer_id = int(tg_user["id"])
            application.reviewed_at = timestamp
            application.updated_at = timestamp
            session.flush()
            user = session.get(core.User, application.telegram_id)
            response = serialize_application(application, user, include_private=True)

    return {"application": response}


def register_paris_event(app) -> None:
    global _REGISTERED
    if _REGISTERED:
        return
    core.Base.metadata.create_all(core.engine)
    app.include_router(router)
    _REGISTERED = True
