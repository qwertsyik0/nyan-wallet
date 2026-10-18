"""Immutable Nyan Elections ballots, one signed Telegram vote per season.

The current season stays in campaign until the owner explicitly opens voting.
Opening snapshots eligible approved parties; closing locks voting and exposes
aggregate results. No payment, reward, bot or wallet-balance side effects.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import (
    BigInteger, DateTime, ForeignKey, ForeignKeyConstraint, Integer,
    String, Text, func, select,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, mapped_column

from . import backend_app as core
from . import elections as election

router = APIRouter(prefix="/api/elections", tags=["elections-voting"])
_REGISTERED = False


class ElectionBallotControl(core.Base):
    __tablename__ = "election_ballot_controls"

    season_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("election_seasons.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    opened_by: Mapped[int] = mapped_column(BigInteger, nullable=False)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_by: Mapped[int | None] = mapped_column(BigInteger)


class ElectionBallotParty(core.Base):
    __tablename__ = "election_ballot_parties"

    season_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("election_seasons.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    party_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("election_parties.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    short_name: Mapped[str] = mapped_column(String(15), nullable=False)
    program: Mapped[str] = mapped_column(Text, nullable=False)
    chair_label: Mapped[str] = mapped_column(String(128), nullable=False)
    emblem_url: Mapped[str | None] = mapped_column(String(500))


class ElectionVote(core.Base):
    __tablename__ = "election_votes"
    __table_args__ = (
        ForeignKeyConstraint(
            ["season_id", "party_id"],
            ["election_ballot_parties.season_id", "election_ballot_parties.party_id"],
            ondelete="RESTRICT",
        ),
    )

    season_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("election_seasons.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    telegram_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.telegram_id", ondelete="RESTRICT"),
        primary_key=True,
    )
    party_id: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CastVote(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    party_id: int = Field(gt=0)


def _eligible(party: election.ElectionParty) -> bool:
    # Previously withdrawn from the public list: never silently re-add to ballot.
    name = " ".join(party.name.split()).casefold()
    short = " ".join(party.short_name.split()).casefold()
    return party.status == "approved" and not (
        short == "сап"
        or name == "союз айристократов парижа"
        or name == "антонианство шаматовский дом"
    )


def _summary(program: str) -> str:
    # Faithful excerpt of the party's actual published program, not AI paraphrase.
    compact = " ".join(program.split())
    if len(compact) <= 260:
        return compact
    cut = compact[:260].rfind(" ")
    return compact[:cut if cut >= 160 else 260].rstrip() + "…"


def _party_snapshot(session, party: election.ElectionParty) -> ElectionBallotParty:
    chair = session.get(core.User, party.chair_id)
    label = (
        "@" + chair.username if chair and chair.username
        else chair.first_name if chair else "пользователь"
    )
    is_uploaded = session.get(election.ElectionPartyEmblem, party.id) is not None
    return ElectionBallotParty(
        season_id=party.season_id,
        party_id=party.id,
        name=party.name,
        short_name=party.short_name,
        program=party.program,
        chair_label=label,
        emblem_url=(
            f"/api/elections/parties/{party.id}/emblem"
            if is_uploaded else party.emblem_url
        ),
    )


def _serialize_party(party: ElectionBallotParty) -> dict:
    return {
        "id": party.party_id,
        "name": party.name,
        "short_name": party.short_name,
        "chair_label": party.chair_label,
        "summary": _summary(party.program),
        "program": party.program,
        "emblem_url": party.emblem_url,
    }


def _ballot(session, season_id: int) -> list[ElectionBallotParty]:
    return list(session.scalars(
        select(ElectionBallotParty)
        .where(ElectionBallotParty.season_id == season_id)
        .order_by(ElectionBallotParty.party_id)
    ).all())


def _vote_count(session, season_id: int) -> int:
    return int(session.scalar(
        select(func.count()).select_from(ElectionVote)
        .where(ElectionVote.season_id == season_id)
    ) or 0)


@router.get("/voting/status")
async def voting_status(
    x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data"),
):
    uid = election.auth(x_telegram_init_data)
    owner = core.is_owner(uid)
    with core.SessionLocal() as session:
        election.require_account(session, uid)
        season = election.latest_season(session)
        if season is None:
            return {"ok": True, "phase": None, "is_owner": owner,
                    "ballot": [], "my_vote_party_id": None}
        result = {
            "ok": True, "phase": season.phase, "season_id": season.id,
            "season_title": season.title, "is_owner": owner,
            "ballot": [], "my_vote_party_id": None,
        }
        if season.phase == "campaign" and owner:
            parties = session.scalars(
                select(election.ElectionParty)
                .where(election.ElectionParty.season_id == season.id)
                .order_by(election.ElectionParty.id)
            ).all()
            result["ballot"] = [
                _serialize_party(_party_snapshot(session, p))
                for p in parties if _eligible(p)
            ]
            result["preview"] = True
        elif season.phase in ("voting", "results", "closed"):
            ballot = _ballot(session, season.id)
            result["ballot"] = [_serialize_party(p) for p in ballot]
            mine = session.get(ElectionVote, (season.id, uid))
            result["my_vote_party_id"] = mine.party_id if mine else None
            if owner or season.phase in ("results", "closed"):
                total = _vote_count(session, season.id)
                result["total_votes"] = total
            if season.phase in ("results", "closed"):
                counts = dict(session.execute(
                    select(ElectionVote.party_id, func.count())
                    .where(ElectionVote.season_id == season.id)
                    .group_by(ElectionVote.party_id)
                ).all())
                result["results"] = [
                    {"party_id": p.party_id, "votes": int(counts.get(p.party_id, 0))}
                    for p in ballot
                ]
            control = session.get(ElectionBallotControl, season.id)
            if control:
                result["opened_at"] = control.opened_at.isoformat()
                result["closed_at"] = control.closed_at.isoformat() if control.closed_at else None
        return result


@router.post("/owner/voting/open")
async def owner_open_voting(
    x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data"),
):
    uid = election.owner_auth(x_telegram_init_data)
    with core.SessionLocal() as session:
        with session.begin():
            season = election.latest_season(session, lock=True)
            if season is None or season.phase != "campaign":
                raise HTTPException(status_code=409, detail="Голосование можно открыть только после агитации")
            if session.get(ElectionBallotControl, season.id):
                raise HTTPException(status_code=409, detail="Голосование этого сезона уже проводилось")
            parties = list(session.scalars(
                select(election.ElectionParty)
                .where(election.ElectionParty.season_id == season.id)
                .order_by(election.ElectionParty.id)
            ).all())
            eligible = [p for p in parties if _eligible(p)]
            if len(eligible) < 2:
                raise HTTPException(status_code=409, detail="Для голосования нужно хотя бы две допущенные партии")
            for party in eligible:
                session.add(_party_snapshot(session, party))
            now = election.timestamp()
            session.add(ElectionBallotControl(
                season_id=season.id, opened_at=now, opened_by=uid,
            ))
            season.phase = "voting"
            season.updated_at = now
            count = len(eligible)
    return {"ok": True, "phase": "voting", "parties": count}


@router.post("/voting/cast")
async def cast_vote(
    payload: CastVote,
    x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data"),
):
    uid = election.auth(x_telegram_init_data)
    try:
        with core.SessionLocal() as session:
            with session.begin():
                election.require_account(session, uid)
                # PostgreSQL season-row lock serializes votes with close(), so
                # a vote cannot be inserted after closing the urn.
                season = election.latest_season(session, lock=True)
                if season is None or season.phase != "voting":
                    raise HTTPException(status_code=409, detail="Голосование сейчас закрыто")
                previous = session.get(ElectionVote, (season.id, uid))
                if previous:
                    if previous.party_id == payload.party_id:
                        return {"ok": True, "accepted": True, "already_voted": True,
                                "party_id": previous.party_id}
                    raise HTTPException(status_code=409, detail="Ваш голос уже учтён. Изменить его нельзя")
                eligible = session.get(ElectionBallotParty, (season.id, payload.party_id))
                if eligible is None:
                    raise HTTPException(status_code=422, detail="Этой партии нет в бюллетене")
                session.add(ElectionVote(
                    season_id=season.id, telegram_id=uid, party_id=payload.party_id,
                    created_at=election.timestamp(),
                ))
        return {"ok": True, "accepted": True, "already_voted": False,
                "party_id": payload.party_id}
    except IntegrityError as exc:
        # Unique composite primary key also guards concurrent requests.
        raise HTTPException(status_code=409, detail="Голос уже зарегистрирован") from exc


@router.post("/owner/voting/close")
async def owner_close_voting(
    x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data"),
):
    uid = election.owner_auth(x_telegram_init_data)
    with core.SessionLocal() as session:
        with session.begin():
            season = election.latest_season(session, lock=True)
            if season is None or season.phase != "voting":
                raise HTTPException(status_code=409, detail="Нет открытого голосования")
            control = session.get(ElectionBallotControl, season.id)
            if control is None or control.closed_at is not None:
                raise HTTPException(status_code=409, detail="Не найдено активное голосование")
            now = election.timestamp()
            control.closed_at = now
            control.closed_by = uid
            season.phase = "results"
            season.updated_at = now
            total = _vote_count(session, season.id)
    return {"ok": True, "phase": "results", "total_votes": total}


def register_elections_voting(app) -> None:
    global _REGISTERED
    if _REGISTERED:
        return
    ElectionBallotControl.__table__.create(bind=core.engine, checkfirst=True)
    ElectionBallotParty.__table__.create(bind=core.engine, checkfirst=True)
    ElectionVote.__table__.create(bind=core.engine, checkfirst=True)
    app.include_router(router)
    _REGISTERED = True
