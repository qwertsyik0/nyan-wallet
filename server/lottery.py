"""Independent Nyan lottery. No changes to existing giveaways or wallet ledgers.

Each paid entry has a snapshotted draw weight. Closing a round fixes its
entrant pool; each winning user may receive only one prize in that round.
"""

from __future__ import annotations

import asyncio
import logging
import secrets
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func, select
from sqlalchemy.orm import Mapped, mapped_column

from . import backend_app as core


LOG = logging.getLogger("nyan_wallet.lottery")
router = APIRouter()
_REGISTERED = False
_AUTO_TASK: asyncio.Task | None = None
MAX_TICKETS_PER_ROUND = 20000


def now() -> datetime:
    return datetime.now(timezone.utc)


def aware(value: datetime | None) -> datetime | None:
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=timezone.utc)


class LotteryRound(core.Base):
    __tablename__ = "lottery_rounds"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    mode: Mapped[str] = mapped_column(String(12), nullable=False)
    status: Mapped[str] = mapped_column(String(14), nullable=False, index=True, default="draft")
    max_per_user: Mapped[int] = mapped_column(Integer, nullable=False)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class LotteryTier(core.Base):
    __tablename__ = "lottery_tiers"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    round_id: Mapped[int] = mapped_column(Integer, ForeignKey("lottery_rounds.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    price: Mapped[int] = mapped_column(Integer, nullable=False)
    weight: Mapped[int] = mapped_column(Integer, nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)


class LotteryPrize(core.Base):
    __tablename__ = "lottery_prizes"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    round_id: Mapped[int] = mapped_column(Integer, ForeignKey("lottery_rounds.id", ondelete="CASCADE"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(90), nullable=False)
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)


class LotteryPurchase(core.Base):
    __tablename__ = "lottery_purchases"
    __table_args__ = (UniqueConstraint("round_id", "telegram_id", "request_key", name="uq_lottery_request"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    round_id: Mapped[int] = mapped_column(Integer, ForeignKey("lottery_rounds.id", ondelete="CASCADE"), nullable=False, index=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.telegram_id"), nullable=False, index=True)
    tier_id: Mapped[int] = mapped_column(Integer, ForeignKey("lottery_tiers.id"), nullable=False)
    count: Mapped[int] = mapped_column(Integer, nullable=False)
    cost: Mapped[int] = mapped_column(Integer, nullable=False)
    balance_after: Mapped[int] = mapped_column(Integer, nullable=False)
    request_key: Mapped[str] = mapped_column(String(64), nullable=False)
    transaction_id: Mapped[int] = mapped_column(Integer, ForeignKey("transactions.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class LotteryTicket(core.Base):
    __tablename__ = "lottery_tickets"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    round_id: Mapped[int] = mapped_column(Integer, ForeignKey("lottery_rounds.id", ondelete="CASCADE"), nullable=False, index=True)
    purchase_id: Mapped[int] = mapped_column(Integer, ForeignKey("lottery_purchases.id"), nullable=False, index=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.telegram_id"), nullable=False, index=True)
    tier_id: Mapped[int] = mapped_column(Integer, ForeignKey("lottery_tiers.id"), nullable=False)
    weight: Mapped[int] = mapped_column(Integer, nullable=False)


class LotteryWin(core.Base):
    __tablename__ = "lottery_wins"
    __table_args__ = (
        UniqueConstraint("round_id", "telegram_id", name="uq_lottery_winner_per_round"),
        UniqueConstraint("ticket_id", name="uq_lottery_winning_ticket"),
        UniqueConstraint("prize_id", "slot", name="uq_lottery_prize_slot"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    round_id: Mapped[int] = mapped_column(Integer, ForeignKey("lottery_rounds.id", ondelete="CASCADE"), nullable=False, index=True)
    prize_id: Mapped[int] = mapped_column(Integer, ForeignKey("lottery_prizes.id"), nullable=False)
    slot: Mapped[int] = mapped_column(Integer, nullable=False)
    ticket_id: Mapped[int] = mapped_column(Integer, ForeignKey("lottery_tickets.id"), nullable=False)
    telegram_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.telegram_id"), nullable=False, index=True)
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    selection: Mapped[str] = mapped_column(String(12), nullable=False)
    transaction_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("transactions.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class LotteryAudit(core.Base):
    __tablename__ = "lottery_audit"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    round_id: Mapped[int] = mapped_column(Integer, ForeignKey("lottery_rounds.id", ondelete="CASCADE"), nullable=False, index=True)
    actor_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    action: Mapped[str] = mapped_column(String(35), nullable=False)
    details: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


def audit(session, row: LotteryRound, actor: int, action: str, details: str) -> None:
    session.add(LotteryAudit(round_id=row.id, actor_id=actor, action=action,
                             details=details[:500], created_at=now()))


class TierInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=2, max_length=50)
    price: int = Field(ge=1, le=100000)
    weight: int = Field(ge=1, le=1000)


class PrizeInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=2, max_length=90)
    amount: int = Field(ge=1, le=100000)
    quantity: int = Field(ge=1, le=30)


class RoundInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=3, max_length=120)
    description: str = Field(min_length=5, max_length=1000)
    mode: Literal["automatic", "manual"]
    max_per_user: int = Field(ge=1, le=100)
    ends_at: datetime | None = None
    tiers: list[TierInput] = Field(min_length=1, max_length=6)
    prizes: list[PrizeInput] = Field(min_length=1, max_length=10)

    @model_validator(mode="after")
    def check_rules(self):
        if sum(p.quantity for p in self.prizes) > 30:
            raise ValueError("Максимум 30 призовых мест")
        if sum(p.amount * p.quantity for p in self.prizes) > 1000000:
            raise ValueError("Общий призовой фонд не может превышать 1 000 000 🐾")
        if len({t.name.casefold() for t in self.tiers}) != len(self.tiers):
            raise ValueError("Названия билетов должны различаться")
        return self


class PurchaseInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    tier_id: int = Field(gt=0)
    count: int = Field(ge=1, le=25)
    request_key: str = Field(min_length=8, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")


class AssignInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    prize_id: int = Field(gt=0)
    slot: int = Field(ge=1, le=30)
    telegram_id: int = Field(gt=0)


def auth(header: str | None, *, owner: bool = False) -> dict:
    # No supplied Telegram ID is trusted; signature/time are verified by core.
    from .interactive_ideas import verify_browser_session
    if (header or "").startswith("browser:"):
        telegram = verify_browser_session(header[len("browser:"):])
    else:
        telegram = core.verify_init_data(header or "")
    if owner:
        core.require_owner(telegram)
    return telegram


def lock_round(session, round_id: int) -> LotteryRound:
    row = session.scalar(select(LotteryRound).where(LotteryRound.id == round_id).with_for_update())
    if row is None:
        raise HTTPException(status_code=404, detail="Лотерея не найдена")
    return row


def all_tiers(session, round_id: int):
    return list(session.scalars(select(LotteryTier).where(LotteryTier.round_id == round_id).order_by(LotteryTier.position)))


def all_prizes(session, round_id: int):
    return list(session.scalars(select(LotteryPrize).where(LotteryPrize.round_id == round_id).order_by(LotteryPrize.position)))


def all_wins(session, round_id: int):
    return list(session.scalars(select(LotteryWin).where(LotteryWin.round_id == round_id).order_by(LotteryWin.prize_id, LotteryWin.slot)))


def ticket_count(session, round_id: int, telegram_id: int | None = None) -> int:
    q = select(func.count()).select_from(LotteryTicket).where(LotteryTicket.round_id == round_id)
    if telegram_id is not None:
        q = q.where(LotteryTicket.telegram_id == telegram_id)
    return int(session.scalar(q) or 0)


def round_json(session, row: LotteryRound, user_id: int, *, owner: bool = False) -> dict:
    entries = ticket_count(session, row.id)
    prizes = all_prizes(session, row.id)
    wins = all_wins(session, row.id)
    winner_names = {u.telegram_id: ("@" + u.username if u.username else (u.first_name or "Участник"))
                    for u in session.scalars(select(core.User).where(
                        core.User.telegram_id.in_([w.telegram_id for w in wins])))}
    result = {
        "id": row.id, "title": row.title, "description": row.description,
        "status": row.status, "max_per_user": row.max_per_user,
        "ends_at": aware(row.ends_at).isoformat() if row.ends_at else None,
        "started_at": aware(row.started_at).isoformat() if row.started_at else None,
        "total_tickets": entries, "my_tickets": ticket_count(session, row.id, user_id),
        "tiers": [{"id": t.id, "name": t.name, "price": t.price,
                   **({"weight": t.weight} if owner else {})} for t in all_tiers(session, row.id)],
        "prizes": [{"id": p.id, "title": p.title, "amount": p.amount, "quantity": p.quantity} for p in prizes],
        "winners": [{"prize_id": w.prize_id, "slot": w.slot,
                     "name": winner_names.get(w.telegram_id, "Участник"),
                     "amount": w.amount, "is_me": w.telegram_id == user_id} for w in wins if w.transaction_id is not None],
        "my_spent": int(session.scalar(select(func.coalesce(func.sum(LotteryPurchase.cost), 0)).where(
            LotteryPurchase.round_id == row.id, LotteryPurchase.telegram_id == user_id)) or 0),
    }
    if owner:
        result["mode"] = row.mode
        result["audit"] = [{"action": record.action, "details": record.details,
                           "at": record.created_at.isoformat()} for record in session.scalars(
            select(LotteryAudit).where(LotteryAudit.round_id == row.id)
            .order_by(LotteryAudit.id.desc()).limit(20))]
        result["reserved_winners"] = [{"prize_id": w.prize_id, "slot": w.slot,
                                      "telegram_id": w.telegram_id, "amount": w.amount,
                                      "paid": w.transaction_id is not None} for w in wins]
        result["participants"] = [{"telegram_id": tid, "tickets": count, "weight": weight, "username": username}
                                  for tid, count, weight, username in session.execute(
            select(LotteryTicket.telegram_id, func.count(), func.sum(LotteryTicket.weight), core.User.username)
            .join(core.User, core.User.telegram_id == LotteryTicket.telegram_id)
            .where(LotteryTicket.round_id == row.id)
            .group_by(LotteryTicket.telegram_id, core.User.username)
            .order_by(func.count().desc(), LotteryTicket.telegram_id)
        )]
        result["gross_sales"] = int(session.scalar(select(func.coalesce(func.sum(LotteryPurchase.cost), 0)).where(
            LotteryPurchase.round_id == row.id)) or 0)
    return result


def set_configuration(session, row: LotteryRound, payload: RoundInput) -> None:
    row.title = payload.title.strip()
    row.description = payload.description.strip()
    row.mode = payload.mode
    row.max_per_user = payload.max_per_user
    row.ends_at = aware(payload.ends_at)
    for item in all_tiers(session, row.id):
        session.delete(item)
    for item in all_prizes(session, row.id):
        session.delete(item)
    session.flush()
    session.add_all([LotteryTier(round_id=row.id, name=t.name.strip(), price=t.price,
                                weight=t.weight, position=i) for i, t in enumerate(payload.tiers, 1)])
    session.add_all([LotteryPrize(round_id=row.id, title=p.title.strip(), amount=p.amount,
                                 quantity=p.quantity, position=i) for i, p in enumerate(payload.prizes, 1)])
    session.flush()


def slots(session, round_id: int) -> list[tuple[LotteryPrize, int]]:
    return [(p, index) for p in all_prizes(session, round_id) for index in range(1, p.quantity + 1)]


def select_ticket(candidates: list[LotteryTicket]) -> LotteryTicket:
    """Cryptographically random weighted entry, weights frozen at purchase."""
    if not candidates:
        raise ValueError("Нечего выбирать")
    value = secrets.randbelow(sum(t.weight for t in candidates))
    for ticket in candidates:
        value -= ticket.weight
        if value < 0:
            return ticket
    raise AssertionError("Некорректные веса")


def pay_winners(session, row: LotteryRound) -> None:
    # Called under locked round; no credit until every winner can be validated.
    wins = all_wins(session, row.id)
    if any(w.transaction_id is not None for w in wins):
        raise HTTPException(status_code=409, detail="Призы уже начислены")
    users = {u.telegram_id: u for u in session.scalars(select(core.User).where(
        core.User.telegram_id.in_(sorted(w.telegram_id for w in wins))).order_by(core.User.telegram_id).with_for_update())}
    if len(users) != len(wins):
        raise HTTPException(status_code=409, detail="Кошелёк одного из победителей не найден")
    timestamp = now()
    for win in wins:
        users[win.telegram_id].balance += win.amount
        tx = core.Transaction(telegram_id=win.telegram_id, amount=win.amount,
                              operation_type="lottery_prize",
                              description=f"Лотерея #{row.id}: приз {win.amount} 🐾", created_at=timestamp)
        session.add(tx)
        session.flush()
        win.transaction_id = tx.id
    row.status = "drawn"
    row.completed_at = timestamp


def finish_automatic(session, row: LotteryRound) -> None:
    if row.status != "closed" or row.mode != "automatic":
        raise HTTPException(status_code=409, detail="Розыгрыш не готов к автоматическому выбору")
    entries = list(session.scalars(select(LotteryTicket).where(LotteryTicket.round_id == row.id).order_by(LotteryTicket.id)))
    winners = set()
    for prize, slot in slots(session, row.id):
        eligible = [ticket for ticket in entries if ticket.telegram_id not in winners]
        if not eligible:
            break
        ticket = select_ticket(eligible)
        winners.add(ticket.telegram_id)
        session.add(LotteryWin(round_id=row.id, prize_id=prize.id, slot=slot,
                               ticket_id=ticket.id, telegram_id=ticket.telegram_id,
                               amount=prize.amount, selection="automatic", created_at=now()))
    session.flush()
    pay_winners(session, row)
    audit(session, row, 0, "automatic_draw", f"Победителей: {len(winners)}")


def close_locked(session, row: LotteryRound) -> None:
    if row.status != "active":
        raise HTTPException(status_code=409, detail="Лотерея уже не принимает билеты")
    row.status = "closed"
    if row.mode == "automatic":
        finish_automatic(session, row)


def close_expired(session, row: LotteryRound) -> None:
    if row.status == "active" and row.ends_at and aware(row.ends_at) <= now():
        close_locked(session, row)


@router.get("/api/lottery")
def list_lotteries(x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data")):
    tg = auth(x_telegram_init_data)
    owner = core.is_owner(tg["id"])
    with core.SessionLocal() as session:
        rows = list(session.scalars(select(LotteryRound).order_by(LotteryRound.id.desc()).limit(60)))
        return {"ok": True, "is_owner": owner,
                "rounds": [round_json(session, row, tg["id"], owner=owner) for row in rows
                           if row.status != "archived" and (owner or row.status not in {"draft", "cancelled"})]}


@router.get("/api/lottery/{round_id}")
def lottery_detail(round_id: int, x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data")):
    tg = auth(x_telegram_init_data)
    with core.SessionLocal() as session:
        row = session.get(LotteryRound, round_id)
        if row is None or row.status == "archived" or (row.status in {"draft", "cancelled"} and not core.is_owner(tg["id"])):
            raise HTTPException(status_code=404, detail="Лотерея не найдена")
        return {"ok": True, "round": round_json(session, row, tg["id"], owner=core.is_owner(tg["id"]))}


@router.post("/api/owner/lottery/rounds")
def owner_create(payload: RoundInput, x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data")):
    tg = auth(x_telegram_init_data, owner=True)
    with core.SessionLocal.begin() as session:
        row = LotteryRound(title=payload.title, description=payload.description, mode=payload.mode,
                           max_per_user=payload.max_per_user, ends_at=aware(payload.ends_at),
                           status="draft", created_at=now())
        session.add(row)
        session.flush()
        set_configuration(session, row, payload)
        audit(session, row, tg["id"], "created", "Создан черновик")
        return {"ok": True, "round": round_json(session, row, tg["id"], owner=True)}


@router.post("/api/owner/lottery/rounds/{round_id}/update")
def owner_update(round_id: int, payload: RoundInput, x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data")):
    tg = auth(x_telegram_init_data, owner=True)
    with core.SessionLocal.begin() as session:
        row = lock_round(session, round_id)
        if row.status != "draft" and (row.status != "active" or ticket_count(session, row.id) > 0):
            raise HTTPException(status_code=409, detail="После продажи билетов нельзя менять шансы, цены и призы. Создайте новый тираж.")
        if row.status == "active" and payload.ends_at and aware(payload.ends_at) <= now():
            raise HTTPException(status_code=400, detail="Время окончания должно быть в будущем")
        set_configuration(session, row, payload)
        audit(session, row, tg["id"], "updated", "Обновлены правила, билеты и призы")
        return {"ok": True, "round": round_json(session, row, tg["id"], owner=True)}


@router.post("/api/owner/lottery/rounds/{round_id}/activate")
def owner_activate(round_id: int, x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data")):
    tg = auth(x_telegram_init_data, owner=True)
    with core.SessionLocal.begin() as session:
        row = lock_round(session, round_id)
        if row.status != "draft":
            raise HTTPException(status_code=409, detail="Можно запустить только черновик")
        if row.mode == "automatic" and not row.ends_at:
            raise HTTPException(status_code=400, detail="Для автоматической лотереи установите дату окончания")
        if row.ends_at and aware(row.ends_at) <= now():
            raise HTTPException(status_code=400, detail="Дата окончания уже прошла")
        row.status, row.started_at = "active", now()
        audit(session, row, tg["id"], "activated", "Открыта продажа билетов")
        return {"ok": True, "status": row.status}


@router.post("/api/lottery/{round_id}/purchase")
def lottery_purchase(round_id: int, payload: PurchaseInput, x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data")):
    tg = auth(x_telegram_init_data)
    if core.is_owner(tg["id"]):
        raise HTTPException(status_code=403, detail="Владелец не участвует в платной лотерее")
    core.get_or_create_user(tg)  # Ensure wallet existence outside the debit transaction.
    with core.SessionLocal.begin() as session:
        row = lock_round(session, round_id)
        prev = session.scalar(select(LotteryPurchase).where(
            LotteryPurchase.round_id == round_id, LotteryPurchase.telegram_id == tg["id"],
            LotteryPurchase.request_key == payload.request_key))
        if prev:
            if prev.tier_id != payload.tier_id or prev.count != payload.count:
                raise HTTPException(status_code=409, detail="Этот ключ покупки уже использован для другого заказа")
            return {"ok": True, "duplicate": True, "cost": prev.cost, "balance": prev.balance_after,
                    "tickets_added": prev.count}
        if row.status != "active" or (row.ends_at and aware(row.ends_at) <= now()):
            raise HTTPException(status_code=409, detail="Продажа билетов завершена")
        tier = session.get(LotteryTier, payload.tier_id)
        if not tier or tier.round_id != row.id:
            raise HTTPException(status_code=400, detail="Такого билета нет")
        if ticket_count(session, row.id, tg["id"]) + payload.count > row.max_per_user:
            raise HTTPException(status_code=409, detail=f"На одного участника максимум {row.max_per_user} билетов")
        if ticket_count(session, row.id) + payload.count > MAX_TICKETS_PER_ROUND:
            raise HTTPException(status_code=409, detail="Лимит билетов на тираж исчерпан")
        user = session.scalar(select(core.User).where(core.User.telegram_id == tg["id"]).with_for_update())
        cost = tier.price * payload.count
        if not user or user.balance < cost:
            raise HTTPException(status_code=409, detail="Недостаточно лапкоинов")
        user.balance -= cost
        tx = core.Transaction(telegram_id=user.telegram_id, amount=-cost, operation_type="lottery_ticket",
                              description=f"Лотерея #{row.id}: {tier.name} × {payload.count}", created_at=now())
        session.add(tx)
        session.flush()
        purchase = LotteryPurchase(round_id=row.id, telegram_id=user.telegram_id,
                                   tier_id=tier.id, count=payload.count, cost=cost,
                                   balance_after=user.balance, transaction_id=tx.id,
                                   request_key=payload.request_key, created_at=now())
        session.add(purchase)
        session.flush()
        session.add_all([LotteryTicket(round_id=row.id, purchase_id=purchase.id,
                                       telegram_id=user.telegram_id, tier_id=tier.id,
                                       weight=tier.weight) for _ in range(payload.count)])
        return {"ok": True, "duplicate": False, "cost": cost, "balance": user.balance,
                "tickets_added": payload.count}


@router.post("/api/owner/lottery/rounds/{round_id}/close")
def owner_close(round_id: int, x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data")):
    tg = auth(x_telegram_init_data, owner=True)
    with core.SessionLocal.begin() as session:
        row = lock_round(session, round_id)
        close_locked(session, row)
        audit(session, row, tg["id"], "closed", "Приём билетов закрыт")
        return {"ok": True, "status": row.status, "winners": len(all_wins(session, row.id))}


@router.post("/api/owner/lottery/rounds/{round_id}/assign")
def owner_assign(round_id: int, payload: AssignInput, x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data")):
    tg = auth(x_telegram_init_data, owner=True)
    with core.SessionLocal.begin() as session:
        row = lock_round(session, round_id)
        if row.mode != "manual" or row.status != "closed":
            raise HTTPException(status_code=409, detail="Ручной выбор доступен только после закрытия ручного тиража")
        prize = session.get(LotteryPrize, payload.prize_id)
        if not prize or prize.round_id != round_id or payload.slot > prize.quantity:
            raise HTTPException(status_code=400, detail="Некорректное призовое место")
        if session.scalar(select(LotteryWin.id).where(LotteryWin.round_id == round_id,
                  LotteryWin.prize_id == prize.id, LotteryWin.slot == payload.slot)):
            raise HTTPException(status_code=409, detail="Это место уже занято")
        if session.scalar(select(LotteryWin.id).where(LotteryWin.round_id == round_id,
                  LotteryWin.telegram_id == payload.telegram_id)):
            raise HTTPException(status_code=409, detail="Участник уже выбран победителем")
        ticket = session.scalar(select(LotteryTicket).where(LotteryTicket.round_id == round_id,
                   LotteryTicket.telegram_id == payload.telegram_id).order_by(LotteryTicket.id).limit(1))
        if not ticket:
            raise HTTPException(status_code=409, detail="У выбранного пользователя нет билетов")
        session.add(LotteryWin(round_id=round_id, prize_id=prize.id, slot=payload.slot,
                               ticket_id=ticket.id, telegram_id=ticket.telegram_id,
                               amount=prize.amount, selection="manual", created_at=now()))
        audit(session, row, tg["id"], "assigned", f"Приз {prize.id}, место {payload.slot}, победитель {payload.telegram_id}")
        return {"ok": True, "message": "Победитель выбран. Начисление только после завершения тиража."}


@router.post("/api/owner/lottery/rounds/{round_id}/finalize")
def owner_finalize(round_id: int, x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data")):
    tg = auth(x_telegram_init_data, owner=True)
    with core.SessionLocal.begin() as session:
        row = lock_round(session, round_id)
        if row.mode != "manual" or row.status != "closed":
            raise HTTPException(status_code=409, detail="Ручной тираж уже завершён или ещё открыт")
        if not all_wins(session, row.id) and ticket_count(session, row.id):
            raise HTTPException(status_code=409, detail="Сначала выберите победителей")
        pay_winners(session, row)
        audit(session, row, tg["id"], "finalized", "Ручной выбор подтверждён, призы начислены")
        return {"ok": True, "status": row.status, "winners": len(all_wins(session, row.id))}


@router.post("/api/owner/lottery/rounds/{round_id}/unassign")
def owner_unassign(round_id: int, payload: AssignInput, x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data")):
    tg = auth(x_telegram_init_data, owner=True)
    with core.SessionLocal.begin() as session:
        row = lock_round(session, round_id)
        if row.mode != "manual" or row.status != "closed":
            raise HTTPException(status_code=409, detail="После выдачи призов изменить победителя нельзя")
        winner = session.scalar(select(LotteryWin).where(
            LotteryWin.round_id == round_id, LotteryWin.prize_id == payload.prize_id,
            LotteryWin.slot == payload.slot, LotteryWin.telegram_id == payload.telegram_id))
        if not winner:
            raise HTTPException(status_code=404, detail="Назначение не найдено")
        session.delete(winner)
        audit(session, row, tg["id"], "unassigned", f"Отмена выбора: приз {payload.prize_id}, место {payload.slot}, участник {payload.telegram_id}")
        return {"ok": True}


@router.post("/api/owner/lottery/rounds/{round_id}/cancel")
def owner_cancel(round_id: int, x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data")):
    tg = auth(x_telegram_init_data, owner=True)
    with core.SessionLocal.begin() as session:
        row = lock_round(session, round_id)
        if row.status not in {"draft", "active", "closed"} or all_wins(session, row.id):
            raise HTTPException(status_code=409, detail="Тираж с назначенными или оплаченными победителями нельзя отменить")
        refunds = session.execute(select(LotteryPurchase.telegram_id, func.sum(LotteryPurchase.cost)).where(
            LotteryPurchase.round_id == row.id).group_by(LotteryPurchase.telegram_id)
            .order_by(LotteryPurchase.telegram_id)).all()
        for tid, cost in refunds:
            if cost <= 0:
                continue
            user = session.scalar(select(core.User).where(core.User.telegram_id == tid).with_for_update())
            user.balance += int(cost)
            session.add(core.Transaction(telegram_id=tid, amount=int(cost),
                                         operation_type="lottery_refund",
                                         description=f"Возврат за отменённую лотерею #{row.id}", created_at=now()))
        row.status, row.completed_at = "cancelled", now()
        audit(session, row, tg["id"], "cancelled", f"Возвраты участникам: {len(refunds)}")
        return {"ok": True, "status": row.status, "refunds": len(refunds)}


@router.post("/api/owner/lottery/rounds/{round_id}/archive")
def owner_archive(round_id: int, x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data")):
    tg = auth(x_telegram_init_data, owner=True)
    with core.SessionLocal.begin() as session:
        row = lock_round(session, round_id)
        if row.status not in {"drawn", "cancelled"}:
            raise HTTPException(status_code=409, detail="В архив можно убрать только завершённый или отменённый тираж")
        previous = row.status
        row.status = "archived"
        audit(session, row, tg["id"], "archived", f"Скрыт из мини-приложения. Предыдущий статус: {previous}. Денежные операции сохранены")
        return {"ok": True, "status": "archived"}


def process_due_rounds() -> None:
    with core.SessionLocal() as session:
        due = list(session.scalars(select(LotteryRound.id).where(
            LotteryRound.status == "active", LotteryRound.ends_at.is_not(None),
            LotteryRound.ends_at <= now()).order_by(LotteryRound.id).limit(30)))
    for round_id in due:
        try:
            with core.SessionLocal.begin() as session:
                row = lock_round(session, round_id)
                close_expired(session, row)
        except Exception:
            LOG.exception("Unable to settle lottery round %s; will retry", round_id)


async def auto_loop():
    while True:
        try:
            await asyncio.to_thread(process_due_rounds)
        except Exception:
            LOG.exception("Lottery timer failed")
        await asyncio.sleep(20)


async def start_auto_loop():
    global _AUTO_TASK
    if _AUTO_TASK is None or _AUTO_TASK.done():
        _AUTO_TASK = asyncio.create_task(auto_loop(), name="nyan-lottery-draw-loop")


def register_lottery(app) -> None:
    global _REGISTERED
    if _REGISTERED:
        return
    core.Base.metadata.create_all(core.engine, tables=[
        LotteryRound.__table__, LotteryTier.__table__, LotteryPrize.__table__,
        LotteryPurchase.__table__, LotteryTicket.__table__, LotteryWin.__table__,
        LotteryAudit.__table__,
    ])
    app.include_router(router)
    app.add_event_handler("startup", start_auto_loop)
    _REGISTERED = True
