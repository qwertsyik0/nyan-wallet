from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import BigInteger, DateTime, ForeignKey, Text, delete, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Mapped, mapped_column

from server import backend_app as core
from server.maintenance import verify_internal_signature

logger = logging.getLogger("nyan_wallet.user_bans")

router = APIRouter()
_REGISTERED = False


class BlockedUser(core.Base):
    __tablename__ = "blocked_users"

    telegram_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.telegram_id", ondelete="CASCADE"),
        primary_key=True,
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    blocked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class OwnerBanPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    target: str = Field(min_length=1, max_length=64)
    reason: str | None = Field(default=None, max_length=300)

    @field_validator("target")
    @classmethod
    def normalize_target(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Пользователь не указан")
        return value

    @field_validator("reason")
    @classmethod
    def normalize_reason(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = " ".join(value.split())
        return value or None


class InternalBanPayload(OwnerBanPayload):
    action: str
    owner_telegram_id: int = Field(gt=0)

    @field_validator("action")
    @classmethod
    def validate_action(cls, value: str) -> str:
        value = value.strip().lower()
        if value not in {"ban", "unban"}:
            raise ValueError("Некорректное действие")
        return value


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _target_user(session, target: str, *, lock: bool = False):
    user = core.find_target_user(session, target, lock=lock)
    if user is None:
        raise HTTPException(
            status_code=404,
            detail="Пользователь не найден. Он должен хотя бы один раз открыть Nyan Wallet.",
        )
    if core.is_owner(int(user.telegram_id)):
        raise HTTPException(status_code=400, detail="Владельца Nyan Wallet нельзя заблокировать")
    return user


def _serialize(row: BlockedUser, user=None) -> dict[str, Any]:
    return {
        "telegram_id": int(row.telegram_id),
        "username": getattr(user, "username", None),
        "first_name": getattr(user, "first_name", None),
        "reason": row.reason or None,
        "blocked_at": row.blocked_at.isoformat(),
    }


def ban_target(target: str, reason: str | None) -> dict[str, Any]:
    timestamp = now_utc()
    normalized_reason = (reason or "").strip() or "Без указания причины"

    try:
        with core.SessionLocal() as session:
            with session.begin():
                user = _target_user(session, target, lock=True)
                row = session.get(BlockedUser, int(user.telegram_id))
                if row is None:
                    row = BlockedUser(
                        telegram_id=int(user.telegram_id),
                        reason=normalized_reason,
                        blocked_at=timestamp,
                    )
                    session.add(row)
                else:
                    row.reason = normalized_reason
                    row.blocked_at = timestamp
                session.flush()
                result = _serialize(row, user)
        return result
    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        logger.exception("ban_target_failed target=%s", target)
        raise HTTPException(status_code=503, detail="Не удалось заблокировать пользователя") from exc


def unban_target(target: str) -> dict[str, Any]:
    try:
        with core.SessionLocal() as session:
            with session.begin():
                user = _target_user(session, target, lock=True)
                row = session.get(BlockedUser, int(user.telegram_id))
                was_blocked = row is not None
                if row is not None:
                    session.delete(row)
                result = {
                    "telegram_id": int(user.telegram_id),
                    "username": user.username,
                    "first_name": user.first_name,
                    "was_blocked": was_blocked,
                }
        return result
    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        logger.exception("unban_target_failed target=%s", target)
        raise HTTPException(status_code=503, detail="Не удалось разблокировать пользователя") from exc


@router.get("/api/owner/bans/status/{telegram_id}")
async def owner_ban_status(
    telegram_id: int,
    x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data"),
):
    tg = core.verify_init_data(x_telegram_init_data or "")
    core.require_owner(tg)

    with core.SessionLocal() as session:
        user = session.get(core.User, telegram_id)
        if user is None:
            raise HTTPException(status_code=404, detail="Пользователь не найден")
        row = session.get(BlockedUser, telegram_id)
        return {
            "ok": True,
            "blocked": row is not None,
            "ban": _serialize(row, user) if row is not None else None,
        }


@router.post("/api/owner/bans/ban")
async def owner_ban(
    payload: OwnerBanPayload,
    x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data"),
):
    tg = core.verify_init_data(x_telegram_init_data or "")
    core.require_owner(tg)
    return {"ok": True, "ban": ban_target(payload.target, payload.reason)}


@router.post("/api/owner/bans/unban")
async def owner_unban(
    payload: OwnerBanPayload,
    x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data"),
):
    tg = core.verify_init_data(x_telegram_init_data or "")
    core.require_owner(tg)
    return {"ok": True, "unban": unban_target(payload.target)}


@router.get("/api/owner/bans")
async def owner_ban_list(
    x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data"),
):
    tg = core.verify_init_data(x_telegram_init_data or "")
    core.require_owner(tg)

    with core.SessionLocal() as session:
        rows = session.scalars(select(BlockedUser).order_by(BlockedUser.blocked_at.desc())).all()
        users = {
            int(user.telegram_id): user
            for user in session.scalars(
                select(core.User).where(core.User.telegram_id.in_([row.telegram_id for row in rows]))
            ).all()
        } if rows else {}
        return {
            "ok": True,
            "bans": [_serialize(row, users.get(int(row.telegram_id))) for row in rows],
        }


@router.post("/api/internal/user-ban")
async def internal_user_ban(
    request: Request,
    x_nyan_timestamp: str | None = Header(default=None, alias="X-Nyan-Timestamp"),
    x_nyan_signature: str | None = Header(default=None, alias="X-Nyan-Signature"),
):
    raw_body = await request.body()
    verify_internal_signature(x_nyan_timestamp, x_nyan_signature, raw_body)

    try:
        payload = InternalBanPayload.model_validate_json(raw_body)
    except Exception as exc:
        raise HTTPException(status_code=422, detail="Некорректные параметры команды бана") from exc

    if core.OWNER_TELEGRAM_ID is None or payload.owner_telegram_id != core.OWNER_TELEGRAM_ID:
        raise HTTPException(status_code=403, detail="Команда доступна только владельцу")

    if payload.action == "ban":
        result = ban_target(payload.target, payload.reason)
    else:
        result = unban_target(payload.target)

    logger.warning(
        "user_ban_action action=%s owner_id=%s target=%s",
        payload.action,
        payload.owner_telegram_id,
        payload.target,
    )
    return {"ok": True, payload.action: result}


async def blocked_user_guard(request: Request, call_next):
    if request.method == "OPTIONS":
        return await call_next(request)

    path = request.url.path
    if not path.startswith("/api/"):
        return await call_next(request)

    # Internal bot calls are authenticated by their own HMAC signature.
    if path == "/api/internal/user-ban":
        return await call_next(request)

    init_data = request.headers.get("X-Telegram-Init-Data", "")
    if not init_data:
        return await call_next(request)

    try:
        tg = core.verify_init_data(init_data)
    except HTTPException:
        return await call_next(request)

    telegram_id = int(tg["id"])
    if core.is_owner(telegram_id):
        return await call_next(request)

    try:
        with core.SessionLocal() as session:
            row = session.get(BlockedUser, telegram_id)
    except SQLAlchemyError:
        logger.exception("blocked_user_guard_failed telegram_id=%s path=%s", telegram_id, path)
        return JSONResponse(status_code=503, content={"detail": "Сервис временно недоступен"})

    if row is None:
        return await call_next(request)

    return JSONResponse(
        status_code=403,
        content={
            "detail": "Аккаунт заблокирован в Nyan Wallet",
            "blocked": True,
            "reason": row.reason if row.reason != "Без указания причины" else None,
        },
    )


def register_user_bans(app) -> None:
    global _REGISTERED
    if _REGISTERED:
        return
    core.Base.metadata.create_all(core.engine)
    app.include_router(router)
    app.middleware("http")(blocked_user_guard)
    _REGISTERED = True
