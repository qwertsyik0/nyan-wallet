"""Authenticated, standalone Telegram Mini App Mafia game.

No wallet balances or other game tables are written by this module. All role
assignment and phase mutations run under a Postgres advisory transaction lock.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
from collections import Counter
from datetime import datetime, timedelta
from urllib.parse import parse_qs, urlsplit

from fastapi import APIRouter, Header, HTTPException, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy import (
    BigInteger, Boolean, DateTime, ForeignKey, ForeignKeyConstraint,
    Integer, String, Text, UniqueConstraint, func, or_, select, text,
)
from sqlalchemy.orm import Mapped, mapped_column

from . import backend_app as core
from .nyan_mafia_rules import (
    NIGHT_ACTION, ROLE_HINT, ROLE_TITLE, TEAM, shuffle_deck, winner_for_roles,
)
from .telegram_relay import TelegramRelayMessage, relay_enabled


router = APIRouter()
_REGISTERED = False
_LOCK = 2026110307
_SECONDS = {"night": 100, "day": 170, "vote": 65}
_ACTIVE = ("registration", "night", "day", "vote")


class MafiaRound(core.Base):
    __tablename__ = "nyan_mafia_rounds"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    phase: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    day: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    winner: Mapped[str | None] = mapped_column(String(20), nullable=True)
    last_event: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    phase_started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    phase_ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class MafiaPlayer(core.Base):
    __tablename__ = "nyan_mafia_players"
    round_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("nyan_mafia_rounds.id", ondelete="CASCADE"), primary_key=True,
    )
    telegram_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.telegram_id", ondelete="CASCADE"), primary_key=True,
    )
    role: Mapped[str | None] = mapped_column(String(20), nullable=True)
    alive: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    immortal_used: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    night_result: Mapped[str | None] = mapped_column(Text, nullable=True)
    photo_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class MafiaChoice(core.Base):
    __tablename__ = "nyan_mafia_choices"
    __table_args__ = (
        ForeignKeyConstraint(
            ["round_id", "actor_id"],
            ["nyan_mafia_players.round_id", "nyan_mafia_players.telegram_id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint("round_id", "day", "phase", "actor_id", name="uq_nyan_mafia_choice"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    round_id: Mapped[int] = mapped_column(Integer, nullable=False)
    actor_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    day: Mapped[int] = mapped_column(Integer, nullable=False)
    phase: Mapped[str] = mapped_column(String(12), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    target_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    second_target_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class MafiaMessage(core.Base):
    __tablename__ = "nyan_mafia_messages"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    round_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("nyan_mafia_rounds.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    telegram_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    channel: Mapped[str] = mapped_column(String(12), nullable=False)
    body: Mapped[str] = mapped_column(String(600), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ChoiceBody(BaseModel):
    target_id: int
    second_target_id: int | None = None


class ChatBody(BaseModel):
    channel: str
    text: str = Field(min_length=1, max_length=500)


def _identity(init_data: str | None) -> dict:
    return core.verify_init_data(init_data or "")


def _owner(init_data: str | None) -> dict:
    user = _identity(init_data)
    core.require_owner(user)
    return user


def _group_id() -> int:
    """Never inherit the NYAN SPY group by default."""
    raw = os.getenv("NYAN_MAFIA_GROUP_ID", "").strip()
    if not raw:
        raise HTTPException(503, "Сначала укажи NYAN_MAFIA_GROUP_ID для группы мафии")
    try:
        chat_id = int(raw)
    except ValueError as error:
        raise HTTPException(503, "NYAN_MAFIA_GROUP_ID должен быть числом") from error
    if not str(chat_id).startswith("-100"):
        raise HTTPException(503, "Укажи полный ID супергруппы формата -100...")
    return chat_id


def _invite_url() -> str:
    """Require a confirmed real Telegram Mini App link, never a demo URL."""
    url = os.getenv("NYAN_MAFIA_INVITE_URL", "").strip()
    parsed = urlsplit(url)
    if (parsed.scheme != "https" or parsed.hostname not in ("t.me", "telegram.me")
            or not parsed.path.strip("/")
            or not (parse_qs(parsed.query).get("startapp") or len(parsed.path.strip("/").split("/")) >= 2)):
        raise HTTPException(
            503,
            "Укажи NYAN_MAFIA_INVITE_URL — рабочую ссылку Telegram Mini App для мафии",
        )
    return url


def _lock(session) -> None:
    session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": _LOCK})


def _latest(session) -> MafiaRound | None:
    return session.scalar(select(MafiaRound).order_by(MafiaRound.id.desc()).limit(1))


def _players(session, round_id: int) -> list[MafiaPlayer]:
    return list(session.scalars(
        select(MafiaPlayer).where(MafiaPlayer.round_id == round_id)
        .order_by(MafiaPlayer.joined_at, MafiaPlayer.telegram_id)
    ).all())


def _system(session, game: MafiaRound, message: str) -> None:
    game.last_event = message
    session.add(MafiaMessage(
        round_id=game.id, telegram_id=None, channel="system", body=message,
        created_at=core.now_utc(),
    ))


def _eliminated_announcement(session, player: MafiaPlayer) -> str:
    """Public elimination result: reveal only this player's role, never living roles."""
    user = session.get(core.User, player.telegram_id)
    label = ("@" + user.username) if user and user.username else (
        user.first_name if user else f"ID {player.telegram_id}"
    )
    return f"{label} — {ROLE_TITLE.get(player.role, 'роль неизвестна')}"


def _end_if_won(session, game: MafiaRound, people: list[MafiaPlayer]) -> bool:
    winner = winner_for_roles([p.role for p in people if p.alive and p.role])
    if winner is None:
        return False
    game.winner = winner
    game.phase = "finished"
    game.phase_ends_at = None
    title = {"civilians": "мирные", "mafia": "мафия", "maniac": "маньяк", "draw": "никто"}[winner]
    _system(session, game, f"игра окончена. победили {title}!")
    return True


def _set_phase(session, game: MafiaRound, phase: str, *, day: int | None = None) -> None:
    game.phase = phase
    if day is not None:
        game.day = day
    game.phase_started_at = core.now_utc()
    game.phase_ends_at = game.phase_started_at + timedelta(seconds=_SECONDS[phase])
    if phase == "night":
        # Previous night's private result must not reappear on later days when
        # a player skipped, was blocked, or could not use their ability.
        for player in _players(session, game.id):
            player.night_result = None
        _system(session, game, f"ночь {game.day}. город засыпает, роли делают выбор.")
    elif phase == "day":
        _system(session, game, f"день {game.day}. обсуждайте события в общем чате.")
    elif phase == "vote":
        _system(session, game, f"голосование {game.day}. выберите подозреваемого.")


def _resolve_night(session, game: MafiaRound) -> None:
    people = _players(session, game.id)
    by_id = {p.telegram_id: p for p in people}
    alive = {p.telegram_id for p in people if p.alive}
    actions = list(session.scalars(select(MafiaChoice).where(
        MafiaChoice.round_id == game.id,
        MafiaChoice.day == game.day,
        MafiaChoice.phase == "night",
    )).all())
    chosen = {a.actor_id: a for a in actions if a.actor_id in alive}
    blocked = {
        a.target_id for a in actions
        if a.actor_id in alive and by_id[a.actor_id].role == "lover"
        and a.target_id in alive
    }
    valid = [a for a in actions if a.actor_id in alive and a.actor_id not in blocked]
    heals = {a.target_id for a in valid if a.kind == "heal"}
    guards = {a.target_id: a.actor_id for a in valid if a.kind == "guard"}

    mafia_votes = [a.target_id for a in valid
                   if a.kind == "kill" and TEAM[by_id[a.actor_id].role] == "mafia"]
    victims: list[int] = []
    if mafia_votes:
        frequencies = Counter(mafia_votes)
        highest = max(frequencies.values())
        leaders = [p for p, n in frequencies.items() if n == highest]
        don_choice = next((a.target_id for a in valid if a.kind == "kill" and by_id[a.actor_id].role == "don"), None)
        victims.append(don_choice if don_choice in leaders else secrets.choice(leaders))
    victims.extend(a.target_id for a in valid if a.kind == "kill" and by_id[a.actor_id].role == "maniac")

    dead: list[int] = []
    for target_id in victims:
        target_id = guards.get(target_id, target_id)
        if target_id not in alive or target_id in heals:
            continue
        target = by_id[target_id]
        if target.role == "immortal" and not target.immortal_used:
            target.immortal_used = True
            target.night_result = "тебя атаковали, но бессмертие спасло тебя."
            continue
        if target_id not in dead:
            dead.append(target_id)

    for actor in valid:
        if actor.kind == "inspect":
            role = by_id[actor.target_id].role
            by_id[actor.actor_id].night_result = (
                "проверка: этот игрок состоит в мафии." if TEAM[role] == "mafia"
                else "проверка: этот игрок не состоит в мафии."
            )
        elif actor.kind == "compare" and actor.second_target_id:
            one = TEAM[by_id[actor.target_id].role]
            two = TEAM[by_id[actor.second_target_id].role]
            by_id[actor.actor_id].night_result = (
                "сравнение: игроки из одной команды." if one == two
                else "сравнение: игроки из разных команд."
            )
    for target_id in list(dead):
        p = by_id[target_id]
        if p.role == "kamikaze" and target_id in chosen and target_id not in blocked:
            revenge = chosen[target_id]
            if revenge.kind == "revenge" and revenge.target_id in alive and revenge.target_id != target_id:
                if revenge.target_id not in dead:
                    dead.append(revenge.target_id)

    for target_id in dead:
        by_id[target_id].alive = False
    if dead:
        announcements = "; ".join(_eliminated_announcement(session, by_id[uid]) for uid in dead)
        _system(session, game, "этой ночью выбыли: " + announcements + ".")
    else:
        _system(session, game, "утро. этой ночью никто не выбыл.")
    if not _end_if_won(session, game, people):
        _set_phase(session, game, "day")


def _resolve_vote(session, game: MafiaRound) -> None:
    people = _players(session, game.id)
    by_id = {p.telegram_id: p for p in people}
    alive = {p.telegram_id for p in people if p.alive}
    choices = list(session.scalars(select(MafiaChoice).where(
        MafiaChoice.round_id == game.id, MafiaChoice.day == game.day,
        MafiaChoice.phase == "vote",
    )).all())
    counts = Counter(a.target_id for a in choices if a.actor_id in alive and a.target_id in alive)
    target = None
    if counts:
        maximum = max(counts.values())
        top = [pid for pid, amount in counts.items() if amount == maximum]
        if len(top) == 1:
            target = top[0]

    defended = {a.target_id for a in session.scalars(select(MafiaChoice).where(
        MafiaChoice.round_id == game.id, MafiaChoice.day == game.day,
        MafiaChoice.phase == "night", MafiaChoice.kind == "defend",
    )).all() if by_id[a.actor_id].alive}
    if target is None:
        _system(session, game, "голоса разделились. никто не изгнан.")
    elif target in defended:
        _system(session, game, "адвокат защитил выбранного игрока. изгнание отменено.")
    else:
        by_id[target].alive = False
        eliminated = [target]
        # A prepared kamikaze takes their night-selected target when voted out.
        if by_id[target].role == "kamikaze":
            revenge = session.scalar(select(MafiaChoice).where(
                MafiaChoice.round_id == game.id, MafiaChoice.day == game.day,
                MafiaChoice.phase == "night", MafiaChoice.actor_id == target,
                MafiaChoice.kind == "revenge",
            ))
            if revenge and revenge.target_id in alive and revenge.target_id != target:
                by_id[revenge.target_id].alive = False
                eliminated.append(revenge.target_id)
        names = "; ".join(_eliminated_announcement(session, by_id[uid]) for uid in eliminated)
        _system(session, game, "после голосования выбыли: " + names + ".")
    if not _end_if_won(session, game, people):
        _set_phase(session, game, "night", day=game.day + 1)


def _advance(session, game: MafiaRound) -> None:
    if game.phase == "night":
        _resolve_night(session, game)
    elif game.phase == "day":
        _set_phase(session, game, "vote")
    elif game.phase == "vote":
        _resolve_vote(session, game)


def _advance_due(session, game: MafiaRound | None) -> None:
    if game and game.phase in _SECONDS and game.phase_ends_at:
        if core.now_utc() >= game.phase_ends_at:
            _advance(session, game)


def _photo(value: object) -> str | None:
    if not isinstance(value, str) or len(value) > 2048:
        return None
    parsed = urlsplit(value)
    return value if parsed.scheme == "https" and parsed.hostname else None


def _state(session, game: MafiaRound | None, tg: dict) -> dict:
    ident = int(tg["id"])
    result = {"ok": True, "is_owner": core.is_owner(ident), "phase": "idle", "players": []}
    if game is None:
        return result
    people = _players(session, game.id)
    me = next((p for p in people if p.telegram_id == ident), None)
    profiles = {u.telegram_id: u for u in session.scalars(
        select(core.User).where(core.User.telegram_id.in_([p.telegram_id for p in people]))
    ).all()}
    result.update({
        "phase": game.phase, "round_id": game.id, "day": game.day,
        "ends_at": game.phase_ends_at.isoformat() if game.phase_ends_at else None,
        "joined": me is not None, "alive": bool(me and me.alive),
        "winner": game.winner, "last_event": game.last_event,
        "min_players": 4, "max_players": 20,
        "players": [
            {"id": p.telegram_id,
             "name": profiles[p.telegram_id].first_name,
             "username": profiles[p.telegram_id].username,
             "photo_url": p.photo_url,
             "alive": p.alive}
            for p in people
        ],
    })
    if me and me.role:
        result["my_role"] = me.role
        result["my_role_title"] = ROLE_TITLE[me.role]
        result["my_role_hint"] = ROLE_HINT[me.role]
        result["night_result"] = me.night_result
        if TEAM[me.role] == "mafia":
            result["mafia_team"] = [p.telegram_id for p in people if p.role in ("mafia", "don")]
        if game.phase in ("night", "vote"):
            action = session.scalar(select(MafiaChoice).where(
                MafiaChoice.round_id == game.id,
                MafiaChoice.day == game.day,
                MafiaChoice.phase == game.phase,
                MafiaChoice.actor_id == ident,
            ))
            if action:
                result["my_choice"] = {"target_id": action.target_id, "second_target_id": action.second_target_id}
    # Publicly reveal only players who have left the game. Living roles stay secret.
    result["revealed_roles"] = {
        str(p.telegram_id): p.role for p in people
        if p.role and (not p.alive or game.phase == "finished")
    }
    # Phase transitions replace game.last_event; preserve the last elimination
    # from the current phase boundary, without introducing a DB migration.
    latest_elimination = session.scalar(select(MafiaMessage).where(
        MafiaMessage.round_id == game.id,
        MafiaMessage.channel == "system",
        or_(
            MafiaMessage.body.like("этой ночью выбыли:%"),
            MafiaMessage.body.like("после голосования выбыли:%"),
        ),
        MafiaMessage.created_at >= game.phase_started_at - timedelta(seconds=10),
    ).order_by(MafiaMessage.id.desc()).limit(1))
    result["last_elimination"] = latest_elimination.body if latest_elimination else None
    return result


@router.get("/api/nyan-mafia/status")
def mafia_status(response: Response, x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data")):
    response.headers["Cache-Control"] = "private, no-store"
    tg = _identity(x_telegram_init_data)
    with core.SessionLocal.begin() as session:
        _lock(session)
        game = _latest(session)
        _advance_due(session, game)
        return _state(session, game, tg)


@router.post("/api/nyan-mafia/join")
def mafia_join(x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data")):
    tg = _identity(x_telegram_init_data)
    core.get_or_create_user(tg)
    with core.SessionLocal.begin() as session:
        _lock(session)
        game = _latest(session)
        if game is None or game.phase != "registration":
            raise HTTPException(409, "регистрация закрыта")
        if session.get(MafiaPlayer, (game.id, int(tg["id"]))) is None:
            if len(_players(session, game.id)) >= 20:
                raise HTTPException(409, "все 20 мест заняты")
            session.add(MafiaPlayer(
                round_id=game.id, telegram_id=int(tg["id"]), joined_at=core.now_utc(),
                photo_url=_photo(tg.get("photo_url")), role=None, alive=True,
            ))
    return {"ok": True}


@router.post("/api/nyan-mafia/leave")
def mafia_leave(x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data")):
    tg = _identity(x_telegram_init_data)
    with core.SessionLocal.begin() as session:
        _lock(session)
        game = _latest(session)
        if not game or game.phase != "registration":
            raise HTTPException(409, "после старта покинуть игру нельзя")
        member = session.get(MafiaPlayer, (game.id, int(tg["id"])))
        if member:
            session.delete(member)
    return {"ok": True}


def _open_registration() -> dict:
    if not relay_enabled():
        raise HTTPException(503, "Telegram-рассылка сейчас недоступна")
    # Validate both destinations BEFORE writing to the database.
    group_id = _group_id()
    invite = _invite_url()
    with core.SessionLocal.begin() as session:
        _lock(session)
        current = _latest(session)
        if current and current.phase in _ACTIVE:
            raise HTTPException(409, "сначала заверши текущую игру")
        now = core.now_utc()
        game = MafiaRound(phase="registration", day=0, created_at=now, phase_started_at=now)
        session.add(game)
        session.flush()
        announcement = {
            "text": "🐾 NYAN MAFIA\n\nрегистрация открыта! заходи в игру, получай секретную роль и участвуй в расследовании. игроки общаются и голосуют прямо в mini app.",
            "buttons": [{"text": "🐾 войти в мафию", "url": invite}],
        }
        session.add(TelegramRelayMessage(
            source_key=f"nyan-mafia-join:{game.id}", chat_id=group_id,
            body="NYAN_TG_RICH_V1:" + json.dumps(announcement, ensure_ascii=False),
            state="pending", attempts=0, created_at=now,
        ))
        game_id = game.id
    return {"ok": True, "round_id": game_id, "invitation_queued": True}


@router.post("/api/owner/nyan-mafia/open")
def mafia_open(x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data")):
    _owner(x_telegram_init_data)
    return _open_registration()


@router.post("/api/internal/nyan-mafia/open")
def mafia_open_from_bot(
    x_nyan_mafia_command: str | None = Header(default=None, alias="X-Nyan-Mafia-Command"),
):
    """Called only by the owner-gated /mafia bot handler."""
    token = (core.BOT_TOKEN or "").encode("utf-8")
    expected = hmac.new(token, b"nyan-mafia:open:v1", hashlib.sha256).hexdigest()
    if not x_nyan_mafia_command or not hmac.compare_digest(x_nyan_mafia_command, expected):
        raise HTTPException(401, "Unauthorized")
    return _open_registration()


@router.post("/api/owner/nyan-mafia/start")
def mafia_start(x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data")):
    _owner(x_telegram_init_data)
    with core.SessionLocal.begin() as session:
        _lock(session)
        game = _latest(session)
        if not game or game.phase != "registration":
            raise HTTPException(409, "нет открытой регистрации")
        people = _players(session, game.id)
        try:
            roles = shuffle_deck(len(people))
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        for person, role in zip(people, roles):
            person.role = role
        _set_phase(session, game, "night", day=1)
        return {"ok": True, "round_id": game.id, "players": len(people)}


@router.post("/api/owner/nyan-mafia/advance")
def mafia_advance(x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data")):
    _owner(x_telegram_init_data)
    with core.SessionLocal.begin() as session:
        _lock(session)
        game = _latest(session)
        if game is None or game.phase not in _SECONDS:
            raise HTTPException(409, "нет активной фазы")
        _advance(session, game)
        return {"ok": True, "phase": game.phase}


@router.post("/api/owner/nyan-mafia/finish")
def mafia_finish(x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data")):
    _owner(x_telegram_init_data)
    with core.SessionLocal.begin() as session:
        _lock(session)
        game = _latest(session)
        if not game or game.phase not in _ACTIVE:
            raise HTTPException(409, "нет активной игры")
        game.phase = "finished"
        game.phase_ends_at = None
        _system(session, game, "ведущий завершил игру.")
    return {"ok": True}


@router.post("/api/nyan-mafia/action")
def mafia_action(body: ChoiceBody, x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data")):
    tg = _identity(x_telegram_init_data)
    ident = int(tg["id"])
    with core.SessionLocal.begin() as session:
        _lock(session)
        game = _latest(session)
        _advance_due(session, game)
        if not game or game.phase not in ("night", "vote"):
            raise HTTPException(409, "сейчас нельзя выбирать игроков")
        players = _players(session, game.id)
        people = {p.telegram_id: p for p in players}
        me = people.get(ident)
        if not me or not me.alive or not me.role:
            raise HTTPException(403, "только живые участники могут действовать")
        if body.target_id not in people or not people[body.target_id].alive:
            raise HTTPException(422, "цель недоступна")
        if game.phase == "night":
            kind = NIGHT_ACTION.get(me.role)
            if kind is None:
                raise HTTPException(403, "для твоей роли нет ночного действия")
            if ident == body.target_id and kind not in ("heal", "defend"):
                raise HTTPException(422, "нельзя выбрать себя")
            if kind == "kill" and TEAM[me.role] == "mafia" and TEAM[people[body.target_id].role] == "mafia":
                raise HTTPException(422, "нельзя атаковать сообщника")
            if kind == "compare":
                if not body.second_target_id or body.second_target_id == body.target_id:
                    raise HTTPException(422, "журналист выбирает двух разных игроков")
                if body.second_target_id not in people or not people[body.second_target_id].alive:
                    raise HTTPException(422, "вторая цель недоступна")
            elif body.second_target_id is not None:
                raise HTTPException(422, "вторая цель не нужна")
        else:
            kind = "vote"
            if ident == body.target_id or body.second_target_id is not None:
                raise HTTPException(422, "выбери другого игрока")

        previous = session.scalar(select(MafiaChoice).where(
            MafiaChoice.round_id == game.id,
            MafiaChoice.day == game.day,
            MafiaChoice.phase == game.phase,
            MafiaChoice.actor_id == ident,
        ))
        if previous:
            previous.target_id = body.target_id
            previous.second_target_id = body.second_target_id
            previous.created_at = core.now_utc()
        else:
            session.add(MafiaChoice(
                round_id=game.id, actor_id=ident, day=game.day, phase=game.phase,
                kind=kind, target_id=body.target_id,
                second_target_id=body.second_target_id, created_at=core.now_utc(),
            ))
        return {"ok": True, "saved": True}


@router.get("/api/nyan-mafia/messages")
def mafia_messages(
    channel: str = Query(default="public"), after: int = Query(default=0, ge=0),
    x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data"),
):
    tg = _identity(x_telegram_init_data)
    with core.SessionLocal() as session:
        game = _latest(session)
        if not game or game.phase == "registration":
            return {"ok": True, "messages": []}
        me = session.get(MafiaPlayer, (game.id, int(tg["id"])))
        if channel == "mafia":
            if not me or me.role not in ("mafia", "don") or not me.alive:
                raise HTTPException(403, "это приватный чат мафии")
            allowed = ["mafia"]
        elif channel == "public":
            allowed = ["public", "system"]
        else:
            raise HTTPException(422, "неизвестный чат")
        messages = list(session.scalars(select(MafiaMessage).where(
            MafiaMessage.round_id == game.id,
            MafiaMessage.channel.in_(allowed), MafiaMessage.id > after,
        ).order_by(MafiaMessage.id).limit(120)).all())
        ids = {m.telegram_id for m in messages if m.telegram_id is not None}
        profiles = {u.telegram_id: u for u in session.scalars(
            select(core.User).where(core.User.telegram_id.in_(ids))
        ).all()}
        return {"ok": True, "messages": [
            {"id": msg.id, "sender_id": msg.telegram_id,
             "name": profiles[msg.telegram_id].first_name if msg.telegram_id in profiles else "ведущий",
             "username": profiles[msg.telegram_id].username if msg.telegram_id in profiles else None,
             "text": msg.body, "system": msg.telegram_id is None,
             "created_at": msg.created_at.isoformat()}
            for msg in messages
        ]}


@router.post("/api/nyan-mafia/messages")
def mafia_post_message(
    body: ChatBody,
    x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data"),
):
    tg = _identity(x_telegram_init_data)
    ident = int(tg["id"])
    message = body.text.strip()
    if not message or len(message) > 500:
        raise HTTPException(422, "сообщение должно содержать от 1 до 500 символов")
    with core.SessionLocal.begin() as session:
        _lock(session)
        game = _latest(session)
        _advance_due(session, game)
        if not game:
            raise HTTPException(409, "игра не запущена")
        me = session.get(MafiaPlayer, (game.id, ident))
        if not me or not me.alive:
            raise HTTPException(403, "отправлять сообщения могут только живые участники")
        if body.channel == "public" and game.phase not in ("day", "vote"):
            raise HTTPException(409, "общий чат доступен днём")
        if body.channel == "mafia" and (game.phase != "night" or me.role not in ("mafia", "don")):
            raise HTTPException(403, "чат мафии доступен только мафии ночью")
        if body.channel not in ("public", "mafia"):
            raise HTTPException(422, "неизвестный чат")
        last = session.scalar(select(MafiaMessage).where(
            MafiaMessage.round_id == game.id, MafiaMessage.telegram_id == ident,
        ).order_by(MafiaMessage.id.desc()).limit(1))
        now = core.now_utc()
        if last and (now - last.created_at).total_seconds() < 1.2:
            raise HTTPException(429, "не отправляй сообщения слишком часто")
        saved = MafiaMessage(
            round_id=game.id, telegram_id=ident, channel=body.channel,
            body=message, created_at=now,
        )
        session.add(saved)
        session.flush()
        saved_response = {
            "id": saved.id,
            "sender_id": ident,
            "name": tg.get("first_name") or "Игрок",
            "username": tg.get("username"),
            "text": message,
            "system": False,
            "created_at": now.isoformat(),
        }
    return {"ok": True, "message": saved_response}


def register_nyan_mafia(app) -> None:
    global _REGISTERED
    if _REGISTERED:
        return
    for model in (MafiaRound, MafiaPlayer, MafiaChoice, MafiaMessage):
        model.__table__.create(bind=core.engine, checkfirst=True)
    app.include_router(router)
    _REGISTERED = True
