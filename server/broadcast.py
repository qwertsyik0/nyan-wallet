from __future__ import annotations

import hashlib
import hmac
import time
from datetime import timedelta
from typing import Literal

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from server import backend_app as core

router = APIRouter()
_REGISTERED = False
SIGNATURE_MAX_AGE_SECONDS = 180
MAX_PAGE_SIZE = 500


class InternalBroadcastRecipientsPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    owner_telegram_id: int = Field(gt=0)
    audience: Literal["all", "active_7d", "active_30d"] = "all"
    after_telegram_id: int = Field(default=0, ge=0)
    limit: int = Field(default=500, ge=1, le=MAX_PAGE_SIZE)


def verify_internal_signature(
    timestamp_raw: str | None,
    signature: str | None,
    body: bytes,
) -> None:
    if not timestamp_raw or not signature:
        raise HTTPException(status_code=401, detail="Подпись внутреннего запроса отсутствует")

    try:
        timestamp = int(timestamp_raw)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="Некорректное время подписи") from exc

    if abs(int(time.time()) - timestamp) > SIGNATURE_MAX_AGE_SECONDS:
        raise HTTPException(status_code=401, detail="Подпись внутреннего запроса устарела")

    expected = hmac.new(
        core.BOT_TOKEN.encode("utf-8"),
        timestamp_raw.encode("utf-8") + b"\n" + body,
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(expected, signature):
        raise HTTPException(status_code=401, detail="Недействительная подпись внутреннего запроса")


@router.post("/api/internal/broadcast/recipients")
async def internal_broadcast_recipients(
    request: Request,
    x_nyan_timestamp: str | None = Header(default=None, alias="X-Nyan-Timestamp"),
    x_nyan_signature: str | None = Header(default=None, alias="X-Nyan-Signature"),
):
    raw_body = await request.body()
    verify_internal_signature(x_nyan_timestamp, x_nyan_signature, raw_body)

    try:
        payload = InternalBroadcastRecipientsPayload.model_validate_json(raw_body)
    except Exception as exc:
        raise HTTPException(status_code=422, detail="Некорректные параметры рассылки") from exc

    if core.OWNER_TELEGRAM_ID is None or payload.owner_telegram_id != core.OWNER_TELEGRAM_ID:
        raise HTTPException(status_code=403, detail="Команда доступна только владельцу")

    timestamp = core.now_utc()
    stmt = (
        select(core.User.telegram_id)
        .where(
            core.User.telegram_id > payload.after_telegram_id,
            core.User.telegram_id != payload.owner_telegram_id,
        )
        .order_by(core.User.telegram_id.asc())
    )

    if payload.audience == "active_7d":
        stmt = stmt.where(core.User.last_seen_at >= timestamp - timedelta(days=7))
    elif payload.audience == "active_30d":
        stmt = stmt.where(core.User.last_seen_at >= timestamp - timedelta(days=30))

    with core.SessionLocal() as session:
        rows = list(session.scalars(stmt.limit(payload.limit + 1)).all())

    has_more = len(rows) > payload.limit
    recipients = rows[: payload.limit]
    next_after = recipients[-1] if recipients else payload.after_telegram_id

    return {
        "ok": True,
        "audience": payload.audience,
        "recipients": recipients,
        "next_after_telegram_id": next_after,
        "has_more": has_more,
    }


def register_broadcast(app) -> None:
    global _REGISTERED
    if _REGISTERED:
        return
    app.include_router(router)
    _REGISTERED = True
