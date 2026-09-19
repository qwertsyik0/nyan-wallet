from __future__ import annotations

import hashlib
import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, LargeBinary, String, Text, UniqueConstraint, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, Session, mapped_column

from server import backend_app as core
from server.extended_features import audit
from server.advanced_features import WalletNotification

logger = logging.getLogger("nyan_wallet.appeals")

router = APIRouter()
_REGISTERED = False

MINI_APP_BASE_URL = "https://qwertsyik0.github.io/nyan-wallet"
MAX_SKIN_IMAGE_BYTES = 2 * 1024 * 1024
ALLOWED_IMAGE_MIME = {"image/png", "image/jpeg", "image/webp"}
APPEAL_STATUSES = {"new", "viewed", "in_progress", "approved", "completed", "rejected"}
OPEN_APPEAL_STATUSES = {"new", "viewed", "in_progress", "approved"}
TERMINAL_APPEAL_STATUSES = {"completed", "rejected"}


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def normalize_optional_text(value: str | None, *, max_length: int) -> str | None:
    if value is None:
        return None
    text = value.strip()
    if not text:
        return None
    if len(text) > max_length:
        raise HTTPException(status_code=400, detail=f"Текст слишком длинный. Максимум {max_length} символов.")
    return text


def human_user(user: core.User) -> str:
    if user.username:
        return f"@{user.username}"
    name = " ".join(part for part in [user.first_name, user.last_name] if part).strip()
    return name or f"ID {user.telegram_id}"


class AppealTopic(core.Base):
    __tablename__ = "appeal_topics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    form_type: Mapped[str] = mapped_column(String(32), nullable=False, default="general")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Appeal(core.Base):
    __tablename__ = "appeals"
    __table_args__ = (
        UniqueConstraint("topic_id", "telegram_id", name="uq_appeal_topic_user"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    public_id: Mapped[str | None] = mapped_column(String(24), nullable=True, unique=True, index=True)
    topic_id: Mapped[int] = mapped_column(Integer, ForeignKey("appeal_topics.id", ondelete="RESTRICT"), nullable=False, index=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.telegram_id", ondelete="CASCADE"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="new", index=True)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    favorite_colors: Mapped[str | None] = mapped_column(Text, nullable=True)
    avoid_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    extra_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    viewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AppealMessage(core.Base):
    __tablename__ = "appeal_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    appeal_id: Mapped[int] = mapped_column(Integer, ForeignKey("appeals.id", ondelete="CASCADE"), nullable=False, index=True)
    author_role: Mapped[str] = mapped_column(String(16), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)


class AppealStatusHistory(core.Base):
    __tablename__ = "appeal_status_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    appeal_id: Mapped[int] = mapped_column(Integer, ForeignKey("appeals.id", ondelete="CASCADE"), nullable=False, index=True)
    from_status: Mapped[str] = mapped_column(String(20), nullable=False)
    to_status: Mapped[str] = mapped_column(String(20), nullable=False)
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class WalletSkin(core.Base):
    __tablename__ = "wallet_skins"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    text_theme: Mapped[str] = mapped_column(String(12), nullable=False, default="dark")
    image_mime: Mapped[str] = mapped_column(String(32), nullable=False)
    image_data: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    image_sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    is_template: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    created_by_appeal_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("appeals.id", ondelete="SET NULL"), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class UserWalletSkin(core.Base):
    __tablename__ = "user_wallet_skins"
    __table_args__ = (
        UniqueConstraint("telegram_id", "skin_id", name="uq_user_wallet_skin"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.telegram_id", ondelete="CASCADE"), nullable=False, index=True)
    skin_id: Mapped[int] = mapped_column(Integer, ForeignKey("wallet_skins.id", ondelete="RESTRICT"), nullable=False, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    acquired_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AppealCreatePayload(BaseModel):
    topic_id: int = Field(ge=1)
    message: str = Field(min_length=1, max_length=1500)
    favorite_colors: str | None = Field(default=None, max_length=300)
    avoid_text: str | None = Field(default=None, max_length=500)
    extra_comment: str | None = Field(default=None, max_length=800)


class AppealMessagePayload(BaseModel):
    body: str = Field(min_length=1, max_length=1500)


class AppealStatusPayload(BaseModel):
    status: Literal["new", "viewed", "in_progress", "approved", "completed", "rejected"]


class OwnerReplyPayload(BaseModel):
    body: str = Field(min_length=1, max_length=1500)


class TopicCreatePayload(BaseModel):
    code: str = Field(min_length=2, max_length=64)
    title: str = Field(min_length=1, max_length=120)
    description: str = Field(min_length=1, max_length=1200)
    form_type: Literal["general", "custom_wallet"] = "general"
    starts_at: datetime | None = None
    ends_at: datetime | None = None


class AssignSkinPayload(BaseModel):
    skin_id: int = Field(ge=1)
    complete_appeal: bool = True


def is_topic_available(topic: AppealTopic, timestamp: datetime) -> bool:
    if not topic.is_active:
        return False
    if topic.starts_at is not None and topic.starts_at > timestamp:
        return False
    if topic.ends_at is not None and topic.ends_at <= timestamp:
        return False
    return True


def serialize_topic(topic: AppealTopic, appeal: Appeal | None = None) -> dict:
    return {
        "id": topic.id,
        "code": topic.code,
        "title": topic.title,
        "description": topic.description,
        "form_type": topic.form_type,
        "starts_at": topic.starts_at.isoformat() if topic.starts_at else None,
        "ends_at": topic.ends_at.isoformat() if topic.ends_at else None,
        "my_appeal": serialize_appeal_summary(appeal) if appeal else None,
    }


def serialize_appeal_summary(item: Appeal) -> dict:
    return {
        "id": item.id,
        "public_id": item.public_id or f"NWR-{item.id:06d}",
        "topic_id": item.topic_id,
        "status": item.status,
        "created_at": item.created_at.isoformat(),
        "updated_at": item.updated_at.isoformat(),
    }


def serialize_skin(skin: WalletSkin, *, owned: bool = False, active: bool = False) -> dict:
    return {
        "id": skin.id,
        "title": skin.title,
        "description": skin.description,
        "text_theme": skin.text_theme,
        "is_template": skin.is_template,
        "is_active": skin.is_active,
        "owned": owned,
        "active": active,
        "image_sha256": skin.image_sha256,
        "created_at": skin.created_at.isoformat(),
    }


def serialize_messages(session: Session, appeal_id: int) -> list[dict]:
    rows = session.scalars(
        select(AppealMessage)
        .where(AppealMessage.appeal_id == appeal_id)
        .order_by(AppealMessage.id.asc())
    ).all()
    return [
        {
            "id": row.id,
            "author_role": row.author_role,
            "body": row.body,
            "created_at": row.created_at.isoformat(),
        }
        for row in rows
    ]


def serialize_appeal_detail(session: Session, item: Appeal) -> dict:
    topic = session.get(AppealTopic, item.topic_id)
    user = session.get(core.User, item.telegram_id)
    return {
        **serialize_appeal_summary(item),
        "topic": {
            "id": topic.id,
            "title": topic.title,
            "form_type": topic.form_type,
        } if topic else None,
        "user": {
            "telegram_id": user.telegram_id,
            "username": user.username,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "label": human_user(user),
        } if user else None,
        "message": item.message,
        "favorite_colors": item.favorite_colors,
        "avoid_text": item.avoid_text,
        "extra_comment": item.extra_comment,
        "viewed_at": item.viewed_at.isoformat() if item.viewed_at else None,
        "completed_at": item.completed_at.isoformat() if item.completed_at else None,
        "messages": serialize_messages(session, item.id),
    }


def detect_image_mime(data: bytes) -> str | None:
    if len(data) >= 8 and data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if len(data) >= 3 and data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if len(data) >= 12 and data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "image/webp"
    return None


async def read_limited_image(request: Request) -> tuple[bytes, str]:
    declared = request.headers.get("content-length")
    if declared:
        try:
            declared_size = int(declared)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Некорректный Content-Length") from exc
        if declared_size <= 0:
            raise HTTPException(status_code=400, detail="Файл пуст")
        if declared_size > MAX_SKIN_IMAGE_BYTES:
            raise HTTPException(status_code=413, detail="Изображение должно быть не больше 2 МБ")

    data = bytearray()
    async for chunk in request.stream():
        if not chunk:
            continue
        if len(data) + len(chunk) > MAX_SKIN_IMAGE_BYTES:
            raise HTTPException(status_code=413, detail="Изображение должно быть не больше 2 МБ")
        data.extend(chunk)

    if not data:
        raise HTTPException(status_code=400, detail="Файл пуст")

    detected = detect_image_mime(bytes(data))
    if detected is None:
        raise HTTPException(status_code=415, detail="Поддерживаются только PNG, JPEG и WEBP")

    declared_mime = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if declared_mime not in ALLOWED_IMAGE_MIME:
        raise HTTPException(status_code=415, detail="Некорректный тип изображения")
    if declared_mime != detected:
        raise HTTPException(status_code=415, detail="Тип файла не совпадает с содержимым")

    return bytes(data), detected


def send_telegram_json(chat_id: int | None, text: str, *, url: str | None = None, button_text: str | None = None) -> None:
    if not chat_id or not core.BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN или chat_id отсутствует")

    payload: dict = {"chat_id": int(chat_id), "text": text}
    if url and button_text:
        payload["reply_markup"] = {
            "inline_keyboard": [[
                {
                    "text": button_text,
                    "web_app": {"url": url},
                }
            ]]
        }

    request = urllib.request.Request(
        f"https://api.telegram.org/bot{core.BOT_TOKEN}/sendMessage",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            body = json.loads(response.read().decode("utf-8"))
        if not body.get("ok"):
            raise RuntimeError(str(body.get("description") or "Telegram API вернул ok=false"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Telegram HTTP {exc.code}: {detail[:500]}") from exc


def safe_owner_notification(text: str, appeal_id: int) -> None:
    try:
        send_telegram_json(
            core.OWNER_TELEGRAM_ID,
            text,
            url=f"{MINI_APP_BASE_URL}/?ownerAppeal={appeal_id}",
            button_text="Открыть обращение",
        )
    except Exception:
        logger.exception("Не удалось отправить владельцу уведомление об обращении %s", appeal_id)


def safe_user_notification(telegram_id: int, text: str, appeal_id: int) -> None:
    try:
        send_telegram_json(
            telegram_id,
            text,
            url=f"{MINI_APP_BASE_URL}/?appeal={appeal_id}",
            button_text="Открыть обращение",
        )
    except Exception:
        logger.exception("Не удалось отправить пользователю %s уведомление об обращении %s", telegram_id, appeal_id)


def add_wallet_notification(session: Session, telegram_id: int, title: str, body: str) -> None:
    session.add(
        WalletNotification(
            telegram_id=telegram_id,
            kind="appeal",
            title=title,
            body=body,
            is_read=False,
            created_at=now_utc(),
        )
    )


def ensure_default_topic() -> None:
    timestamp = now_utc()
    with core.SessionLocal() as session:
        topic = session.scalar(select(AppealTopic).where(AppealTopic.code == "CUSTOM_WALLET"))
        if topic is not None:
            return
        session.add(
            AppealTopic(
                code="CUSTOM_WALLET",
                title="Свой Nyan Wallet",
                description=(
                    "Оставьте заявку на индивидуальный дизайн кошелька. "
                    "Опишите желаемый стиль, цвета и детали. Владелец Нян рассмотрит обращение "
                    "и сможет установить уникальное оформление прямо в ваш Nyan Wallet."
                ),
                form_type="custom_wallet",
                is_active=True,
                starts_at=None,
                ends_at=None,
                created_at=timestamp,
                updated_at=timestamp,
            )
        )
        session.commit()


@router.get("/api/appeal-topics")
async def user_topics(x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data")):
    tg = core.verify_init_data(x_telegram_init_data or "")
    core.get_or_create_user(tg)
    timestamp = now_utc()
    with core.SessionLocal() as session:
        topics = session.scalars(
            select(AppealTopic).where(AppealTopic.is_active.is_(True)).order_by(AppealTopic.id.asc())
        ).all()
        user_appeals = {
            item.topic_id: item
            for item in session.scalars(
                select(Appeal).where(Appeal.telegram_id == tg["id"])
            ).all()
        }
        return {
            "ok": True,
            "topics": [
                serialize_topic(topic, user_appeals.get(topic.id))
                for topic in topics
                if is_topic_available(topic, timestamp)
            ],
        }


@router.post("/api/appeals")
async def create_appeal(
    payload: AppealCreatePayload,
    background_tasks: BackgroundTasks,
    x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data"),
):
    tg = core.verify_init_data(x_telegram_init_data or "")
    core.get_or_create_user(tg)

    message = payload.message.strip()
    if not message:
        raise HTTPException(status_code=400, detail="Напишите пожелания или суть обращения")

    favorite_colors = normalize_optional_text(payload.favorite_colors, max_length=300)
    avoid_text = normalize_optional_text(payload.avoid_text, max_length=500)
    extra_comment = normalize_optional_text(payload.extra_comment, max_length=800)
    timestamp = now_utc()

    try:
        with core.SessionLocal() as session:
            with session.begin():
                topic = session.scalar(
                    select(AppealTopic).where(AppealTopic.id == payload.topic_id).with_for_update()
                )
                if topic is None:
                    raise HTTPException(status_code=404, detail="Тема обращения не найдена")
                if not is_topic_available(topic, timestamp):
                    raise HTTPException(status_code=409, detail="Приём обращений по этой теме сейчас закрыт")

                existing = session.scalar(
                    select(Appeal).where(
                        Appeal.topic_id == topic.id,
                        Appeal.telegram_id == tg["id"],
                    )
                )
                if existing is not None:
                    raise HTTPException(
                        status_code=409,
                        detail=f"Вы уже отправили обращение {existing.public_id or f'NWR-{existing.id:06d}'}",
                    )

                item = Appeal(
                    public_id=None,
                    topic_id=topic.id,
                    telegram_id=tg["id"],
                    status="new",
                    message=message,
                    favorite_colors=favorite_colors,
                    avoid_text=avoid_text,
                    extra_comment=extra_comment,
                    created_at=timestamp,
                    updated_at=timestamp,
                    viewed_at=None,
                    completed_at=None,
                )
                session.add(item)
                session.flush()
                item.public_id = f"NWR-{item.id:06d}"
                add_wallet_notification(
                    session,
                    tg["id"],
                    "Обращение отправлено",
                    f"{item.public_id} · {topic.title}",
                )
                audit(session, "appeal_created", tg["id"], f"{item.public_id} · {topic.title}")
                result = serialize_appeal_detail(session, item)
                user = session.get(core.User, tg["id"])
                who = human_user(user) if user else f"ID {tg['id']}"

            text_parts = [
                f"Новое обращение {item.public_id}",
                f"{who} · ID {tg['id']}",
                f"Тема: {topic.title}",
                "",
                f"Пожелания: {message}",
            ]
            if favorite_colors:
                text_parts.append(f"Цвета: {favorite_colors}")
            if avoid_text:
                text_parts.append(f"Не использовать: {avoid_text}")
            if extra_comment:
                text_parts.append(f"Комментарий: {extra_comment}")
            background_tasks.add_task(safe_owner_notification, "\n".join(text_parts), item.id)
            return {"ok": True, "appeal": result}
    except IntegrityError as exc:
        raise HTTPException(status_code=409, detail="Вы уже отправили обращение по этой теме") from exc


@router.get("/api/appeals/me")
async def my_appeals(x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data")):
    tg = core.verify_init_data(x_telegram_init_data or "")
    core.get_or_create_user(tg)
    with core.SessionLocal() as session:
        rows = session.scalars(
            select(Appeal)
            .where(Appeal.telegram_id == tg["id"])
            .order_by(Appeal.id.desc())
            .limit(100)
        ).all()
        return {"ok": True, "appeals": [serialize_appeal_detail(session, item) for item in rows]}


@router.get("/api/appeals/{appeal_id}")
async def my_appeal_detail(
    appeal_id: int,
    x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data"),
):
    tg = core.verify_init_data(x_telegram_init_data or "")
    core.get_or_create_user(tg)
    with core.SessionLocal() as session:
        item = session.get(Appeal, appeal_id)
        if item is None or item.telegram_id != tg["id"]:
            raise HTTPException(status_code=404, detail="Обращение не найдено")
        return {"ok": True, "appeal": serialize_appeal_detail(session, item)}


@router.post("/api/appeals/{appeal_id}/messages")
async def user_add_message(
    appeal_id: int,
    payload: AppealMessagePayload,
    background_tasks: BackgroundTasks,
    x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data"),
):
    tg = core.verify_init_data(x_telegram_init_data or "")
    core.get_or_create_user(tg)
    body = payload.body.strip()
    if not body:
        raise HTTPException(status_code=400, detail="Сообщение пустое")
    timestamp = now_utc()

    with core.SessionLocal() as session:
        with session.begin():
            item = session.scalar(select(Appeal).where(Appeal.id == appeal_id).with_for_update())
            if item is None or item.telegram_id != tg["id"]:
                raise HTTPException(status_code=404, detail="Обращение не найдено")
            if item.status in TERMINAL_APPEAL_STATUSES:
                raise HTTPException(status_code=409, detail="Это обращение уже закрыто")
            session.add(AppealMessage(appeal_id=item.id, author_role="user", body=body, created_at=timestamp))
            item.updated_at = timestamp
            audit(session, "appeal_user_message", tg["id"], f"{item.public_id}")
            public_id = item.public_id or f"NWR-{item.id:06d}"
            user = session.get(core.User, tg["id"])
            who = human_user(user) if user else f"ID {tg['id']}"

        background_tasks.add_task(
            safe_owner_notification,
            f"Новое сообщение в {public_id}\n{who} · ID {tg['id']}\n\n{body}",
            appeal_id,
        )
    return {"ok": True}


@router.get("/api/owner/appeals")
async def owner_appeals(
    status: str | None = Query(default=None, max_length=20),
    q: str | None = Query(default=None, max_length=80),
    x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data"),
):
    tg = core.verify_init_data(x_telegram_init_data or "")
    core.require_owner(tg)

    if status and status not in APPEAL_STATUSES:
        raise HTTPException(status_code=400, detail="Некорректный статус")

    with core.SessionLocal() as session:
        stmt = (
            select(Appeal, AppealTopic, core.User)
            .join(AppealTopic, AppealTopic.id == Appeal.topic_id)
            .join(core.User, core.User.telegram_id == Appeal.telegram_id)
        )
        if status:
            stmt = stmt.where(Appeal.status == status)
        query = (q or "").strip()
        if query:
            filters = [
                func.lower(AppealTopic.title).contains(query.lower()),
                func.lower(core.User.first_name).contains(query.lower()),
                func.lower(func.coalesce(core.User.username, "")).contains(query.lower()),
                func.lower(func.coalesce(Appeal.public_id, "")).contains(query.lower()),
            ]
            if query.isdigit():
                filters.append(core.User.telegram_id == int(query))
            stmt = stmt.where(or_(*filters))
        rows = session.execute(stmt.order_by(Appeal.updated_at.desc()).limit(200)).all()

        items = []
        for item, topic, user in rows:
            items.append({
                **serialize_appeal_summary(item),
                "topic_title": topic.title,
                "form_type": topic.form_type,
                "user": {
                    "telegram_id": user.telegram_id,
                    "username": user.username,
                    "first_name": user.first_name,
                    "label": human_user(user),
                },
                "message_preview": item.message[:220],
            })
        return {"ok": True, "appeals": items}


@router.get("/api/owner/appeals/{appeal_id}")
async def owner_appeal_detail(
    appeal_id: int,
    x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data"),
):
    tg = core.verify_init_data(x_telegram_init_data or "")
    core.require_owner(tg)
    with core.SessionLocal() as session:
        item = session.get(Appeal, appeal_id)
        if item is None:
            raise HTTPException(status_code=404, detail="Обращение не найдено")
        return {"ok": True, "appeal": serialize_appeal_detail(session, item)}


@router.post("/api/owner/appeals/{appeal_id}/viewed")
async def mark_appeal_viewed(
    appeal_id: int,
    x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data"),
):
    tg = core.verify_init_data(x_telegram_init_data or "")
    core.require_owner(tg)
    timestamp = now_utc()
    with core.SessionLocal() as session:
        with session.begin():
            item = session.scalar(select(Appeal).where(Appeal.id == appeal_id).with_for_update())
            if item is None:
                raise HTTPException(status_code=404, detail="Обращение не найдено")
            if item.viewed_at is None:
                item.viewed_at = timestamp
            if item.status == "new":
                item.status = "viewed"
                item.updated_at = timestamp
                session.add(AppealStatusHistory(appeal_id=item.id, from_status="new", to_status="viewed", changed_at=timestamp))
    return {"ok": True}


@router.post("/api/owner/appeals/{appeal_id}/status")
async def owner_change_status(
    appeal_id: int,
    payload: AppealStatusPayload,
    background_tasks: BackgroundTasks,
    x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data"),
):
    tg = core.verify_init_data(x_telegram_init_data or "")
    core.require_owner(tg)
    timestamp = now_utc()

    with core.SessionLocal() as session:
        with session.begin():
            item = session.scalar(select(Appeal).where(Appeal.id == appeal_id).with_for_update())
            if item is None:
                raise HTTPException(status_code=404, detail="Обращение не найдено")
            previous = item.status
            if previous == payload.status:
                return {"ok": True, "status": previous}
            item.status = payload.status
            item.updated_at = timestamp
            if item.viewed_at is None:
                item.viewed_at = timestamp
            item.completed_at = timestamp if payload.status in TERMINAL_APPEAL_STATUSES else None
            session.add(
                AppealStatusHistory(
                    appeal_id=item.id,
                    from_status=previous,
                    to_status=payload.status,
                    changed_at=timestamp,
                )
            )
            add_wallet_notification(
                session,
                item.telegram_id,
                "Статус обращения изменён",
                f"{item.public_id} · {payload.status}",
            )
            audit(session, "appeal_status_changed", item.telegram_id, f"{item.public_id}: {previous} -> {payload.status}")
            telegram_id = item.telegram_id
            public_id = item.public_id or f"NWR-{item.id:06d}"

        background_tasks.add_task(
            safe_user_notification,
            telegram_id,
            f"{public_id}\nСтатус обращения изменён: {payload.status}",
            appeal_id,
        )
    return {"ok": True, "status": payload.status}


@router.post("/api/owner/appeals/{appeal_id}/reply")
async def owner_reply(
    appeal_id: int,
    payload: OwnerReplyPayload,
    background_tasks: BackgroundTasks,
    x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data"),
):
    tg = core.verify_init_data(x_telegram_init_data or "")
    core.require_owner(tg)
    body = payload.body.strip()
    if not body:
        raise HTTPException(status_code=400, detail="Ответ пустой")
    timestamp = now_utc()

    with core.SessionLocal() as session:
        with session.begin():
            item = session.scalar(select(Appeal).where(Appeal.id == appeal_id).with_for_update())
            if item is None:
                raise HTTPException(status_code=404, detail="Обращение не найдено")
            session.add(AppealMessage(appeal_id=item.id, author_role="owner", body=body, created_at=timestamp))
            item.updated_at = timestamp
            if item.viewed_at is None:
                item.viewed_at = timestamp
            if item.status == "new":
                session.add(AppealStatusHistory(appeal_id=item.id, from_status="new", to_status="viewed", changed_at=timestamp))
                item.status = "viewed"
            add_wallet_notification(session, item.telegram_id, f"Ответ по {item.public_id}", body)
            audit(session, "appeal_owner_reply", item.telegram_id, item.public_id)
            telegram_id = item.telegram_id
            public_id = item.public_id or f"NWR-{item.id:06d}"

        background_tasks.add_task(
            safe_user_notification,
            telegram_id,
            f"Ответ по {public_id}\n\n{body}",
            appeal_id,
        )
    return {"ok": True}


@router.get("/api/owner/appeal-topics")
async def owner_topics(x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data")):
    tg = core.verify_init_data(x_telegram_init_data or "")
    core.require_owner(tg)
    with core.SessionLocal() as session:
        rows = session.scalars(select(AppealTopic).order_by(AppealTopic.id.desc())).all()
        return {
            "ok": True,
            "topics": [
                {
                    "id": row.id,
                    "code": row.code,
                    "title": row.title,
                    "description": row.description,
                    "form_type": row.form_type,
                    "is_active": row.is_active,
                    "starts_at": row.starts_at.isoformat() if row.starts_at else None,
                    "ends_at": row.ends_at.isoformat() if row.ends_at else None,
                }
                for row in rows
            ],
        }


@router.post("/api/owner/appeal-topics")
async def owner_create_topic(
    payload: TopicCreatePayload,
    x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data"),
):
    tg = core.verify_init_data(x_telegram_init_data or "")
    core.require_owner(tg)
    code = payload.code.strip().upper().replace(" ", "_")
    title = payload.title.strip()
    description = payload.description.strip()
    if not code.replace("_", "").replace("-", "").isalnum():
        raise HTTPException(status_code=400, detail="Код темы: только буквы, цифры, _ и -")
    if not title or not description:
        raise HTTPException(status_code=400, detail="Название и описание обязательны")

    starts_at = payload.starts_at
    ends_at = payload.ends_at
    if starts_at and starts_at.tzinfo is None:
        starts_at = starts_at.replace(tzinfo=timezone.utc)
    if ends_at and ends_at.tzinfo is None:
        ends_at = ends_at.replace(tzinfo=timezone.utc)
    if starts_at and ends_at and ends_at <= starts_at:
        raise HTTPException(status_code=400, detail="Окончание должно быть позже начала")

    timestamp = now_utc()
    try:
        with core.SessionLocal() as session:
            item = AppealTopic(
                code=code,
                title=title,
                description=description,
                form_type=payload.form_type,
                is_active=True,
                starts_at=starts_at,
                ends_at=ends_at,
                created_at=timestamp,
                updated_at=timestamp,
            )
            session.add(item)
            audit(session, "appeal_topic_created", None, title)
            session.commit()
            session.refresh(item)
            return {"ok": True, "topic_id": item.id}
    except IntegrityError as exc:
        raise HTTPException(status_code=409, detail="Тема с таким кодом уже существует") from exc


@router.post("/api/owner/appeal-topics/{topic_id}/toggle")
async def owner_toggle_topic(
    topic_id: int,
    x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data"),
):
    tg = core.verify_init_data(x_telegram_init_data or "")
    core.require_owner(tg)
    with core.SessionLocal() as session:
        with session.begin():
            item = session.scalar(select(AppealTopic).where(AppealTopic.id == topic_id).with_for_update())
            if item is None:
                raise HTTPException(status_code=404, detail="Тема не найдена")
            item.is_active = not item.is_active
            item.updated_at = now_utc()
            audit(session, "appeal_topic_toggled", None, f"{item.title} · {item.is_active}")
            active = item.is_active
    return {"ok": True, "is_active": active}


@router.post("/api/owner/wallet-skins")
async def owner_create_wallet_skin(
    request: Request,
    title: str = Query(min_length=1, max_length=120),
    description: str | None = Query(default=None, max_length=500),
    text_theme: Literal["dark", "light"] = Query(default="dark"),
    is_template: bool = Query(default=False),
    appeal_id: int | None = Query(default=None, ge=1),
    x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data"),
):
    tg = core.verify_init_data(x_telegram_init_data or "")
    core.require_owner(tg)
    clean_title = title.strip()
    if not clean_title:
        raise HTTPException(status_code=400, detail="Название дизайна пустое")
    image_data, image_mime = await read_limited_image(request)
    digest = hashlib.sha256(image_data).hexdigest()
    timestamp = now_utc()

    with core.SessionLocal() as session:
        if appeal_id is not None and session.get(Appeal, appeal_id) is None:
            raise HTTPException(status_code=404, detail="Обращение не найдено")
        skin = WalletSkin(
            title=clean_title,
            description=normalize_optional_text(description, max_length=500),
            text_theme=text_theme,
            image_mime=image_mime,
            image_data=image_data,
            image_sha256=digest,
            is_template=is_template,
            is_active=True,
            created_by_appeal_id=appeal_id,
            created_at=timestamp,
        )
        session.add(skin)
        audit(session, "wallet_skin_created", None, f"{clean_title} · {digest[:12]}")
        session.commit()
        session.refresh(skin)
        return {"ok": True, "skin": serialize_skin(skin)}


@router.get("/api/owner/wallet-skins")
async def owner_wallet_skins(
    templates_only: bool = Query(default=False),
    x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data"),
):
    tg = core.verify_init_data(x_telegram_init_data or "")
    core.require_owner(tg)
    with core.SessionLocal() as session:
        stmt = select(WalletSkin).order_by(WalletSkin.id.desc())
        if templates_only:
            stmt = stmt.where(WalletSkin.is_template.is_(True), WalletSkin.is_active.is_(True))
        rows = session.scalars(stmt.limit(200)).all()
        return {"ok": True, "skins": [serialize_skin(row) for row in rows]}


@router.post("/api/owner/wallet-skins/{skin_id}/toggle")
async def owner_toggle_wallet_skin(
    skin_id: int,
    x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data"),
):
    tg = core.verify_init_data(x_telegram_init_data or "")
    core.require_owner(tg)
    with core.SessionLocal() as session:
        with session.begin():
            skin = session.scalar(select(WalletSkin).where(WalletSkin.id == skin_id).with_for_update())
            if skin is None:
                raise HTTPException(status_code=404, detail="Дизайн не найден")
            skin.is_active = not skin.is_active
            audit(session, "wallet_skin_toggled", None, f"#{skin.id} · {skin.is_active}")
            state = skin.is_active
    return {"ok": True, "is_active": state}


def assign_skin_to_user(session: Session, telegram_id: int, skin: WalletSkin, timestamp: datetime) -> UserWalletSkin:
    user = session.scalar(select(core.User).where(core.User.telegram_id == telegram_id).with_for_update())
    if user is None:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    assignments = session.scalars(
        select(UserWalletSkin)
        .where(UserWalletSkin.telegram_id == telegram_id)
        .with_for_update()
    ).all()
    current = None
    for row in assignments:
        row.is_active = False
        if row.skin_id == skin.id:
            current = row
    if current is None:
        current = UserWalletSkin(
            telegram_id=telegram_id,
            skin_id=skin.id,
            is_active=True,
            acquired_at=timestamp,
        )
        session.add(current)
    else:
        current.is_active = True
    return current


@router.post("/api/owner/appeals/{appeal_id}/assign-skin")
async def owner_assign_skin(
    appeal_id: int,
    payload: AssignSkinPayload,
    background_tasks: BackgroundTasks,
    x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data"),
):
    tg = core.verify_init_data(x_telegram_init_data or "")
    core.require_owner(tg)
    timestamp = now_utc()

    with core.SessionLocal() as session:
        with session.begin():
            appeal = session.scalar(select(Appeal).where(Appeal.id == appeal_id).with_for_update())
            if appeal is None:
                raise HTTPException(status_code=404, detail="Обращение не найдено")
            skin = session.scalar(select(WalletSkin).where(WalletSkin.id == payload.skin_id).with_for_update())
            if skin is None or not skin.is_active:
                raise HTTPException(status_code=404, detail="Дизайн не найден или отключён")
            assign_skin_to_user(session, appeal.telegram_id, skin, timestamp)
            previous_status = appeal.status
            if payload.complete_appeal and appeal.status != "completed":
                appeal.status = "completed"
                appeal.completed_at = timestamp
                appeal.updated_at = timestamp
                session.add(
                    AppealStatusHistory(
                        appeal_id=appeal.id,
                        from_status=previous_status,
                        to_status="completed",
                        changed_at=timestamp,
                    )
                )
            add_wallet_notification(
                session,
                appeal.telegram_id,
                "Новый дизайн Nyan Wallet",
                f"Для вас установлен дизайн «{skin.title}».",
            )
            audit(session, "wallet_skin_assigned", appeal.telegram_id, f"skin #{skin.id} · {appeal.public_id}")
            telegram_id = appeal.telegram_id
            public_id = appeal.public_id or f"NWR-{appeal.id:06d}"

        background_tasks.add_task(
            safe_user_notification,
            telegram_id,
            f"{public_id}\nВаш индивидуальный дизайн «{skin.title}» установлен в Nyan Wallet.",
            appeal_id,
        )
    return {"ok": True, "skin": serialize_skin(skin, owned=True, active=True)}


@router.get("/api/wallet-skins/me")
async def my_wallet_skins(x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data")):
    tg = core.verify_init_data(x_telegram_init_data or "")
    core.get_or_create_user(tg)
    with core.SessionLocal() as session:
        rows = session.execute(
            select(UserWalletSkin, WalletSkin)
            .join(WalletSkin, WalletSkin.id == UserWalletSkin.skin_id)
            .where(UserWalletSkin.telegram_id == tg["id"])
            .order_by(UserWalletSkin.is_active.desc(), UserWalletSkin.acquired_at.desc())
        ).all()
        return {
            "ok": True,
            "skins": [
                serialize_skin(skin, owned=True, active=assignment.is_active)
                for assignment, skin in rows
                if skin.is_active
            ],
        }


@router.post("/api/wallet-skins/{skin_id}/activate")
async def activate_my_wallet_skin(
    skin_id: int,
    x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data"),
):
    tg = core.verify_init_data(x_telegram_init_data or "")
    core.get_or_create_user(tg)
    timestamp = now_utc()
    with core.SessionLocal() as session:
        with session.begin():
            user = session.scalar(select(core.User).where(core.User.telegram_id == tg["id"]).with_for_update())
            if user is None:
                raise HTTPException(status_code=404, detail="Пользователь не найден")
            rows = session.scalars(
                select(UserWalletSkin).where(UserWalletSkin.telegram_id == tg["id"]).with_for_update()
            ).all()
            target = next((row for row in rows if row.skin_id == skin_id), None)
            if target is None:
                raise HTTPException(status_code=403, detail="Этот дизайн вам не принадлежит")
            skin = session.get(WalletSkin, skin_id)
            if skin is None or not skin.is_active:
                raise HTTPException(status_code=409, detail="Этот дизайн сейчас недоступен")
            for row in rows:
                row.is_active = row.id == target.id
            audit(session, "wallet_skin_activated", tg["id"], f"skin #{skin_id}")
        return {"ok": True, "skin_id": skin_id, "activated_at": timestamp.isoformat()}


@router.get("/api/wallet-skins/{skin_id}/image")
async def wallet_skin_image(
    skin_id: int,
    x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data"),
):
    tg = core.verify_init_data(x_telegram_init_data or "")
    core.get_or_create_user(tg)
    with core.SessionLocal() as session:
        skin = session.get(WalletSkin, skin_id)
        if skin is None or not skin.is_active:
            raise HTTPException(status_code=404, detail="Дизайн не найден")
        if not core.is_owner(tg["id"]):
            owned = session.scalar(
                select(UserWalletSkin.id).where(
                    UserWalletSkin.telegram_id == tg["id"],
                    UserWalletSkin.skin_id == skin_id,
                )
            )
            if owned is None:
                raise HTTPException(status_code=403, detail="Нет доступа к этому дизайну")
        return Response(
            content=skin.image_data,
            media_type=skin.image_mime,
            headers={
                "Cache-Control": "private, max-age=3600",
                "ETag": f'"{skin.image_sha256}"',
                "X-Content-Type-Options": "nosniff",
            },
        )


def register_appeals(app) -> None:
    global _REGISTERED
    if _REGISTERED:
        return
    core.Base.metadata.create_all(core.engine)
    ensure_default_topic()
    app.include_router(router)
    _REGISTERED = True
