"""One-day Nyan Halloween mystery. All puzzles and rewards are verified server-side.

2026-10-29 17:00 through 2026-10-31 (Moscow). Separate event currency (pumpkins) cannot be converted or
transferred. Wallet grants are atomic and unique per user/room.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import random
import re
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Mapped, mapped_column

from . import backend_app as core
from .user_bans import BlockedUser


router = APIRouter()
_REGISTERED = False
UTC = timezone.utc
START_AT = datetime(2026, 10, 29, 14, 0, tzinfo=UTC)  # Oct 29, 17:00 MSK
SECRET_AT = datetime(2026, 10, 31, 20, 0, tzinfo=UTC)  # Oct 31, 23:00 MSK
END_AT = datetime(2026, 10, 31, 21, 0, tzinfo=UTC)  # Nov 1, 00:00 MSK
MAX_BALANCE = 2_147_483_647
REWARDS = {1: 40, 2: 50, 3: 60, 4: 100, 5: 150, 6: 100}
PUMPKINS = {1: 10, 2: 12, 3: 14, 4: 16, 5: 18, 6: 20}
ITEMS = {
    "loupe": ("Лупа", 5),
    "candle": ("Свеча", 10),
    "key": ("Ржавый ключ", 15),
    "eye": ("Глаз Няника", 20),
}
ROOMS = (
    ("Заброшенная лавка", "Первый чек сохранился. Цифры в нём не случайны."),
    ("Комната наблюдения", "Четыре монитора ещё передают сигнал."),
    ("Дневник Няника", "Буквы будто сдвинулись со своих мест."),
    ("Три запертые двери", "Только одна табличка говорит правду."),
    ("Последний разговор", "Собери всё, что осталось после пройденных комнат."),
    ("Комната без номера", "Няник оставил последнюю запись. Она откроется ночью."),
)
KEY_RE = re.compile(r"[A-Za-z0-9_-]{12,64}\Z")
ALPHABET = "АБВГДЕЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯ"


class HalloweenPlayer(core.Base):
    __tablename__ = "halloween_2026_players"
    telegram_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.telegram_id", ondelete="CASCADE"), primary_key=True)
    pumpkins: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    secret_unlocked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class HalloweenRoom(core.Base):
    __tablename__ = "halloween_2026_rooms"
    telegram_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.telegram_id", ondelete="CASCADE"), primary_key=True)
    room: Mapped[int] = mapped_column(Integer, primary_key=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    solved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reward: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    transaction_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("transactions.id"), nullable=True, unique=True)
    last_request_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_correct: Mapped[bool | None] = mapped_column(Boolean, nullable=True)


class HalloweenInventory(core.Base):
    __tablename__ = "halloween_2026_inventory"
    telegram_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.telegram_id", ondelete="CASCADE"), primary_key=True)
    item: Mapped[str] = mapped_column(String(20), primary_key=True)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class HalloweenEffect(core.Base):
    __tablename__ = "halloween_2026_effects"
    telegram_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.telegram_id", ondelete="CASCADE"), primary_key=True)
    room: Mapped[int] = mapped_column(Integer, primary_key=True)
    item: Mapped[str] = mapped_column(String(20), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class HalloweenPurchase(core.Base):
    __tablename__ = "halloween_2026_purchases"
    __table_args__ = (UniqueConstraint("telegram_id", "request_key", name="uq_halloween_purchase_request"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.telegram_id", ondelete="CASCADE"), nullable=False)
    request_key: Mapped[str] = mapped_column(String(64), nullable=False)
    item: Mapped[str] = mapped_column(String(20), nullable=False)
    cost: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class HalloweenBadge(core.Base):
    __tablename__ = "halloween_2026_badges"
    telegram_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.telegram_id", ondelete="CASCADE"), primary_key=True)
    awarded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AnswerInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    room: int = Field(ge=1, le=6)
    answer: str = Field(min_length=1, max_length=60)
    request_key: str = Field(min_length=12, max_length=64)


class BuyInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    item: str
    request_key: str = Field(min_length=12, max_length=64)


class UseInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    room: int = Field(ge=1, le=6)
    item: str


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _seed(uid: int, room: int) -> int:
    # This key is only on the server. The HTML/JS never contains winning answers.
    secret = os.getenv("BOT_TOKEN", "")
    if not secret:
        raise RuntimeError("BOT_TOKEN не задан")
    digest = hmac.new(secret.encode(), f"nyan-halloween-2026:{uid}:{room}".encode(), hashlib.sha256).digest()
    return int.from_bytes(digest[:8], "big")


def _fragment(uid: int, room: int) -> str:
    return str(1 + _seed(uid, room) % 9)


def _puzzle(uid: int, room: int) -> tuple[dict, str]:
    rng = random.Random(_seed(uid, room))
    if room == 1:
        candle, mask, key = rng.randint(5, 11), rng.randint(3, 9), rng.randint(12, 29)
        return ({"kind": "receipt", "lines": [f"2 свечи = {2*candle}", f"свеча + маска = {candle+mask}", f"маска + ключ = {mask+key}"],
                 "question": "Сколько стоит ключ? Напиши только число."}, str(key))
    if room == 2:
        selected = sorted(rng.sample(range(16), 4))
        digits = [rng.randint(0, 9) for _ in range(16)]
        tiles = [{"digit": str(d), "marked": i in selected} for i, d in enumerate(digits)]
        return ({"kind": "monitors", "tiles": tiles,
                 "question": "Читай цифры только с мониторов с круглой меткой, слева направо, сверху вниз. Введи четырёхзначный код."},
                "".join(str(digits[i]) for i in selected))
    if room == 3:
        word = rng.choice(("СВЕЧА", "ТЫКВА", "ДВЕРЬ", "КОШКА", "ПРИЗРАК", "ФОНАРЬ"))
        shift = rng.randint(2, 6)
        cipher = "".join(ALPHABET[(ALPHABET.index(ch) + shift) % len(ALPHABET)] for ch in word)
        return ({"kind": "cipher", "cipher": cipher, "shift": shift,
                 "question": "Каждую букву сдвинули вправо по русскому алфавиту без Ё. Верни её назад и напиши слово."}, word)
    if room == 4:
        a, b, _ = rng.sample((1, 2, 3), 3)
        return ({"kind": "doors", "lines": [f"Табличка I: ключ за дверью {a}.",
                  f"Табличка II: ключ НЕ за дверью {b}.", f"Табличка III: ключ НЕ за дверью {a}."],
                 "question": "Только одна табличка говорит правду. За какой дверью ключ: 1, 2 или 3?"}, str(b))
    if room == 5:
        order = rng.sample((1, 2, 3, 4), 4)
        return ({"kind": "fragments", "order": order,
                 "question": "Вспомни цифры-фрагменты первых четырёх комнат. Собери их в указанном порядке."},
                "".join(_fragment(uid, i) for i in order))
    if room == 6:
        step = rng.randint(1, 4)
        parts = [_fragment(uid, i) for i in range(1, 6)]
        answer = "".join(str((int(ch) + step) % 10) for ch in reversed(parts))
        return ({"kind": "final", "step": step,
                 "question": "Возьми пять фрагментов, прочитай их в обратном порядке и увеличь каждую цифру на указанное число. После 9 снова идёт 0."}, answer)
    raise ValueError("Неизвестная комната")


def _hint(uid: int, room: int, item: str) -> str:
    puzzle, answer = _puzzle(uid, room)
    if item == "loupe":
        if room == 3:
            return f"Используй алфавит без Ё, отступая на {puzzle['shift']} позиций влево."
        return {
            1: "Начни с первой строки чека. Затем найди маску и вычти её цену из последней строки.",
            2: "Ровно четыре монитора отмечены маленькой точкой.",
            4: "Попробуй каждую из трёх дверей и посчитай, сколько табличек оказалось правдивыми.",
            5: "Цифры-фрагменты видны рядом с уже открытыми комнатами.",
            6: "Сначала поменяй порядок пяти цифр, только затем прибавляй число.",
        }[room]
    if item == "candle":
        return f"Первая часть ответа: {answer[:1]}. Всего символов: {len(answer)}."
    if item == "eye":
        return f"Почти весь ответ: {answer[:-1]}{'□'} (остался последний символ)." if len(answer) > 1 else f"Ответ: {answer}"
    raise ValueError("Неизвестный предмет")


def _require_live(now: datetime) -> None:
    if not START_AT <= now < END_AT:
        raise HTTPException(status_code=409, detail="Событие доступно с 29 октября, 17:00, до конца 31 октября по Москве")


def _identity(init_data: str | None) -> dict:
    return core.verify_init_data(init_data or "")


def _lock_user(session, tg_user: dict, now: datetime) -> core.User:
    values = dict(telegram_id=int(tg_user["id"]), username=tg_user.get("username"),
                  first_name=tg_user.get("first_name") or "Пользователь", last_name=tg_user.get("last_name"),
                  balance=0, created_at=now, last_seen_at=now)
    dialect = session.bind.dialect.name
    if dialect == "postgresql":
        stmt = pg_insert(core.User).values(**values)
    elif dialect == "sqlite":
        stmt = sqlite_insert(core.User).values(**values)
    else:
        raise RuntimeError("Для события требуется PostgreSQL")
    session.execute(stmt.on_conflict_do_nothing(index_elements=["telegram_id"]))
    user = session.scalar(select(core.User).where(core.User.telegram_id == values["telegram_id"]).with_for_update())
    if session.get(BlockedUser, user.telegram_id) is not None:
        raise HTTPException(status_code=403, detail="Участие недоступно для заблокированного аккаунта")
    core.apply_telegram_profile(user, tg_user, now)
    return user


def _player(session, uid: int, now: datetime) -> HalloweenPlayer:
    player = session.get(HalloweenPlayer, uid)
    if player is None:
        player = HalloweenPlayer(telegram_id=uid, pumpkins=5, secret_unlocked=False, created_at=now)
        session.add(player)
        session.flush()
    return player


def _solved(session, uid: int) -> dict[int, HalloweenRoom]:
    return {r.room: r for r in session.scalars(select(HalloweenRoom).where(HalloweenRoom.telegram_id == uid)) if r.solved_at is not None}


def first_witness_id(session) -> int | None:
    """The earliest persisted sixth-room completion wins, including past solves."""
    return session.scalar(
        select(HalloweenRoom.telegram_id)
        .where(HalloweenRoom.room == 6, HalloweenRoom.solved_at.is_not(None))
        .order_by(HalloweenRoom.solved_at.asc(), HalloweenRoom.telegram_id.asc())
        .limit(1)
    )


def _can_enter(room: int, solved: dict, player: HalloweenPlayer | None, now: datetime, uid: int) -> bool:
    if room == 1:
        return True
    if room <= 5:
        return room - 1 in solved
    if core.is_owner(uid):
        return True
    if player is None:
        return False
    return all(i in solved for i in range(1, 6)) and player.secret_unlocked and now >= SECRET_AT


def _status_for(uid: int, now: datetime | None = None) -> dict:
    now = now or core.now_utc()
    with core.SessionLocal() as session:
        player = session.get(HalloweenPlayer, uid)
        progress = {r.room: r for r in session.scalars(select(HalloweenRoom).where(HalloweenRoom.telegram_id == uid))}
        solved = {i: r for i, r in progress.items() if r.solved_at is not None}
        inventory = {r.item: r.quantity for r in session.scalars(select(HalloweenInventory).where(HalloweenInventory.telegram_id == uid))}
        effects = {(r.room, r.item) for r in session.scalars(select(HalloweenEffect).where(HalloweenEffect.telegram_id == uid))}
        badge = session.get(HalloweenBadge, uid) is not None
        final_completed = 6 in solved
        first_witness = final_completed and first_witness_id(session) == uid
    items = []
    for room, (title, subtitle) in enumerate(ROOMS, start=1):
        row = progress.get(room)
        completed = room in solved
        accessible = _can_enter(room, solved, player, now, uid)
        open_now = (START_AT <= now < END_AT or (room == 6 and core.is_owner(uid) and now < END_AT)) and accessible
        current = {"room": room, "title": title, "subtitle": subtitle,
                   "completed": completed, "accessible": open_now,
                   "reward": REWARDS[room], "pumpkins_reward": PUMPKINS[room],
                   "fragment": _fragment(uid, room) if completed else None,
                   "attempts": row.attempts if row else 0,
                   "retry_at": _utc(row.retry_at).isoformat() if row and row.retry_at and _utc(row.retry_at) > now else None,
                   "clues": [{"item": item, "text": _hint(uid, room, item)}
                             for item in ("loupe", "candle", "eye") if (room, item) in effects]}
        if open_now or completed:
            current["puzzle"] = _puzzle(uid, room)[0]
        items.append(current)
    return {"ok": True, "started": now >= START_AT, "active": START_AT <= now < END_AT,
            "finished": now >= END_AT, "starts_at": START_AT.isoformat(),
            "secret_at": SECRET_AT.isoformat(), "ends_at": END_AT.isoformat(),
            "pumpkins": player.pumpkins if player else 5,
            "inventory": {item: inventory.get(item, 0) for item in ITEMS},
            "secret_unlocked": bool(player and player.secret_unlocked),
            "owner_early_access": core.is_owner(uid) and now < END_AT,
            "badge": badge, "final_badge": final_completed, "first_witness": first_witness,
            "wallet_earned": sum(row.reward for row in solved.values()),
            "rooms": items,
            "shop": [{"key": k, "title": title, "price": price} for k, (title, price) in ITEMS.items()]}


def _room_guard(session, uid: int, room: int, player: HalloweenPlayer, now: datetime) -> None:
    if not _can_enter(room, _solved(session, uid), player, now, uid):
        raise HTTPException(status_code=409, detail="Сначала открой предыдущие комнаты")


@router.get("/api/halloween-2026/status")
def halloween_status(x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data")):
    user = _identity(x_telegram_init_data)
    return _status_for(int(user["id"]))


@router.post("/api/halloween-2026/answer")
def halloween_answer(payload: AnswerInput,
                     x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data")):
    tg_user = _identity(x_telegram_init_data)
    if not KEY_RE.fullmatch(payload.request_key):
        raise HTTPException(status_code=422, detail="Некорректный ключ запроса")
    now = core.now_utc()
    uid = int(tg_user["id"])
    if payload.room != 6 or not (core.is_owner(uid) and now < END_AT):
        _require_live(now)
    with core.SessionLocal.begin() as session:
        user = _lock_user(session, tg_user, now)
        player = _player(session, uid, now)
        row = session.get(HalloweenRoom, (uid, payload.room))
        if row and row.solved_at is not None:
            result = {"correct": True, "already_completed": True, "reward": row.reward}
        elif row and row.last_request_key == payload.request_key:
            result = {"correct": bool(row.last_correct), "already_completed": False, "reward": 0,
                      "retry_at": _utc(row.retry_at).isoformat() if row.retry_at else None}
        else:
            _room_guard(session, uid, payload.room, player, now)
            if row is None:
                row = HalloweenRoom(telegram_id=uid, room=payload.room, attempts=0, reward=0)
                session.add(row)
            if row.retry_at and _utc(row.retry_at) > now:
                raise HTTPException(status_code=429, detail="Попытки восстановятся через несколько минут")
            if row.retry_at and _utc(row.retry_at) <= now:
                row.retry_at = None
                row.attempts = 0
            expected = _puzzle(uid, payload.room)[1]
            normalized = "".join(payload.answer.strip().upper().split()).replace("Ё", "Е")
            correct = normalized == expected
            row.last_request_key = payload.request_key
            row.last_correct = correct
            if correct:
                amount = REWARDS[payload.room]
                if user.balance + amount > MAX_BALANCE:
                    raise HTTPException(status_code=409, detail="Достигнут предел баланса кошелька")
                user.balance += amount
                player.pumpkins += PUMPKINS[payload.room]
                tx = core.Transaction(telegram_id=uid, amount=amount, operation_type="halloween_2026_reward",
                                      description=f"Ночь Няника · комната {payload.room}", created_at=now)
                session.add(tx)
                session.flush()
                row.solved_at, row.reward, row.transaction_id = now, amount, tx.id
                if payload.room == 5 and session.get(HalloweenBadge, uid) is None:
                    session.add(HalloweenBadge(telegram_id=uid, awarded_at=now))
                    from .advanced_features import WalletNotification
                    session.add(WalletNotification(telegram_id=uid, kind="halloween_reward",
                                                   title="Ночь Няника · пройдено",
                                                   body="Все пять комнат пройдены. Значок «Призрак Няника» получен!",
                                                   is_read=False, created_at=now))
                result = {"correct": True, "already_completed": False, "reward": amount}
            else:
                row.attempts += 1
                if row.attempts >= 3:
                    row.attempts = 0
                    row.retry_at = now + timedelta(minutes=5)
                result = {"correct": False, "already_completed": False, "reward": 0,
                          "retry_at": row.retry_at.isoformat() if row.retry_at else None}
    return {"ok": True, **result, "state": _status_for(uid, now)}


@router.post("/api/halloween-2026/buy")
def halloween_buy(payload: BuyInput,
                  x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data")):
    tg_user = _identity(x_telegram_init_data)
    if payload.item not in ITEMS or not KEY_RE.fullmatch(payload.request_key):
        raise HTTPException(status_code=422, detail="Неизвестный предмет или ключ покупки")
    now = core.now_utc()
    _require_live(now)
    uid = int(tg_user["id"])
    with core.SessionLocal.begin() as session:
        _lock_user(session, tg_user, now)
        player = _player(session, uid, now)
        previous = session.scalar(select(HalloweenPurchase).where(HalloweenPurchase.telegram_id == uid,
                                                                  HalloweenPurchase.request_key == payload.request_key))
        if previous:
            if previous.item != payload.item:
                raise HTTPException(status_code=409, detail="Ключ уже использован для другого предмета")
            duplicate = True
        else:
            cost = ITEMS[payload.item][1]
            owned_key = session.get(HalloweenInventory, (uid, "key")) if payload.item == "key" else None
            if payload.item == "key" and (player.secret_unlocked or (owned_key and owned_key.quantity > 0)):
                raise HTTPException(status_code=409, detail="У тебя уже есть ключ")
            if player.pumpkins < cost:
                raise HTTPException(status_code=409, detail="Не хватает тыкв")
            inventory = session.get(HalloweenInventory, (uid, payload.item))
            if inventory is None:
                session.add(HalloweenInventory(telegram_id=uid, item=payload.item, quantity=1))
            else:
                inventory.quantity += 1
            player.pumpkins -= cost
            session.add(HalloweenPurchase(telegram_id=uid, item=payload.item,
                                          request_key=payload.request_key, cost=cost, created_at=now))
            duplicate = False
    return {"ok": True, "duplicate": duplicate, "state": _status_for(uid, now)}


@router.post("/api/halloween-2026/use")
def halloween_use(payload: UseInput,
                  x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data")):
    tg_user = _identity(x_telegram_init_data)
    if payload.item not in ("loupe", "candle", "eye"):
        raise HTTPException(status_code=422, detail="Этот предмет нельзя применить здесь")
    now = core.now_utc()
    _require_live(now)
    uid = int(tg_user["id"])
    with core.SessionLocal.begin() as session:
        _lock_user(session, tg_user, now)
        player = _player(session, uid, now)
        _room_guard(session, uid, payload.room, player, now)
        row = session.get(HalloweenRoom, (uid, payload.room))
        if row and row.solved_at:
            raise HTTPException(status_code=409, detail="Комната уже пройдена")
        previous = session.get(HalloweenEffect, (uid, payload.room, payload.item))
        if previous:
            duplicate = True
        else:
            inventory = session.get(HalloweenInventory, (uid, payload.item))
            if inventory is None or inventory.quantity <= 0:
                raise HTTPException(status_code=409, detail="Предмета нет в инвентаре")
            inventory.quantity -= 1
            session.add(HalloweenEffect(telegram_id=uid, room=payload.room, item=payload.item, created_at=now))
            duplicate = False
    return {"ok": True, "duplicate": duplicate, "state": _status_for(uid, now)}


@router.post("/api/halloween-2026/unlock-secret")
def halloween_unlock(x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data")):
    tg_user = _identity(x_telegram_init_data)
    now = core.now_utc()
    if not (core.is_owner(int(tg_user["id"])) and now < END_AT):
        _require_live(now)
    if now < SECRET_AT and not core.is_owner(int(tg_user["id"])):
        raise HTTPException(status_code=409, detail="Последняя дверь откроется в 23:00 МСК")
    uid = int(tg_user["id"])
    with core.SessionLocal.begin() as session:
        _lock_user(session, tg_user, now)
        player = _player(session, uid, now)
        if player.secret_unlocked:
            duplicate = True
        else:
            if not core.is_owner(uid):
                if not all(i in _solved(session, uid) for i in range(1, 6)):
                    raise HTTPException(status_code=409, detail="Сначала пройди пять комнат")
                key = session.get(HalloweenInventory, (uid, "key"))
                if key is None or key.quantity <= 0:
                    raise HTTPException(status_code=409, detail="Нужен ржавый ключ из лавки")
                key.quantity -= 1
            player.secret_unlocked = True
            duplicate = False
    return {"ok": True, "duplicate": duplicate, "state": _status_for(uid, now)}


def register_halloween_2026(app) -> None:
    global _REGISTERED
    if _REGISTERED:
        return
    core.Base.metadata.create_all(core.engine, tables=[
        HalloweenPlayer.__table__, HalloweenRoom.__table__, HalloweenInventory.__table__,
        HalloweenEffect.__table__, HalloweenPurchase.__table__, HalloweenBadge.__table__,
    ])
    app.include_router(router)
    _REGISTERED = True
