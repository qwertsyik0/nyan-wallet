"""Nyan Elections foundation: party registration, owner review and one-party membership.

No voting routes are exposed in this first release. Publishing electoral results,
starting ballots and awarding governing privileges require later, separately tested steps.
"""

from __future__ import annotations

import base64
import binascii
import io
import json
import logging
import os
import re
import urllib.error
import urllib.request
from datetime import datetime, timezone
from PIL import Image, ImageOps, UnidentifiedImageError
from typing import Literal
from urllib.parse import urlsplit

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, LargeBinary, String, Text, UniqueConstraint, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, mapped_column

from . import backend_app as core
from .user_bans import BlockedUser

router = APIRouter(prefix="/api/elections", tags=["elections"])
_REGISTERED = False
logger = logging.getLogger("nyan_wallet.elections")
ELECTIONS_WEB_APP_URL = "https://qwertsyik0.github.io/nyan-wallet/elections.html"
MAX_IMAGE_INPUT_BYTES = 2 * 1024 * 1024
MAX_IMAGE_PIXELS = 10_000_000
FIRST_RELEASE_UTC = datetime(2026, 10, 16, 20, 0, tzinfo=timezone.utc)

ACTIVE_PHASES = ("registration", "recruitment", "campaign")
JOIN_PHASES = ("recruitment", "campaign")
NEXT_PHASE = {
    "registration": "recruitment",
    "recruitment": "campaign",
}
SHORT_PATTERN = re.compile(r"^[A-Za-zА-Яа-яЁё0-9 -]{2,15}$")


class ElectionSeason(core.Base):
    __tablename__ = "election_seasons"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    phase: Mapped[str] = mapped_column(String(24), nullable=False, default="registration")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_by: Mapped[int] = mapped_column(BigInteger, nullable=False)


class ElectionParty(core.Base):
    __tablename__ = "election_parties"
    __table_args__ = (
        UniqueConstraint("season_id", "name_key", name="uq_election_party_season_name"),
        UniqueConstraint("season_id", "short_key", name="uq_election_party_season_short"),
        UniqueConstraint("season_id", "chair_id", name="uq_election_party_season_chair"),
        {"sqlite_autoincrement": True},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    season_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("election_seasons.id", ondelete="CASCADE"), nullable=False, index=True
    )
    chair_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.telegram_id", ondelete="RESTRICT"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    name_key: Mapped[str] = mapped_column(String(80), nullable=False)
    short_name: Mapped[str] = mapped_column(String(15), nullable=False)
    short_key: Mapped[str] = mapped_column(String(15), nullable=False)
    program: Mapped[str] = mapped_column(Text, nullable=False)
    emblem_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending", index=True)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decided_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    decision_note: Mapped[str | None] = mapped_column(String(300), nullable=True)


class ElectionPartyEmblem(core.Base):
    """Sanitized emblem bytes stored with the application data, not on ephemeral disk."""

    __tablename__ = "election_party_emblems"
    party_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("election_parties.id", ondelete="CASCADE"), primary_key=True
    )
    image_data: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    mime_type: Mapped[str] = mapped_column(String(40), nullable=False, default="image/webp")


class ElectionInitialRollback(core.Base):
    """One-off audit prevents later legitimate seasons being removed at restart."""

    __tablename__ = "election_initial_rollback_20261016"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    season_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(60), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ElectionMembership(core.Base):
    """Database-level guarantee: at most one party per person within a season."""

    __tablename__ = "election_memberships"
    __table_args__ = (UniqueConstraint("season_id", "telegram_id", name="uq_election_one_party"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    season_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("election_seasons.id", ondelete="CASCADE"), nullable=False, index=True
    )
    party_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("election_parties.id", ondelete="CASCADE"), nullable=False
    )
    telegram_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.telegram_id", ondelete="CASCADE"), nullable=False
    )
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CreateSeason(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    title: str = Field(min_length=4, max_length=120)

    @field_validator("title")
    @classmethod
    def normalize(cls, value: str) -> str:
        cleaned = " ".join(value.split())
        if len(cleaned) < 4:
            raise ValueError("Укажите название сезона")
        return cleaned


class CreateParty(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    name: str = Field(min_length=3, max_length=80)
    short_name: str = Field(min_length=2, max_length=15)
    program: str = Field(min_length=30, max_length=3000)
    emblem_url: str | None = Field(default=None, max_length=500)
    emblem_data: str | None = Field(default=None, max_length=2_900_000)

    @field_validator("name", "short_name")
    @classmethod
    def trim(cls, value: str) -> str:
        cleaned = " ".join(value.split())
        if not cleaned:
            raise ValueError("Поле не может быть пустым")
        return cleaned

    @field_validator("program")
    @classmethod
    def clean_program(cls, value: str) -> str:
        # Preserve paragraphs in party manifestos while rejecting blank filler.
        cleaned = value.replace("\r\n", "\n").strip()
        if len(cleaned) < 30 or not cleaned.strip():
            raise ValueError("Программа должна содержать не менее 30 символов")
        return cleaned

    @field_validator("short_name")
    @classmethod
    def check_short(cls, value: str) -> str:
        if not SHORT_PATTERN.fullmatch(value):
            raise ValueError("Аббревиатура должна содержать буквы, цифры, пробелы или дефисы")
        return value

    @field_validator("emblem_url")
    @classmethod
    def check_image_url(cls, value: str | None) -> str | None:
        if not value:
            return None
        value = value.strip()
        url = urlsplit(value)
        if url.scheme != "https" or not url.netloc or url.username or url.password:
            raise ValueError("Эмблема должна быть доступна по HTTPS")
        return value


def sanitize_emblem(raw: str | None) -> bytes | None:
    if not raw:
        return None
    if not raw.startswith("data:image/") or ";base64," not in raw:
        raise HTTPException(status_code=422, detail="Загрузите файл изображения из галереи")
    content_type, encoded = raw.split(";base64,", 1)
    if content_type not in {"data:image/png", "data:image/jpeg", "data:image/webp"}:
        raise HTTPException(status_code=422, detail="Разрешены PNG, JPEG и WebP")
    if len(encoded) > ((MAX_IMAGE_INPUT_BYTES + 2) // 3) * 4:
        raise HTTPException(status_code=413, detail="Максимальный размер изображения — 2 МБ")
    try:
        payload = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise HTTPException(status_code=422, detail="Изображение повреждено") from exc
    if not payload or len(payload) > MAX_IMAGE_INPUT_BYTES:
        raise HTTPException(status_code=413, detail="Максимальный размер изображения — 2 МБ")
    try:
        with Image.open(io.BytesIO(payload)) as source:
            if source.format not in {"PNG", "JPEG", "WEBP"}:
                raise ValueError("Unsupported image")
            if source.width * source.height > MAX_IMAGE_PIXELS:
                raise ValueError("Too many pixels")
            source.load()
            # Strip EXIF, author/device metadata and animations by re-encoding.
            with ImageOps.exif_transpose(source) as image:
                image.thumbnail((1024, 1024), Image.Resampling.LANCZOS)
                converted = image.convert("RGBA" if "A" in image.getbands() else "RGB")
                buffer = io.BytesIO()
                converted.save(buffer, format="WEBP", quality=83, method=4)
                return buffer.getvalue()
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as exc:
        raise HTTPException(status_code=422, detail="Не удалось обработать изображение") from exc


class ReviewParty(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    decision: Literal["approve", "reject"]
    note: str | None = Field(default=None, max_length=300)

    @field_validator("note")
    @classmethod
    def trim_note(cls, value: str | None) -> str | None:
        return " ".join(value.split()) or None if value is not None else None


class SetPhase(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    next_phase: Literal["recruitment", "campaign"]


def _store_election_notification(session, telegram_id: int | None, title: str, body: str) -> None:
    """In-wallet fallback saved in the same transaction as the party change."""
    if not telegram_id:
        return
    if session.get(core.User, int(telegram_id)) is None:
        return
    from .advanced_features import notify as wallet_notify
    wallet_notify(session, int(telegram_id), "elections", title, body)


def _send_party_telegram_notice(telegram_id: int | None, text: str, button_label: str) -> bool:
    """Best-effort private Telegram message, after the DB transaction commits.

    Delivery failure never changes the accepted/rejected status. User can still
    read the authoritative decision and reason in Nyan Wallet.
    """
    if not telegram_id or not core.BOT_TOKEN:
        return False
    payload = {
        "chat_id": int(telegram_id),
        "text": text[:3500],
        "reply_markup": {
            "inline_keyboard": [[{
                "text": button_label,
                "web_app": {"url": ELECTIONS_WEB_APP_URL},
            }]],
        },
    }
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{core.BOT_TOKEN}/sendMessage",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            answer = json.loads(response.read().decode("utf-8"))
        if answer.get("ok") is True:
            return True
        logger.warning("Election Telegram message rejected chat_id=%s", telegram_id)
    except (urllib.error.URLError, OSError, ValueError) as exc:
        logger.warning("Election Telegram message not delivered chat_id=%s reason=%s",
                       telegram_id, type(exc).__name__)
    return False


def timestamp() -> datetime:
    return datetime.now(timezone.utc)


def auth(init_data: str | None) -> int:
    data = core.verify_init_data(init_data or "", require_subscription=False)
    return int(data["id"])


def owner_auth(init_data: str | None) -> int:
    uid = auth(init_data)
    if not core.is_owner(uid):
        raise HTTPException(status_code=403, detail="Только владелец может управлять выборами")
    return uid


def require_account(session, uid: int) -> None:
    if session.get(core.User, uid) is None:
        raise HTTPException(status_code=403, detail="Сначала откройте свой кошелёк Nyan Wallet")
    if session.get(BlockedUser, uid) is not None:
        raise HTTPException(status_code=403, detail="Участие в выборах недоступно")


def latest_season(session, *, lock: bool = False) -> ElectionSeason | None:
    stmt = select(ElectionSeason).order_by(ElectionSeason.id.desc()).limit(1)
    return session.scalar(stmt.with_for_update() if lock else stmt)


def _party_group_invite(party: ElectionParty) -> str | None:
    """Resolve private party invite from protected server configuration.

    Invite links must never be included in public party listings or source code.
    Telegram can still allow forwarded invites; administrators should use
    join-request links for actual Telegram membership verification.
    """
    try:
        mapping = json.loads(os.getenv("NYAN_ELECTIONS_GROUP_INVITES", "{}"))
    except (TypeError, ValueError):
        logger.warning("Elections group invite configuration is invalid")
        return None
    if not isinstance(mapping, dict):
        return None
    name = " ".join(party.name.split()).casefold()
    for configured_name, configured_url in mapping.items():
        if not isinstance(configured_name, str) or not isinstance(configured_url, str):
            continue
        if " ".join(configured_name.split()).casefold() != name:
            continue
        url = configured_url.strip()
        parts = urlsplit(url)
        # Allow only Telegram's private invite URLs. Disallow query strings,
        # credentials and third-party links.
        if (parts.scheme == "https" and parts.netloc == "t.me"
                and re.fullmatch(r"/\+[A-Za-z0-9_-]{12,64}", parts.path)
                and not parts.query and not parts.fragment and not parts.username):
            return url
        logger.warning("Invalid Elections group invite URL configured for %s", party.id)
    return None


def party_data(party: ElectionParty, session, *, include_private: bool = False) -> dict:
    chair = session.get(core.User, party.chair_id)
    member_count = session.scalar(
        select(func.count(ElectionMembership.id)).where(ElectionMembership.party_id == party.id)
    ) or 0
    result = {
        "id": party.id,
        "name": party.name,
        "short_name": party.short_name,
        "program": party.program,
        "emblem_url": (
            f"/api/elections/parties/{party.id}/emblem"
            if session.get(ElectionPartyEmblem, party.id) is not None
            else party.emblem_url
        ),
        "chair_label": ("@" + chair.username) if chair and chair.username else (
            chair.first_name if chair else "пользователь"
        ),
        "member_count": int(member_count),
        "status": party.status,
    }
    if include_private:
        result.update({
            "chair_id": int(party.chair_id),
            "submitted_at": party.submitted_at.isoformat(),
            "decision_note": party.decision_note,
        })
    return result


@router.get("")
async def get_elections(x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data")):
    uid = auth(x_telegram_init_data)
    with core.SessionLocal() as session:
        season = latest_season(session)
        if season is None:
            result = {"ok": True, "season": None, "parties": [], "my_party_id": None, "is_owner": core.is_owner(uid)}
            if core.is_owner(uid):
                audit = session.get(ElectionInitialRollback, 1)
                result["initial_rollback"] = audit.status if audit else None
            return result
        approved = session.scalars(
            select(ElectionParty).where(
                ElectionParty.season_id == season.id, ElectionParty.status == "approved"
            ).order_by(ElectionParty.id)
        ).all()
        member = session.scalar(select(ElectionMembership).where(
            ElectionMembership.season_id == season.id,
            ElectionMembership.telegram_id == uid,
        ))
        owned_party = session.scalar(
            select(ElectionParty).where(ElectionParty.season_id == season.id, ElectionParty.chair_id == uid)
        ) if core.is_owner(uid) else None
        return {
            "ok": True,
            "is_owner": core.is_owner(uid),
            "initial_rollback": (session.get(ElectionInitialRollback, 1).status if core.is_owner(uid) and session.get(ElectionInitialRollback, 1) else None),
            "season": {"id": season.id, "title": season.title, "phase": season.phase},
            "parties": [party_data(p, session) for p in approved],
            "my_party_id": member.party_id if member else None,
            "my_party_group_url": (
                _party_group_invite(session.get(ElectionParty, member.party_id))
                if member and session.get(ElectionParty, member.party_id)
                else None
            ),
            "owned_party": party_data(owned_party, session, include_private=True) if owned_party else None,
            "applications": [
                party_data(p, session, include_private=True)
                for p in session.scalars(select(ElectionParty).where(
                    ElectionParty.season_id == season.id,
                    ElectionParty.chair_id == uid,
                    ElectionParty.status != "approved",
                ))
            ],
        }


@router.post("/owner/seasons")
async def owner_create_season(
    payload: CreateSeason,
    x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data"),
):
    uid = owner_auth(x_telegram_init_data)
    with core.SessionLocal() as session:
        with session.begin():
            previous = latest_season(session, lock=True)
            if previous and previous.phase != "closed":
                raise HTTPException(status_code=409, detail="Предыдущий сезон ещё не завершён")
            now = timestamp()
            season = ElectionSeason(title=payload.title, phase="registration",
                                    created_at=now, updated_at=now, created_by=uid)
            session.add(season)
            session.flush()
            season_id = season.id
    return {"ok": True, "season_id": season_id, "phase": "registration"}


@router.get("/parties/{party_id}/emblem")
async def serve_party_emblem(party_id: int):
    with core.SessionLocal() as session:
        party = session.get(ElectionParty, party_id)
        image = session.get(ElectionPartyEmblem, party_id) if party else None
        if not image:
            raise HTTPException(status_code=404, detail="Эмблема не найдена")
        return Response(
            content=image.image_data,
            media_type="image/webp",
            headers={"Cache-Control": "public, max-age=300", "X-Content-Type-Options": "nosniff"},
        )


def _submit_party(
    payload: CreateParty,
    background_tasks: BackgroundTasks,
    uid: int,
):
    """Ordinary users may submit one party; owners only moderate elections."""
    if core.is_owner(uid):
        raise HTTPException(status_code=403, detail="Владелец управляет выборами и не может создавать партии")
    sanitized_image = sanitize_emblem(payload.emblem_data)
    with core.SessionLocal() as session:
        try:
            with session.begin():
                require_account(session, uid)
                season = latest_season(session, lock=True)
                if not season or season.phase != "registration":
                    raise HTTPException(status_code=409, detail="Создавать партии можно только во время регистрации")
                existing = session.scalar(
                    select(ElectionParty.id).where(
                        ElectionParty.season_id == season.id,
                        ElectionParty.chair_id == uid,
                    )
                )
                if existing:
                    raise HTTPException(status_code=409, detail="Заявка на партию уже существует")
                party = ElectionParty(
                    season_id=season.id, chair_id=uid, name=payload.name,
                    name_key=payload.name.casefold(), short_name=payload.short_name,
                    short_key=payload.short_name.casefold(), program=payload.program,
                    emblem_url=payload.emblem_url, status="pending", submitted_at=timestamp()
                )
                session.add(party)
                session.flush()
                party_id = party.id
                if sanitized_image is not None:
                    session.add(ElectionPartyEmblem(
                        party_id=party_id, image_data=sanitized_image, mime_type="image/webp"
                    ))
                _store_election_notification(
                    session, uid, "Заявка на партию отправлена",
                    f"«{party.name}» (№{party.id}) ожидает рассмотрения владельцем."
                )
                _store_election_notification(
                    session, core.OWNER_TELEGRAM_ID, "Новая партия на рассмотрении",
                    f"Партия «{party.name}» (№{party.id}). "
                    f"Председатель: @{session.get(core.User, uid).username or uid}. "
                    "Откройте «Выборы» для решения."
                )
        except IntegrityError as exc:
            raise HTTPException(status_code=409, detail="Название или аббревиатура уже заняты") from exc
    background_tasks.add_task(
        _send_party_telegram_notice,
        core.OWNER_TELEGRAM_ID,
        f"🗳 NYAN ELECTIONS | Новая заявка №{party_id}\n\n"
        f"Название: {payload.name}\n"
        f"Аббревиатура: {payload.short_name}\n"
        f"Председатель: {uid}\n\n"
        "Откройте раздел «Выборы», чтобы принять или отклонить партию.",
        "🗳 Рассмотреть заявку",
    )
    return {"ok": True, "party_id": party_id, "status": "pending"}


@router.post("/parties")
async def create_party(
    payload: CreateParty,
    background_tasks: BackgroundTasks,
    x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data"),
):
    uid = auth(x_telegram_init_data)
    return _submit_party(payload, background_tasks, uid)


@router.post("/owner/parties/replace")
async def owner_replace_party(
    x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data"),
):
    owner_auth(x_telegram_init_data)
    raise HTTPException(
        status_code=403,
        detail="Создание и замена партий для владельца отключены. Рассматривать заявки по-прежнему можно.",
    )


@router.get("/owner/pending")
async def owner_pending(x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data")):
    owner_auth(x_telegram_init_data)
    with core.SessionLocal() as session:
        season = latest_season(session)
        if not season:
            return {"ok": True, "parties": []}
        parties = session.scalars(
            select(ElectionParty).where(
                ElectionParty.season_id == season.id, ElectionParty.status == "pending"
            ).order_by(ElectionParty.submitted_at, ElectionParty.id)
        ).all()
        return {"ok": True, "parties": [party_data(p, session, include_private=True) for p in parties]}


@router.post("/owner/parties/{party_id}/review")
async def owner_review_party(
    party_id: int,
    payload: ReviewParty,
    background_tasks: BackgroundTasks,
    x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data"),
):
    uid = owner_auth(x_telegram_init_data)
    if payload.decision == "reject" and not payload.note:
        raise HTTPException(status_code=422, detail="При отклонении укажите причину для заявителя")
    with core.SessionLocal() as session:
        try:
            with session.begin():
                season = latest_season(session, lock=True)
                if not season or season.phase != "registration":
                    raise HTTPException(status_code=409, detail="Модерация партий уже закрыта")
                party = session.scalar(select(ElectionParty).where(
                    ElectionParty.id == party_id, ElectionParty.season_id == season.id
                ).with_for_update())
                if not party:
                    raise HTTPException(status_code=404, detail="Партия не найдена")
                if party.status != "pending":
                    raise HTTPException(status_code=409, detail="Заявка уже рассмотрена")
                if payload.decision == "approve":
                    require_account(session, party.chair_id)
                    conflict = session.scalar(select(ElectionMembership.id).where(
                        ElectionMembership.season_id == season.id,
                        ElectionMembership.telegram_id == party.chair_id,
                    ))
                    if conflict:
                        raise HTTPException(status_code=409, detail="Председатель уже состоит в другой партии")
                    session.add(ElectionMembership(
                        season_id=season.id, party_id=party.id,
                        telegram_id=party.chair_id, joined_at=timestamp()
                    ))
                party.status = "approved" if payload.decision == "approve" else "rejected"
                party.decided_at = timestamp()
                party.decided_by = uid
                party.decision_note = payload.note
                applicant_id = int(party.chair_id)
                party_title = party.name
                verdict = "одобрена" if payload.decision == "approve" else "отклонена"
                decision_body = (
                    f"Ваша партия «{party_title}» (№{party_id}) {verdict}."
                    + (f" Причина: {payload.note}" if payload.note else "")
                )
                _store_election_notification(
                    session, applicant_id,
                    "Партия одобрена" if payload.decision == "approve" else "Партия отклонена",
                    decision_body,
                )
        except IntegrityError as exc:
            raise HTTPException(status_code=409, detail="Конфликт состава партии") from exc
    background_tasks.add_task(
        _send_party_telegram_notice, applicant_id,
        f"🗳 NYAN ELECTIONS\n\n{decision_body}",
        "🗳 Открыть мою партию",
    )
    return {"ok": True, "party_id": party_id, "status": party.status}


@router.post("/owner/phase")
async def owner_advance(
    payload: SetPhase,
    x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data"),
):
    owner_auth(x_telegram_init_data)
    with core.SessionLocal() as session:
        with session.begin():
            season = latest_season(session, lock=True)
            if not season or NEXT_PHASE.get(season.phase) != payload.next_phase:
                raise HTTPException(status_code=409, detail="Недопустимый этап выборов")
            if season.phase == "registration":
                pending = session.scalar(select(ElectionParty.id).where(
                    ElectionParty.season_id == season.id,
                    ElectionParty.status == "pending"
                ))
                if pending:
                    raise HTTPException(status_code=409, detail="Сначала рассмотрите все заявки партий")
            season.phase = payload.next_phase
            season.updated_at = timestamp()
            season_id = season.id
    return {"ok": True, "season_id": season_id, "phase": payload.next_phase}


@router.post("/parties/{party_id}/join")
async def join_party(
    party_id: int,
    x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data"),
):
    uid = auth(x_telegram_init_data)
    with core.SessionLocal() as session:
        try:
            with session.begin():
                require_account(session, uid)
                season = latest_season(session, lock=True)
                if not season or season.phase not in JOIN_PHASES:
                    raise HTTPException(status_code=409, detail="Набор в партии сейчас закрыт")
                party = session.scalar(select(ElectionParty).where(
                    ElectionParty.id == party_id, ElectionParty.season_id == season.id,
                    ElectionParty.status == "approved"
                ))
                if not party:
                    raise HTTPException(status_code=404, detail="Партия не найдена")
                existing = session.scalar(select(ElectionMembership).where(
                    ElectionMembership.season_id == season.id,
                    ElectionMembership.telegram_id == uid
                ))
                if existing:
                    if existing.party_id == party.id:
                        raise HTTPException(status_code=409, detail="Вы уже состоите в этой партии")
                    # Party change before balloting is allowed. A chair must remain
                    # chair of their own party until a leadership-transfer workflow exists.
                    current = session.get(ElectionParty, existing.party_id)
                    if current and current.chair_id == uid:
                        raise HTTPException(status_code=409, detail="Председатель не может покинуть свою партию")
                    existing.party_id = party.id
                    existing.joined_at = timestamp()
                else:
                    session.add(ElectionMembership(
                        season_id=season.id, party_id=party.id, telegram_id=uid,
                        joined_at=timestamp()
                    ))
        except IntegrityError as exc:
            raise HTTPException(status_code=409, detail="Не удалось вступить: конфликт членства") from exc
    return {"ok": True, "party_id": party_id}


@router.post("/parties/leave")
async def leave_party(x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data")):
    uid = auth(x_telegram_init_data)
    with core.SessionLocal() as session:
        with session.begin():
            require_account(session, uid)
            season = latest_season(session, lock=True)
            if not season or season.phase not in JOIN_PHASES:
                raise HTTPException(status_code=409, detail="Сменить партию сейчас нельзя")
            membership = session.scalar(select(ElectionMembership).where(
                ElectionMembership.season_id == season.id,
                ElectionMembership.telegram_id == uid
            ).with_for_update())
            if not membership:
                raise HTTPException(status_code=404, detail="Вы не состоите в партии")
            party = session.get(ElectionParty, membership.party_id)
            if party and party.chair_id == uid:
                raise HTTPException(status_code=409, detail="Председатель не может покинуть свою партию")
            session.delete(membership)
    return {"ok": True}


def rollback_first_empty_season_once() -> str:
    """User-requested cancellation of the initially created season.

    Delete ONLY the one first season after feature activation and only if no
    parties or memberships exist. Persist the outcome so later restarts cannot
    remove new user-created seasons. Never change balances or user accounts.
    """
    with core.SessionLocal() as session:
        with session.begin():
            if session.get(ElectionInitialRollback, 1) is not None:
                return "already_processed"
            season = latest_season(session, lock=True)
            season_id = season.id if season else None
            count = session.scalar(select(func.count(ElectionSeason.id))) or 0
            status = "no_initial_season"
            if season is not None:
                created = season.created_at
                if created.tzinfo is None:
                    created = created.replace(tzinfo=timezone.utc)
                if (count != 1 or season.id != 1 or season.phase != "registration"
                        or created < FIRST_RELEASE_UTC):
                    status = "skipped_not_initial_registration"
                else:
                    has_parties = session.scalar(select(ElectionParty.id).where(ElectionParty.season_id == season.id).limit(1))
                    has_members = session.scalar(select(ElectionMembership.id).where(ElectionMembership.season_id == season.id).limit(1))
                    if has_parties is not None or has_members is not None:
                        status = "skipped_contains_party_data"
                    else:
                        session.delete(season)
                        status = "empty_initial_season_rolled_back"
            session.add(ElectionInitialRollback(
                id=1, season_id=season_id, status=status, created_at=timestamp()
            ))
    logger.warning("election_initial_rollback season_id=%s result=%s", season_id, status)
    return status


def register_elections(app) -> None:
    global _REGISTERED
    if _REGISTERED:
        return
    ElectionSeason.__table__.create(bind=core.engine, checkfirst=True)
    ElectionParty.__table__.create(bind=core.engine, checkfirst=True)
    ElectionMembership.__table__.create(bind=core.engine, checkfirst=True)
    ElectionPartyEmblem.__table__.create(bind=core.engine, checkfirst=True)
    ElectionInitialRollback.__table__.create(bind=core.engine, checkfirst=True)
    rollback_first_empty_season_once()
    app.include_router(router)
    _REGISTERED = True
