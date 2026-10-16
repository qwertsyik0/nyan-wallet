"""Nyan Elections foundation: party registration, owner review and one-party membership.

No voting routes are exposed in this first release. Publishing electoral results,
starting ballots and awarding governing privileges require later, separately tested steps.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Literal
from urllib.parse import urlsplit

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, mapped_column

from . import backend_app as core
from .user_bans import BlockedUser

router = APIRouter(prefix="/api/elections", tags=["elections"])
_REGISTERED = False

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
        "emblem_url": party.emblem_url,
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
            return {"ok": True, "season": None, "parties": [], "my_party_id": None}
        approved = session.scalars(
            select(ElectionParty).where(
                ElectionParty.season_id == season.id, ElectionParty.status == "approved"
            ).order_by(ElectionParty.id)
        ).all()
        member = session.scalar(select(ElectionMembership).where(
            ElectionMembership.season_id == season.id,
            ElectionMembership.telegram_id == uid,
        ))
        return {
            "ok": True,
            "season": {"id": season.id, "title": season.title, "phase": season.phase},
            "parties": [party_data(p, session) for p in approved],
            "my_party_id": member.party_id if member else None,
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


@router.post("/parties")
async def create_party(
    payload: CreateParty,
    x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data"),
):
    uid = auth(x_telegram_init_data)
    with core.SessionLocal() as session:
        try:
            with session.begin():
                require_account(session, uid)
                season = latest_season(session, lock=True)
                if not season or season.phase != "registration":
                    raise HTTPException(status_code=409, detail="Регистрация партий сейчас закрыта")
                existing = session.scalar(select(ElectionParty.id).where(
                    ElectionParty.season_id == season.id, ElectionParty.chair_id == uid
                ))
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
        except IntegrityError as exc:
            raise HTTPException(status_code=409, detail="Название или аббревиатура уже заняты") from exc
    return {"ok": True, "party_id": party_id, "status": "pending"}


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
    x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data"),
):
    uid = owner_auth(x_telegram_init_data)
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
        except IntegrityError as exc:
            raise HTTPException(status_code=409, detail="Конфликт состава партии") from exc
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


def register_elections(app) -> None:
    global _REGISTERED
    if _REGISTERED:
        return
    ElectionSeason.__table__.create(bind=core.engine, checkfirst=True)
    ElectionParty.__table__.create(bind=core.engine, checkfirst=True)
    ElectionMembership.__table__.create(bind=core.engine, checkfirst=True)
    app.include_router(router)
    _REGISTERED = True
