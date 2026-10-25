"""One lifetime interactive idea per verified Telegram user, moderated for 500 paws.

The page supports both a signed Telegram Mini App launch and the independent
Telegram Login Widget for people opening the GitHub Pages URL in a browser.
No client-supplied Telegram ID is accepted without an HMAC signature.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import re
import time
from datetime import datetime

from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, Text, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Mapped, mapped_column

from . import backend_app as core
from .user_bans import BlockedUser


LOG = logging.getLogger("nyan_wallet.interactive_ideas")
router = APIRouter()
_REGISTERED = False
REWARD_AMOUNT = 500
REWARD_REASON = "одобрение идеи интерактива"
WEB_PREFIX = "browser:"
WEB_SESSION_SECONDS = 6 * 60 * 60
WIDGET_MAX_AGE_SECONDS = 10 * 60


class InteractiveIdea(core.Base):
    __tablename__ = "interactive_idea_submissions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # A database constraint (not just a frontend flag) disallows every retry,
    # including after a rejection and during simultaneous POST requests.
    telegram_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.telegram_id", ondelete="CASCADE"),
        nullable=False, unique=True, index=True,
    )
    title: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    reward_amount: Mapped[int] = mapped_column(Integer, nullable=False)
    moderator_note: Mapped[str | None] = mapped_column(String(600), nullable=True)
    reviewed_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rewarded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class IdeaRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    title: str = Field(min_length=5, max_length=100)
    description: str = Field(min_length=40, max_length=4000)


class ReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    decision: str
    note: str | None = Field(default=None, max_length=600)


def _url_b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _decode_b64(data: str) -> bytes:
    if not re.fullmatch(r"[A-Za-z0-9_-]+", data) or len(data) > 2000:
        raise ValueError("Некорректная сессия")
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


def _browser_key() -> bytes:
    # Purpose separation: a Telegram Login Widget hash cannot become a valid
    # application session signature or be confused with Telegram Mini App data.
    return hmac.new(core.BOT_TOKEN.encode("utf-8"), b"nyan-interactive-ideas-session-v1", hashlib.sha256).digest()


def verify_widget_login(data: dict) -> dict:
    """Verify Telegram Login Widget data using the documented SHA256(token) key."""
    if not isinstance(data, dict) or not (3 <= len(data) <= 20):
        raise HTTPException(status_code=401, detail="Некорректный ответ Telegram")
    values = {}
    for key, value in data.items():
        if not isinstance(key, str) or not re.fullmatch(r"[a-z_]{1,40}", key):
            raise HTTPException(status_code=401, detail="Некорректные параметры Telegram")
        if isinstance(value, bool) or not isinstance(value, (str, int)) or len(str(value)) > 2048:
            raise HTTPException(status_code=401, detail="Некорректные параметры Telegram")
        values[key] = str(value)
    supplied = values.pop("hash", "")
    if not re.fullmatch(r"[0-9a-f]{64}", supplied):
        raise HTTPException(status_code=401, detail="Подпись Telegram отсутствует")
    check_string = "\n".join(f"{key}={value}" for key, value in sorted(values.items()))
    expected = hmac.new(hashlib.sha256(core.BOT_TOKEN.encode("utf-8")).digest(),
                        check_string.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(supplied, expected):
        raise HTTPException(status_code=401, detail="Подпись Telegram недействительна")
    try:
        identity = int(values["id"])
        issued = int(values["auth_date"])
    except (KeyError, ValueError):
        raise HTTPException(status_code=401, detail="Telegram не предоставил данные входа") from None
    if identity <= 0 or abs(int(time.time()) - issued) > WIDGET_MAX_AGE_SECONDS:
        raise HTTPException(status_code=401, detail="Срок входа через Telegram истёк")
    return {
        "id": identity,
        "username": values.get("username", "")[:64],
        "first_name": values.get("first_name", "Пользователь")[:255],
        "last_name": values.get("last_name", "")[:255],
    }


def issue_browser_session(tg_user: dict) -> str:
    payload = json.dumps({
        "v": 1,
        "uid": int(tg_user["id"]),
        "username": tg_user.get("username") or "",
        "first_name": tg_user.get("first_name") or "Пользователь",
        "last_name": tg_user.get("last_name") or "",
        "exp": int(time.time()) + WEB_SESSION_SECONDS,
    }, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    encoded = _url_b64(payload)
    signature = _url_b64(hmac.new(_browser_key(), encoded.encode("ascii"), hashlib.sha256).digest())
    return encoded + "." + signature


def verify_browser_session(value: str) -> dict:
    try:
        encoded, supplied = value.split(".", 1)
        signature = _url_b64(hmac.new(_browser_key(), encoded.encode("ascii"), hashlib.sha256).digest())
        if not hmac.compare_digest(signature, supplied):
            raise ValueError("Подпись сессии не совпадает")
        details = json.loads(_decode_b64(encoded).decode("utf-8"))
        uid = details["uid"]
        expires = details["exp"]
        if (details["v"] != 1 or isinstance(uid, bool) or type(uid) is not int
                or uid <= 0 or type(expires) is not int or int(time.time()) > expires):
            raise ValueError("Сессия устарела")
    except (KeyError, ValueError, TypeError, UnicodeError, json.JSONDecodeError):
        raise HTTPException(status_code=401, detail="Вход через Telegram устарел. Войдите заново.") from None
    return {
        "id": uid,
        "username": str(details.get("username") or "")[:64],
        "first_name": str(details.get("first_name") or "Пользователь")[:255],
        "last_name": str(details.get("last_name") or "")[:255],
    }


def _identity(header: str | None) -> dict:
    value = header or ""
    if value.startswith(WEB_PREFIX):
        return verify_browser_session(value[len(WEB_PREFIX):])
    return core.verify_init_data(value)


def _normalize(value: str) -> str:
    return " ".join(value.strip().split())


def _clean_description(value: str) -> str:
    lines = [" ".join(line.split()) for line in value.strip().splitlines()]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines))


def _serialize(item: InteractiveIdea, user: core.User | None = None) -> dict:
    output = {
        "id": item.id,
        "title": item.title,
        "description": item.description,
        "status": item.status,
        "reward_amount": item.reward_amount,
        "moderator_note": item.moderator_note,
        "created_at": item.created_at.isoformat(),
        "reviewed_at": item.reviewed_at.isoformat() if item.reviewed_at else None,
        "rewarded_at": item.rewarded_at.isoformat() if item.rewarded_at else None,
    }
    if user is not None:
        output.update(telegram_id=user.telegram_id,
                      username=user.username, first_name=user.first_name)
    return output


def _ensure_user(session, telegram: dict, timestamp: datetime) -> core.User:
    values = {
        "telegram_id": int(telegram["id"]),
        "username": telegram.get("username") or None,
        "first_name": telegram.get("first_name") or "Пользователь",
        "last_name": telegram.get("last_name") or None,
        "balance": 0,
        "created_at": timestamp,
        "last_seen_at": timestamp,
    }
    dialect = session.bind.dialect.name
    if dialect == "postgresql":
        insert = pg_insert(core.User).values(**values)
    elif dialect == "sqlite":  # Isolated test database only.
        insert = sqlite_insert(core.User).values(**values)
    else:
        raise RuntimeError("Для Nyan Wallet требуется PostgreSQL")
    session.execute(insert.on_conflict_do_nothing(index_elements=["telegram_id"]))
    user = session.scalar(select(core.User)
                          .where(core.User.telegram_id == telegram["id"])
                          .with_for_update())
    core.apply_telegram_profile(user, telegram, timestamp)
    return user


def _notify(chat_id: int | None, text: str) -> None:
    if not chat_id:
        return
    try:
        from .telegram_relay import queue_message
        queue_message(chat_id, text)
    except Exception:
        # A Telegram transport failure must never change a form or balance.
        LOG.exception("Failed to enqueue interactive idea notice")


@router.post("/api/interactive-ideas/auth/widget")
def widget_login(payload: dict):
    user = verify_widget_login(payload)
    return {"ok": True, "session": issue_browser_session(user),
            "expires_in": WEB_SESSION_SECONDS}


@router.get("/api/interactive-ideas/me")
def my_idea(x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data")):
    tg_user = _identity(x_telegram_init_data)
    with core.SessionLocal() as session:
        row = session.scalar(select(InteractiveIdea).where(InteractiveIdea.telegram_id == tg_user["id"]))
    return {"ok": True, "is_owner": core.is_owner(tg_user["id"]),
            "can_submit": row is None, "idea": _serialize(row) if row else None,
            "reward_amount": REWARD_AMOUNT}


@router.post("/api/interactive-ideas")
def submit_idea(payload: IdeaRequest,
                x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data")):
    tg_user = _identity(x_telegram_init_data)
    title = _normalize(payload.title)
    description = _clean_description(payload.description)
    if len(title) < 5 or len(_normalize(description)) < 40:
        raise HTTPException(status_code=400, detail="Укажите название и подробное описание интерактива")
    timestamp = core.now_utc()
    with core.SessionLocal.begin() as session:
        user = _ensure_user(session, tg_user, timestamp)
        if session.get(BlockedUser, user.telegram_id) is not None:
            raise HTTPException(status_code=403, detail="Для заблокированного аккаунта участие недоступно")
        existing = session.scalar(select(InteractiveIdea.id)
                                  .where(InteractiveIdea.telegram_id == user.telegram_id))
        if existing is not None:
            raise HTTPException(status_code=409, detail="Вы уже отправляли идею. Повторная заявка недоступна.")
        item = InteractiveIdea(
            telegram_id=user.telegram_id,
            title=title,
            description=description,
            status="pending",
            reward_amount=REWARD_AMOUNT,
            moderator_note=None,
            reviewed_by=None,
            created_at=timestamp,
            reviewed_at=None,
            rewarded_at=None,
        )
        session.add(item)
        session.flush()
        result = _serialize(item)

    if core.OWNER_TELEGRAM_ID:
        name = "@" + tg_user["username"] if tg_user.get("username") else tg_user.get("first_name", "Пользователь")
        _notify(core.OWNER_TELEGRAM_ID,
                f"💡 Новая идея интерактива #{result['id']}\n"
                f"Автор: {name} (ID {tg_user['id']})\n"
                f"Название: {title}\n\n{description[:650]}\n\n"
                "Проверить: https://qwertsyik0.github.io/nyan-wallet/interactive-ideas.html")
    return {"ok": True, "idea": result}


@router.get("/api/interactive-ideas/moderation")
def owner_ideas(status: str = Query(default="pending"),
                x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data")):
    user = _identity(x_telegram_init_data)
    core.require_owner(user)
    if status not in {"pending", "approved", "rejected", "all"}:
        raise HTTPException(status_code=400, detail="Некорректный фильтр")
    with core.SessionLocal() as session:
        query = (select(InteractiveIdea, core.User)
                 .join(core.User, core.User.telegram_id == InteractiveIdea.telegram_id)
                 .order_by(InteractiveIdea.id.desc()).limit(200))
        if status != "all":
            query = query.where(InteractiveIdea.status == status)
        records = [_serialize(idea, submitter) for idea, submitter in session.execute(query).all()]
    return {"ok": True, "ideas": records}


@router.post("/api/interactive-ideas/{idea_id}/review")
def review_idea(idea_id: int, payload: ReviewRequest,
                x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data")):
    admin = _identity(x_telegram_init_data)
    core.require_owner(admin)
    if payload.decision not in {"approve", "reject"}:
        raise HTTPException(status_code=400, detail="Некорректное решение")
    note = _normalize(payload.note or "")[:600] or None
    timestamp = core.now_utc()
    with core.SessionLocal.begin() as session:
        row = session.scalar(select(InteractiveIdea)
                             .where(InteractiveIdea.id == idea_id)
                             .with_for_update())
        if row is None:
            raise HTTPException(status_code=404, detail="Заявка не найдена")
        if row.status != "pending":
            raise HTTPException(status_code=409, detail="Заявка уже рассмотрена")
        submitter = session.scalar(select(core.User)
                                   .where(core.User.telegram_id == row.telegram_id)
                                   .with_for_update())
        if submitter is None:
            raise HTTPException(status_code=404, detail="Кошелёк автора не найден")
        if payload.decision == "approve" and session.get(BlockedUser, submitter.telegram_id) is not None:
            raise HTTPException(status_code=403, detail="Нельзя начислять награду заблокированному аккаунту")
        row.status = "approved" if payload.decision == "approve" else "rejected"
        row.moderator_note = note
        row.reviewed_by = admin["id"]
        row.reviewed_at = timestamp
        if row.status == "approved":
            submitter.balance += REWARD_AMOUNT
            row.rewarded_at = timestamp
            session.add(core.Transaction(
                telegram_id=submitter.telegram_id,
                amount=REWARD_AMOUNT,
                operation_type="interactive_idea_reward",
                description=f"{REWARD_REASON} №{row.id}",
                created_at=timestamp,
            ))
        else:
            from .advanced_features import WalletNotification
            session.add(WalletNotification(
                telegram_id=submitter.telegram_id,
                kind="interactive_idea_rejected",
                title="Идея интерактива отклонена",
                body="Повторная заявка недоступна." + (f" Комментарий: {note}" if note else ""),
                is_read=False,
                created_at=timestamp,
            ))
        session.flush()
        result = _serialize(row, submitter)
    if result["status"] == "rejected":
        _notify(result["telegram_id"],
                "Ваша идея интерактива отклонена. Повторная подача недоступна."
                + (f"\nКомментарий: {note}" if note else ""))
    # On approval the existing transaction hook queues the +500 wallet
    # notification and owner copy in the same DB transaction.
    return {"ok": True, "idea": result}


def register_interactive_ideas(app) -> None:
    global _REGISTERED
    if _REGISTERED:
        return
    core.Base.metadata.create_all(core.engine, tables=[InteractiveIdea.__table__])
    app.include_router(router)
    _REGISTERED = True
