"""Bind a private Telegram flood and verify participation using its admin bot.

No public invite link, title, request form or Telegram username is trusted as
proof of membership. The bind is owner-only, checked against Bot API, and stored
once. All event access must fail closed while it is missing or unavailable.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import BigInteger, DateTime, Integer, String, Text, select
from sqlalchemy.orm import Mapped, mapped_column

from . import backend_app as core


router = APIRouter()
_REGISTERED = False
BOT_APP_LINK = "https://t.me/nyancash_bot?startapp=nyan_takeover"
DEFAULT_CHAT_ID = int(os.getenv("NYAN_TAKEOVER_CHAT_ID", "-1003689150794"))
POST_LINK_RE = re.compile(r"(?:https?://)?t\.me/c/([1-9][0-9]{4,13})/[0-9]+(?:[/?#].*)?\Z", re.I)
CHAT_ID_RE = re.compile(r"-100[1-9][0-9]{4,13}\Z")


class TakeoverGroup(core.Base):
    __tablename__ = "takeover_2026_group"
    key: Mapped[str] = mapped_column(String(16), primary_key=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    bound_by: Mapped[int] = mapped_column(BigInteger, nullable=False)
    bound_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class TakeoverPublication(core.Base):
    __tablename__ = "takeover_2026_group_posts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    message_id: Mapped[int] = mapped_column(Integer, nullable=False)
    request_key: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    sent_by: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class BindRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    chat_link_or_id: str = Field(min_length=6, max_length=160)


class PublishRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    text: str = Field(min_length=1, max_length=2000)
    request_key: str = Field(min_length=16, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$")


def bot_api(method: str, payload: dict, *, timeout: int = 7) -> dict:
    if not core.BOT_TOKEN:
        raise HTTPException(503, "Telegram-бот не настроен")
    data = urllib.parse.urlencode({
        key: json.dumps(value, ensure_ascii=False, separators=(",", ":")) if isinstance(value, (dict,list)) else value
        for key, value in payload.items()
    }).encode("utf-8")
    req = urllib.request.Request(f"https://api.telegram.org/bot{core.BOT_TOKEN}/{method}",
                                 data=data, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            answer = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        raise HTTPException(503, "Telegram временно не отвечает, попробуй позже") from exc
    if not answer.get("ok"):
        # Never return Bot API URLs or token-bearing request details to clients.
        raise HTTPException(503, "Telegram не подтвердил права бота в группе")
    return answer.get("result") or {}


def parse_chat_id(value: str) -> int:
    normalized = value.strip()
    if CHAT_ID_RE.fullmatch(normalized):
        return int(normalized)
    link = POST_LINK_RE.fullmatch(normalized)
    if link:
        return int("-100" + link.group(1))
    raise HTTPException(422, "Нужна ссылка на сообщение вида t.me/c/123456/78 или ID -100…")


def bound_group(session) -> TakeoverGroup:
    group = session.get(TakeoverGroup, "flood")
    if not group:
        raise HTTPException(503, "Частный флуд пока не привязан. Дождись запуска.")
    return group


def group_member(session, telegram_id: int) -> bool:
    group = bound_group(session)
    result = bot_api("getChatMember", {"chat_id": group.chat_id, "user_id": telegram_id})
    status = result.get("status", "")
    return status in {"creator", "administrator", "member"} or (
        status == "restricted" and result.get("is_member") is True
    )


@router.get("/api/nyan-takeover/owner/group")
def owner_group(x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data")):
    tg = core.verify_init_data(x_telegram_init_data or "")
    core.require_owner(tg)
    with core.SessionLocal() as session:
        group = session.get(TakeoverGroup, "flood")
        posts = session.scalars(select(TakeoverPublication).order_by(TakeoverPublication.id.desc()).limit(10)).all()
        return {"ok": True, "bound": bool(group),
                "chat_id": group.chat_id if group else None,
                "title": group.title if group else None,
                "posts": [{"message_id": item.message_id, "sent_at": item.sent_at.isoformat(),
                           "text": item.text} for item in posts]}


@router.post("/api/nyan-takeover/owner/group/bind")
def owner_bind(payload: BindRequest, x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data")):
    tg = core.verify_init_data(x_telegram_init_data or "")
    core.require_owner(tg)
    chat_id = parse_chat_id(payload.chat_link_or_id)
    chat = bot_api("getChat", {"chat_id": chat_id})
    if chat.get("type") not in {"group", "supergroup"} or int(chat.get("id", 0)) != chat_id:
        raise HTTPException(409, "Это не группа Telegram")
    bot_id = bot_api("getMe", {}).get("id")
    member = bot_api("getChatMember", {"chat_id": chat_id, "user_id": bot_id})
    if member.get("status") not in {"creator", "administrator"}:
        raise HTTPException(409, "Для проверки участников бот должен быть администратором группы")
    title = str(chat.get("title") or "").strip()
    if not title:
        raise HTTPException(409, "У группы нет названия")
    with core.SessionLocal.begin() as session:
        row = session.get(TakeoverGroup, "flood")
        if row and row.chat_id != chat_id:
            raise HTTPException(409, "Уже привязана другая группа. Смену нужно согласовать отдельно")
        if row is None:
            session.add(TakeoverGroup(key="flood", chat_id=chat_id, title=title,
                                      bound_by=int(tg["id"]), bound_at=datetime.now(timezone.utc)))
    return {"ok": True, "bound": True, "title": title, "chat_id": chat_id}


@router.post("/api/nyan-takeover/owner/group/publish")
def owner_publish(payload: PublishRequest, x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data")):
    tg = core.verify_init_data(x_telegram_init_data or "")
    core.require_owner(tg)
    content = payload.text.strip()
    if not content:
        raise HTTPException(422, "Пустая публикация")
    with core.SessionLocal.begin() as session:
        group = bound_group(session)
        # Serialize publish requests to make retries of the same key harmless.
        if session.get_bind().dialect.name == "postgresql":
            from sqlalchemy import text as sql_text
            session.execute(sql_text("SELECT pg_advisory_xact_lock(20261031, 710)"))
        old = session.scalar(select(TakeoverPublication).where(TakeoverPublication.request_key == payload.request_key))
        if old:
            if old.text != content or old.chat_id != group.chat_id:
                raise HTTPException(409, "Ключ публикации уже использован")
            return {"ok": True, "repeated": True, "message_id": old.message_id}
        result = bot_api("sendMessage", {
            "chat_id": group.chat_id, "text": content,
            "reply_markup": {"inline_keyboard": [[{"text": "Открыть NYAN TAKEOVER", "url": BOT_APP_LINK}]]},
            "disable_web_page_preview": True,
        })
        message_id = result.get("message_id")
        if not isinstance(message_id, int):
            raise HTTPException(503, "Telegram не вернул ID опубликованного сообщения")
        session.add(TakeoverPublication(chat_id=group.chat_id, message_id=message_id,
                                        request_key=payload.request_key, text=content,
                                        sent_by=int(tg["id"]), sent_at=datetime.now(timezone.utc)))
    return {"ok": True, "repeated": False, "message_id": message_id}


def register_nyan_takeover_group(app) -> None:
    global _REGISTERED
    if _REGISTERED:
        return
    core.Base.metadata.create_all(core.engine, tables=[TakeoverGroup.__table__, TakeoverPublication.__table__], checkfirst=True)
    with core.SessionLocal.begin() as session:
        if session.get_bind().dialect.name == "postgresql":
            from sqlalchemy import text as sql_text
            session.execute(sql_text("SELECT pg_advisory_xact_lock(20261031, 712)"))
        if session.get(TakeoverGroup, "flood") is None:
            from .nyan_takeover import FLOOD_NAME
            session.add(TakeoverGroup(key="flood", chat_id=DEFAULT_CHAT_ID, title=FLOOD_NAME,
                                      bound_by=0, bound_at=datetime.now(timezone.utc)))
    app.include_router(router)
    _REGISTERED = True
