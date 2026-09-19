from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import Boolean, DateTime, Integer, String, Text, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Mapped, Session, mapped_column

from server import backend_app as core

logger = logging.getLogger("nyan_wallet.maintenance")

router = APIRouter()
_REGISTERED = False
STATE_ID = 1
SIGNATURE_MAX_AGE_SECONDS = 180

DEFAULT_TITLE = "Nyan Wallet становится лучше"
DEFAULT_MESSAGE = (
    "Сейчас мы проводим технические работы: добавляем новые функции, "
    "улучшаем стабильность и готовим обновления для вас. "
    "Кошелёк скоро снова будет доступен в обычном режиме."
)

EXEMPT_PATHS = {
    "/api/health",
    "/api/maintenance/status",
    "/api/internal/maintenance/toggle",
}


class MaintenanceState(core.Base):
    __tablename__ = "maintenance_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    title: Mapped[str] = mapped_column(String(120), nullable=False, default=DEFAULT_TITLE)
    message: Mapped[str] = mapped_column(Text, nullable=False, default=DEFAULT_MESSAGE)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_by: Mapped[int | None] = mapped_column(Integer, nullable=True)


class InternalMaintenancePayload(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    enabled: bool
    title: str | None = Field(default=None, max_length=120)
    message: str | None = Field(default=None, max_length=800)
    owner_telegram_id: int = Field(gt=0)

    @field_validator("title", "message")
    @classmethod
    def normalize_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = " ".join(value.split())
        return normalized or None


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def get_state(session: Session, *, lock: bool = False) -> MaintenanceState:
    query = select(MaintenanceState).where(MaintenanceState.id == STATE_ID)
    if lock:
        query = query.with_for_update()
    state = session.scalar(query)
    if state is not None:
        return state

    state = MaintenanceState(
        id=STATE_ID,
        enabled=False,
        title=DEFAULT_TITLE,
        message=DEFAULT_MESSAGE,
        updated_at=now_utc(),
        updated_by=None,
    )
    session.add(state)
    session.flush()
    return state


def serialize_state(state: MaintenanceState) -> dict[str, Any]:
    return {
        "enabled": bool(state.enabled),
        "title": state.title,
        "message": state.message,
        "updated_at": state.updated_at.isoformat(),
    }


def verify_internal_signature(timestamp_raw: str | None, signature: str | None, body: bytes) -> None:
    if not timestamp_raw or not signature:
        raise HTTPException(status_code=401, detail="Подпись команды обслуживания отсутствует")

    try:
        timestamp = int(timestamp_raw)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="Некорректное время подписи") from exc

    now = int(time.time())
    if abs(now - timestamp) > SIGNATURE_MAX_AGE_SECONDS:
        raise HTTPException(status_code=401, detail="Подпись команды обслуживания устарела")

    message = timestamp_raw.encode("utf-8") + b"\n" + body
    expected = hmac.new(
        core.BOT_TOKEN.encode("utf-8"),
        message,
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(expected, signature):
        raise HTTPException(status_code=401, detail="Недействительная подпись команды обслуживания")


def read_state() -> dict[str, Any]:
    try:
        with core.SessionLocal() as session:
            state = get_state(session)
            session.commit()
            return serialize_state(state)
    except SQLAlchemyError as exc:
        logger.exception("maintenance_state_read_failed")
        raise HTTPException(status_code=503, detail="Не удалось прочитать режим обслуживания") from exc


@router.get("/api/maintenance/status")
async def maintenance_status(
    x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data"),
):
    is_owner = False
    if x_telegram_init_data:
        try:
            tg = core.verify_init_data(x_telegram_init_data)
            is_owner = core.is_owner(int(tg["id"]))
        except HTTPException:
            is_owner = False

    state = read_state()
    return {
        "ok": True,
        "maintenance": state,
        "owner_bypass": is_owner,
        "blocked": bool(state["enabled"] and not is_owner),
    }


@router.post("/api/internal/maintenance/toggle")
async def internal_toggle_maintenance(
    request: Request,
    x_nyan_timestamp: str | None = Header(default=None, alias="X-Nyan-Timestamp"),
    x_nyan_signature: str | None = Header(default=None, alias="X-Nyan-Signature"),
):
    raw_body = await request.body()
    verify_internal_signature(x_nyan_timestamp, x_nyan_signature, raw_body)

    try:
        payload = InternalMaintenancePayload.model_validate_json(raw_body)
    except Exception as exc:
        raise HTTPException(status_code=422, detail="Некорректные параметры режима обслуживания") from exc

    if core.OWNER_TELEGRAM_ID is None or payload.owner_telegram_id != core.OWNER_TELEGRAM_ID:
        raise HTTPException(status_code=403, detail="Команда доступна только владельцу")

    title = payload.title or DEFAULT_TITLE
    message = payload.message or DEFAULT_MESSAGE
    timestamp = now_utc()

    try:
        with core.SessionLocal() as session:
            with session.begin():
                state = get_state(session, lock=True)
                state.enabled = payload.enabled
                state.title = title
                state.message = message
                state.updated_at = timestamp
                state.updated_by = payload.owner_telegram_id
            result = serialize_state(state)
    except SQLAlchemyError as exc:
        logger.exception("maintenance_toggle_failed owner_id=%s", payload.owner_telegram_id)
        raise HTTPException(status_code=503, detail="Не удалось изменить режим обслуживания") from exc

    logger.warning(
        "maintenance_mode_changed enabled=%s owner_id=%s",
        payload.enabled,
        payload.owner_telegram_id,
    )
    return {"ok": True, "maintenance": result}


async def maintenance_guard(request: Request, call_next):
    if request.method == "OPTIONS":
        return await call_next(request)

    path = request.url.path
    if not path.startswith("/api/") or path in EXEMPT_PATHS:
        return await call_next(request)

    try:
        with core.SessionLocal() as session:
            state = get_state(session)
            session.commit()
            enabled = bool(state.enabled)
            serialized = serialize_state(state)
    except SQLAlchemyError:
        logger.exception("maintenance_guard_state_failed path=%s", path)
        return JSONResponse(
            status_code=503,
            content={"detail": "Сервис временно недоступен"},
        )

    if not enabled:
        return await call_next(request)

    init_data = request.headers.get("X-Telegram-Init-Data", "")
    if init_data:
        try:
            tg = core.verify_init_data(init_data)
            if core.is_owner(int(tg["id"])):
                return await call_next(request)
        except HTTPException:
            pass

    return JSONResponse(
        status_code=503,
        headers={"Retry-After": "300"},
        content={
            "detail": "maintenance",
            "maintenance": serialized,
        },
    )


def register_maintenance(app) -> None:
    global _REGISTERED
    if _REGISTERED:
        return
    core.Base.metadata.create_all(core.engine)
    with core.SessionLocal() as session:
        get_state(session)
        session.commit()
    app.include_router(router)
    app.middleware("http")(maintenance_guard)
    _REGISTERED = True
