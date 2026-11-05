"""NYAN AWARDS 2026: authenticated nominations, consent and secret ballots.

The public page never receives intermediate counts. The special partner-flood
ballot is restricted to verified members of the bound Telegram group.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, UniqueConstraint, func, select
from sqlalchemy.orm import Mapped, mapped_column

from . import backend_app as core


router = APIRouter()
_REGISTERED = False
MSK = ZoneInfo("Europe/Moscow")

CATEGORIES = (
    ("legend_nyan", "Легенда Нян", "Главная награда экосистемы", "100 ⭐ · физ. аккаунт Японии · 600 🐾"),
    ("soul_nyan", "Душа Нян", "Тот, кто делает сообщество теплее", "250 🐾"),
    ("face_nyan", "Лицо Нян", "Самый узнаваемый участник", "50 ⭐ · 300 🐾"),
    ("discovery", "Открытие года", "Главное новое имя года", "150 🐾"),
    ("creator", "Творец Нян", "Идеи, творчество и вдохновение", "200 🐾"),
    ("engine", "Двигатель Нян", "Человек, который двигает проекты вперёд", "200 🐾"),
    ("games_legend", "Легенда Nyan Games", "Выдающиеся игровые достижения", "25 ⭐ · физ. аккаунт · 250 🐾"),
    ("mafia_master", "Мастер мафии", "Игра, тактика и победы", "200 🐾"),
    ("finance", "Финансовый стратег", "Успехи в экономике Nyan Wallet", "150 🐾"),
    ("admin", "Администратор года", "Забота о проектах и участниках", "200 🐾"),
    ("flood_legend", "Легенда флуда", "Специальная номинация партнёрского флуда", "75 ⭐ · физ. аккаунт · 300 🐾"),
)
CATEGORY_IDS = {row[0] for row in CATEGORIES}
EVIDENCE_CATEGORIES = {"games_legend", "mafia_master", "finance"}
FLOOD_CATEGORY = "flood_legend"


class AwardNomination(core.Base):
    __tablename__ = "nyan_awards_nominations_2026"
    __table_args__ = (UniqueConstraint("category", "candidate_key", name="uq_awards_candidate_category_2026"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    category: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    candidate_key: Mapped[str] = mapped_column(String(90), nullable=False)
    candidate_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.telegram_id"), nullable=True)
    candidate_username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    nominated_by: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.telegram_id"), nullable=False)
    reason: Mapped[str] = mapped_column(String(320), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AwardVote(core.Base):
    __tablename__ = "nyan_awards_votes_2026"
    __table_args__ = (UniqueConstraint("voter_id", "category", name="uq_awards_vote_category_2026"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    voter_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.telegram_id"), nullable=False)
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    candidate_id: Mapped[int] = mapped_column(Integer, ForeignKey("nyan_awards_nominations_2026.id"), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AwardWinner(core.Base):
    """Verified achievement winner or a human-resolved tied public ballot."""

    __tablename__ = "nyan_awards_winners_2026"

    category: Mapped[str] = mapped_column(String(32), primary_key=True)
    nomination_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("nyan_awards_nominations_2026.id"), nullable=False
    )
    selected_by: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.telegram_id"), nullable=False)
    justification: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    selected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class NominateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    category: str = Field(min_length=3, max_length=32)
    nominee: str = Field(min_length=2, max_length=65)
    reason: str = Field(default="", max_length=320)


class ConfirmBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    nomination_id: int = Field(ge=1)
    accept: bool


class VoteBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    category: str = Field(min_length=3, max_length=32)
    nomination_id: int = Field(ge=1)


class FinalistBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    nomination_id: int = Field(ge=1)
    finalist: bool


class WinnerBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    category: str = Field(min_length=3, max_length=32)
    nomination_id: int = Field(ge=1)
    justification: str = Field(default="", max_length=500)


def phase_at(now: datetime | None = None) -> str:
    current = (now or core.now_utc()).astimezone(MSK)
    if current < datetime(2026, 11, 5, tzinfo=MSK):
        return "soon"
    if current < datetime(2026, 11, 7, tzinfo=MSK):
        return "nominations"
    if current < datetime(2026, 11, 8, tzinfo=MSK):
        return "review"
    if current < datetime(2026, 11, 9, tzinfo=MSK):
        return "voting"
    if current < datetime(2026, 11, 9, 19, tzinfo=MSK):
        return "ceremony_wait"
    return "results"


def _auth(init_data: str | None) -> dict:
    tg = core.verify_init_data(init_data or "")
    core.get_or_create_user(tg)
    return tg


def _username(tg: dict) -> str:
    return str(tg.get("username") or "").lstrip("@").lower().strip()


def _display(tg: dict) -> str:
    return str(tg.get("first_name") or "Участник")[:100]


def _candidate_for_user(candidate: AwardNomination, tg: dict) -> bool:
    if candidate.candidate_id is not None:
        return candidate.candidate_id == int(tg["id"])
    return bool(_username(tg) and candidate.candidate_username == _username(tg))


def _check_partner_member(session, telegram_id: int) -> None:
    from .nyan_takeover_group import group_member
    if not group_member(session, telegram_id):
        raise HTTPException(403, "Номинация доступна участникам партнёрского флуда")


def _serialize(candidate: AwardNomination) -> dict:
    return {
        "id": candidate.id,
        "category": candidate.category,
        "name": candidate.display_name,
        "username": candidate.candidate_username,
        "status": candidate.status,
        "reason": candidate.reason,
    }


def _ballot_counts(session) -> dict[int, int]:
    return {
        int(candidate_id): int(total)
        for candidate_id, total in session.execute(
            select(AwardVote.candidate_id, func.count(AwardVote.id)).group_by(AwardVote.candidate_id)
        ).all()
    }


def _leaders(finalists: list[AwardNomination], counts: dict[int, int]) -> list[int]:
    if not finalists:
        return []
    highest = max(counts.get(candidate.id, 0) for candidate in finalists)
    if highest == 0:
        return []
    return [candidate.id for candidate in finalists if counts.get(candidate.id, 0) == highest]


def _resolved_winners(
    nominations: list[AwardNomination], counts: dict[int, int],
    manual: dict[str, int],
) -> dict[str, int]:
    result = {}
    for category in CATEGORY_IDS:
        finalists = [n for n in nominations if n.category == category and n.status == "finalist"]
        if category in EVIDENCE_CATEGORIES:
            if manual.get(category) in {n.id for n in finalists}:
                result[category] = manual[category]
            continue
        leaders = _leaders(finalists, counts)
        if len(leaders) == 1:
            result[category] = leaders[0]
        elif len(leaders) > 1 and manual.get(category) in leaders:
            result[category] = manual[category]
    return result


@router.get("/api/nyan-awards/status")
def awards_status(x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data")):
    tg = _auth(x_telegram_init_data)
    uid = int(tg["id"])
    phase = phase_at()
    with core.SessionLocal() as session:
        nominations = session.scalars(select(AwardNomination).order_by(AwardNomination.id.asc())).all()
        votes = session.scalars(select(AwardVote).where(AwardVote.voter_id == uid)).all()
        mine = [_serialize(n) for n in nominations if _candidate_for_user(n, tg)]
        finalists = [_serialize(n) for n in nominations if n.status == "finalist"] if phase in {"voting", "ceremony_wait", "results"} else []
        response = {
            "phase": phase,
            "categories": [{"key": k, "title": title, "description": description, "prize": prize,
                            "evidence_based": k in EVIDENCE_CATEGORIES, "partner": k == FLOOD_CATEGORY}
                           for k, title, description, prize in CATEGORIES],
            "my_nominations": mine,
            "finalists": finalists,
            "my_votes": {vote.category: vote.candidate_id for vote in votes},
            "ceremony_at": "2026-11-09T19:00:00+03:00",
        }
        if phase == "results":
            counts = _ballot_counts(session)
            manual = {row.category: row.nomination_id for row in session.scalars(select(AwardWinner)).all()}
            winners = _resolved_winners(nominations, counts, manual)
            response["results"] = [
                {**_serialize(n), "votes": counts.get(n.id, 0), "winner": winners.get(n.category) == n.id}
                for n in nominations if n.status == "finalist"
            ]
        return response


@router.post("/api/nyan-awards/nominate")
def awards_nominate(body: NominateBody, x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data")):
    tg = _auth(x_telegram_init_data)
    if phase_at() != "nominations":
        raise HTTPException(409, "Приём кандидатур сейчас закрыт")
    if body.category not in CATEGORY_IDS:
        raise HTTPException(422, "Неизвестная номинация")

    uid = int(tg["id"])
    self_nomination = body.nominee.strip().lower() in {"me", "self", "я"}
    nominee_username = _username(tg) if self_nomination else body.nominee.strip().lstrip("@").lower()
    if not self_nomination and (not nominee_username.isascii() or not nominee_username.replace("_", "").isalnum() or not 5 <= len(nominee_username) <= 32):
        raise HTTPException(422, "Укажи корректный @username кандидата")
    key = "name:" + nominee_username if nominee_username else f"id:{uid}"
    display = _display(tg) if self_nomination else "@" + nominee_username
    with core.SessionLocal() as session:
        with session.begin():
            if self_nomination and body.category == FLOOD_CATEGORY:
                _check_partner_member(session, uid)
            candidate = session.scalar(select(AwardNomination).where(
                AwardNomination.category == body.category, AwardNomination.candidate_key == key).with_for_update())
            if candidate is not None:
                if self_nomination and candidate.status == "awaiting_confirmation":
                    confirmed_count = session.scalar(select(func.count(AwardNomination.id)).where(
                        AwardNomination.candidate_id == uid,
                        AwardNomination.status.in_(("confirmed", "finalist")))) or 0
                    if confirmed_count >= 2:
                        raise HTTPException(409, "Можно участвовать максимум в двух номинациях")
                    candidate.candidate_id = uid
                    candidate.display_name = _display(tg)
                    candidate.status = "confirmed"
                    candidate.confirmed_at = core.now_utc()
                return {"ok": True, "nomination": _serialize(candidate), "already_exists": True}
            if self_nomination:
                confirmed_count = session.scalar(select(func.count(AwardNomination.id)).where(
                    AwardNomination.candidate_id == uid,
                    AwardNomination.status.in_(("confirmed", "finalist")))) or 0
                if confirmed_count >= 2:
                    raise HTTPException(409, "Можно участвовать максимум в двух номинациях")
            candidate = AwardNomination(
                category=body.category, candidate_key=key, candidate_id=uid if self_nomination else None,
                candidate_username=nominee_username or None, display_name=display,
                nominated_by=uid, reason=body.reason.strip(),
                status="confirmed" if self_nomination else "awaiting_confirmation",
                created_at=core.now_utc(), confirmed_at=core.now_utc() if self_nomination else None,
            )
            session.add(candidate)
            session.flush()
            return {"ok": True, "nomination": _serialize(candidate), "already_exists": False}


@router.post("/api/nyan-awards/confirm")
def awards_confirm(body: ConfirmBody, x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data")):
    tg = _auth(x_telegram_init_data)
    if phase_at() not in {"nominations", "review"}:
        raise HTTPException(409, "Подтверждение кандидатур закрыто")
    uid = int(tg["id"])
    with core.SessionLocal() as session:
        with session.begin():
            candidate = session.scalar(select(AwardNomination).where(AwardNomination.id == body.nomination_id).with_for_update())
            if candidate is None or not _candidate_for_user(candidate, tg):
                raise HTTPException(404, "Кандидатура не найдена")
            if candidate.status != "awaiting_confirmation":
                raise HTTPException(409, "Кандидатура уже обработана")
            if body.accept:
                if candidate.category == FLOOD_CATEGORY:
                    _check_partner_member(session, uid)
                count = session.scalar(select(func.count(AwardNomination.id)).where(
                    AwardNomination.candidate_id == uid, AwardNomination.status.in_(("confirmed", "finalist")))) or 0
                if count >= 2:
                    raise HTTPException(409, "Можно участвовать максимум в двух номинациях")
                candidate.candidate_id = uid
                candidate.display_name = _display(tg)
                candidate.status = "confirmed"
                candidate.confirmed_at = core.now_utc()
            else:
                candidate.status = "declined"
            return {"ok": True, "nomination": _serialize(candidate)}


@router.post("/api/nyan-awards/vote")
def awards_vote(body: VoteBody, x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data")):
    tg = _auth(x_telegram_init_data)
    if phase_at() != "voting":
        raise HTTPException(409, "Голосование сейчас закрыто")
    if body.category not in CATEGORY_IDS:
        raise HTTPException(422, "Неизвестная номинация")
    if body.category in EVIDENCE_CATEGORIES:
        raise HTTPException(403, "Победитель определяется по подтверждённым игровым достижениям")
    uid = int(tg["id"])
    with core.SessionLocal() as session:
        with session.begin():
            if body.category == FLOOD_CATEGORY:
                _check_partner_member(session, uid)
            finalist_count = session.scalar(select(func.count(AwardNomination.id)).where(
                AwardNomination.category == body.category, AwardNomination.status == "finalist")) or 0
            if finalist_count < 3:
                raise HTTPException(409, "Для голосования нужно хотя бы три подтверждённых финалиста")
            candidate = session.get(AwardNomination, body.nomination_id)
            if candidate is None or candidate.category != body.category or candidate.status != "finalist":
                raise HTTPException(422, "Этот финалист недоступен")
            existing = session.scalar(select(AwardVote).where(
                AwardVote.category == body.category, AwardVote.voter_id == uid).with_for_update())
            if existing:
                existing.candidate_id = candidate.id
                existing.updated_at = core.now_utc()
            else:
                session.add(AwardVote(voter_id=uid, category=body.category,
                                      candidate_id=candidate.id, updated_at=core.now_utc()))
            return {"ok": True, "category": body.category, "nomination_id": candidate.id}


@router.get("/api/owner/nyan-awards/candidates")
def owner_awards_candidates(x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data")):
    tg = _auth(x_telegram_init_data)
    core.require_owner(tg)
    with core.SessionLocal() as session:
        nominations = session.scalars(select(AwardNomination).order_by(AwardNomination.category, AwardNomination.id)).all()
        counts = _ballot_counts(session)
        manual = {row.category: {"nomination_id": row.nomination_id, "justification": row.justification}
                  for row in session.scalars(select(AwardWinner)).all()}
        ties = {
            category: _leaders([n for n in nominations if n.category == category and n.status == "finalist"], counts)
            for category in CATEGORY_IDS if category not in EVIDENCE_CATEGORIES
        }
        return {"phase": phase_at(), "candidates": [{**_serialize(n), "votes": counts.get(n.id, 0)} for n in nominations],
                "manual_winners": manual, "leaders": ties}


@router.post("/api/owner/nyan-awards/finalist")
def owner_awards_finalist(body: FinalistBody, x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data")):
    tg = _auth(x_telegram_init_data)
    core.require_owner(tg)
    if phase_at() != "review":
        raise HTTPException(409, "Финалистов можно утверждать только 7 ноября")
    with core.SessionLocal() as session:
        with session.begin():
            candidate = session.scalar(select(AwardNomination).where(AwardNomination.id == body.nomination_id).with_for_update())
            if candidate is None or candidate.status not in {"confirmed", "finalist"}:
                raise HTTPException(422, "Кандидат не подтвердил участие")
            if body.finalist:
                total = session.scalar(select(func.count(AwardNomination.id)).where(
                    AwardNomination.category == candidate.category, AwardNomination.status == "finalist")) or 0
                if candidate.status != "finalist" and total >= 5:
                    raise HTTPException(409, "В одной номинации может быть максимум 5 финалистов")
                candidate.status = "finalist"
            else:
                candidate.status = "confirmed"
            return {"ok": True, "nomination": _serialize(candidate)}


@router.post("/api/owner/nyan-awards/winner")
def owner_awards_winner(body: WinnerBody, x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data")):
    tg = _auth(x_telegram_init_data)
    core.require_owner(tg)
    if phase_at() != "ceremony_wait":
        raise HTTPException(409, "Победителей можно утвердить 9 ноября до начала церемонии")
    if body.category not in CATEGORY_IDS:
        raise HTTPException(422, "Неизвестная номинация")
    with core.SessionLocal() as session:
        with session.begin():
            candidate = session.get(AwardNomination, body.nomination_id)
            if candidate is None or candidate.category != body.category or candidate.status != "finalist":
                raise HTTPException(422, "Выбери утверждённого финалиста")
            if body.category in EVIDENCE_CATEGORIES:
                if len(body.justification.strip()) < 10:
                    raise HTTPException(422, "Укажи подтверждённые достижения победителя (не менее 10 символов)")
            else:
                counts = _ballot_counts(session)
                finalists = session.scalars(select(AwardNomination).where(
                    AwardNomination.category == body.category,
                    AwardNomination.status == "finalist"
                )).all()
                leaders = _leaders(finalists, counts)
                if len(leaders) < 2 or candidate.id not in leaders:
                    raise HTTPException(409, "В этой номинации нет ничьей. Победителя определяют голоса")
            winner = session.get(AwardWinner, body.category)
            if winner is None:
                winner = AwardWinner(category=body.category, nomination_id=candidate.id,
                                     selected_by=int(tg["id"]), selected_at=core.now_utc(),
                                     justification=body.justification.strip())
                session.add(winner)
            else:
                winner.nomination_id = candidate.id
                winner.selected_by = int(tg["id"])
                winner.selected_at = core.now_utc()
                winner.justification = body.justification.strip()
            return {"ok": True, "category": body.category, "nomination_id": candidate.id}


def register_nyan_awards_2026(app) -> None:
    global _REGISTERED
    if _REGISTERED:
        return
    AwardNomination.__table__.create(bind=core.engine, checkfirst=True)
    AwardVote.__table__.create(bind=core.engine, checkfirst=True)
    AwardWinner.__table__.create(bind=core.engine, checkfirst=True)
    app.include_router(router)
    _REGISTERED = True
