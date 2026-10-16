"""Finance internship: all proposed decisions require authenticated owner approval.

A trainee can draft grant/debit/investigation requests, never directly mutate
balances or call privileged endpoints. Role grants/revocations are owner-only.
"""
from __future__ import annotations

import json
import logging
import re
import urllib.parse
import urllib.request
import urllib.error
from datetime import datetime, timedelta
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, mapped_column

from . import backend_app as core
from .extended_features import audit
from .finance_recruitment import FinancialAdminApplication

router = APIRouter()
_REGISTERED = False
LOG = logging.getLogger("nyan_wallet.finance_workspace")
WORKSPACE_URL = "https://qwertsyik0.github.io/nyan-wallet/finance-workspace.html"
MAX_AMOUNT = 100_000
MAX_PENDING_PER_TRAINEE = 15
MAX_DAILY_PER_TRAINEE = 30
TOKEN_PATTERN = re.compile(r"^[a-zA-Z0-9_-]{12,64}$")


class FinanceTrainee(core.Base):
    __tablename__ = "finance_trainees"

    telegram_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.telegram_id", ondelete="CASCADE"),
        primary_key=True,
    )
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    granted_by: Mapped[int] = mapped_column(BigInteger, nullable=False)
    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class FinanceDecisionRequest(core.Base):
    __tablename__ = "finance_decision_requests"
    __table_args__ = (
        UniqueConstraint("trainee_id", "request_token", name="uq_finance_trainee_token"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    trainee_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.telegram_id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    target_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.telegram_id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    target_reference: Mapped[str | None] = mapped_column(String(128), nullable=True)
    action: Mapped[str] = mapped_column(String(16), nullable=False)
    amount: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    evidence: Mapped[str | None] = mapped_column(Text, nullable=True)
    request_token: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decided_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    owner_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    transaction_id: Mapped[int | None] = mapped_column(Integer, nullable=True)


class FinanceTelegramDelivery(core.Base):
    """State of the Telegram user-message associated with an approved finance operation."""
    __tablename__ = "finance_telegram_deliveries"

    request_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("finance_decision_requests.id", ondelete="CASCADE"),
        primary_key=True,
    )
    recipient_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(String(250), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ProposalPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    target: str | None = Field(default=None, max_length=128)
    action: Literal["grant", "debit", "investigate"]
    amount: int = Field(ge=0, le=MAX_AMOUNT)
    reason: str = Field(min_length=10, max_length=300)
    evidence: str | None = Field(default=None, max_length=500)
    request_token: str = Field(min_length=12, max_length=64)

    @field_validator("target", "reason", "evidence")
    @classmethod
    def normalize_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return " ".join(value.strip().split())


class DecisionPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    decision: Literal["approve", "reject"]
    note: str | None = Field(default=None, max_length=400)

    @field_validator("note")
    @classmethod
    def clean_note(cls, value: str | None) -> str | None:
        return " ".join(value.split()).strip() or None if value is not None else None


def _name(user: core.User | None) -> str:
    if user is None:
        return "пользователь"
    if user.username:
        return "@" + user.username
    return " ".join(filter(None, [user.first_name, user.last_name])) or "пользователь"


def _serialize(item: FinanceDecisionRequest, session, *, include_trainee: bool = False) -> dict:
    target = session.get(core.User, item.target_id) if item.target_id is not None else None
    label = _name(target) if target is not None else (
        item.target_reference or "без указанного кошелька"
    )
    result = {
        "id": item.id,
        "target_label": label,
        "target_id": item.target_id,
        "target_reference": item.target_reference,
        "action": item.action,
        "amount": item.amount,
        "reason": item.reason,
        "evidence": item.evidence,
        "status": item.status,
        "created_at": item.created_at.isoformat(),
        "decided_at": item.decided_at.isoformat() if item.decided_at else None,
        "owner_note": item.owner_note,
        "transaction_id": item.transaction_id,
    }
    if include_trainee:
        delivery = session.get(FinanceTelegramDelivery, item.id)
        result["telegram_notification"] = (
            {"status": delivery.status, "attempts": delivery.attempts,
             "last_error": delivery.last_error,
             "sent_at": delivery.sent_at.isoformat() if delivery.sent_at else None}
            if delivery else None
        )
        result["trainee_id"] = item.trainee_id
        result["trainee_label"] = _name(session.get(core.User, item.trainee_id))
    return result


def _staff_or_forbidden(session, telegram_id: int, *, lock: bool = False) -> FinanceTrainee:
    query = select(FinanceTrainee).where(
        FinanceTrainee.telegram_id == telegram_id,
        FinanceTrainee.active.is_(True),
    )
    if lock:
        query = query.with_for_update()
    role = session.scalar(query)
    if not role:
        raise HTTPException(status_code=403, detail="Доступ к финансам стажёра не предоставлен")
    return role


def _send_notification(chat_id: int | None, message: str, *, button: bool = False) -> None:
    if not chat_id or not core.BOT_TOKEN:
        return
    data: dict[str, str] = {"chat_id": str(chat_id), "text": message}
    if button:
        data["reply_markup"] = json.dumps({
            "inline_keyboard": [[{
                "text": "Управление финансами",
                "web_app": {"url": WORKSPACE_URL},
            }]]
        }, ensure_ascii=False)
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{core.BOT_TOKEN}/sendMessage",
        data=urllib.parse.urlencode(data).encode("utf-8"),
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=7) as response:
            response.read()
    except Exception:
        LOG.warning("Finance trainee notification could not be delivered", exc_info=True)



def _telegram_finance_notice(chat_id: int, message: str) -> tuple[bool, str | None]:
    """Send a recipient notification without exposing the bot token in logs."""
    if not core.BOT_TOKEN:
        return False, "Токен бота не настроен"
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{core.BOT_TOKEN}/sendMessage",
        data=json.dumps({"chat_id": chat_id, "text": message}, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=8) as response:
            result = json.loads(response.read().decode("utf-8"))
        if not result.get("ok"):
            return False, str(result.get("description", "Telegram API: ok=false"))[:250]
        return True, None
    except urllib.error.HTTPError as exc:
        # Telegram returns errors such as "Forbidden: bot was blocked by the user".
        # Keep this information available to the owner without leaking credentials.
        try:
            data = json.loads(exc.read().decode("utf-8", errors="replace"))
            reason = str(data.get("description") or f"Telegram HTTP {exc.code}")
        except Exception:
            reason = f"Telegram HTTP {exc.code}"
        return False, reason[:250]
    except Exception as exc:
        return False, f"Ошибка отправки: {type(exc).__name__}"


def _send_approved_finance_notice(request_id: int) -> None:
    """Delivery is independent of the financial transaction: errors cannot undo a credit."""
    with core.SessionLocal() as session:
        with session.begin():
            delivery = session.scalar(
                select(FinanceTelegramDelivery).where(
                    FinanceTelegramDelivery.request_id == request_id
                ).with_for_update()
            )
            if delivery is None or delivery.status in {"sent", "sending"}:
                return
            decision = session.get(FinanceDecisionRequest, request_id)
            if not decision or decision.status != "approved" or not decision.transaction_id:
                return
            tx = session.get(core.Transaction, decision.transaction_id)
            if tx is None or tx.telegram_id != decision.target_id:
                LOG.error("FINANCE_DELIVERY invalid_request id=%s", request_id)
                return
            if tx.amount != (decision.amount if decision.action == "grant" else -decision.amount):
                LOG.error("FINANCE_DELIVERY amount_mismatch id=%s", request_id)
                return
            delivery.status = "sending"
            delivery.attempts += 1
            delivery.updated_at = core.now_utc()
            chat_id = delivery.recipient_id
            reason = decision.reason
            amount = decision.amount
            direction = decision.action

    if direction == "grant":
        msg = (f"🐾 Nyan Wallet | Начисление\n\n"
               f"На твой кошелёк начислено +{amount} 🐾\n"
               f"Причина: {reason}\n\n"
               f"Операция подтверждена владельцем · заявка №{request_id}")
    else:
        msg = (f"🐾 Nyan Wallet | Списание\n\n"
               f"С твоего кошелька списано {amount} 🐾\n"
               f"Причина: {reason}\n\n"
               f"Операция подтверждена владельцем · заявка №{request_id}")
    success, error = _telegram_finance_notice(chat_id, msg)
    with core.SessionLocal() as session:
        with session.begin():
            delivery = session.scalar(
                select(FinanceTelegramDelivery).where(
                    FinanceTelegramDelivery.request_id == request_id
                ).with_for_update()
            )
            if delivery is not None:
                delivery.status = "sent" if success else "failed"
                delivery.last_error = None if success else error
                delivery.updated_at = core.now_utc()
                if success:
                    delivery.sent_at = core.now_utc()
    if success:
        LOG.info("FINANCE_DELIVERY sent request_id=%s recipient=%s", request_id, chat_id)
    else:
        LOG.warning("FINANCE_DELIVERY failed request_id=%s reason=%s", request_id, error)


@router.get("/api/finance/workspace/access")
async def access(
    x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data"),
):
    user = core.verify_init_data(x_telegram_init_data or "")
    with core.SessionLocal() as session:
        role = session.get(FinanceTrainee, user["id"])
        return {
            "ok": True,
            "is_owner": bool(core.is_owner(user["id"])),
            "is_trainee": bool(role and role.active),
            "role": "owner" if core.is_owner(user["id"]) else ("trainee" if role and role.active else "user"),
        }


@router.get("/api/finance/workspace/requests")
async def my_requests(
    x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data"),
):
    user = core.verify_init_data(x_telegram_init_data or "")
    with core.SessionLocal() as session:
        _staff_or_forbidden(session, user["id"])
        records = session.scalars(
            select(FinanceDecisionRequest)
            .where(FinanceDecisionRequest.trainee_id == user["id"])
            .order_by(FinanceDecisionRequest.id.desc())
            .limit(60)
        ).all()
        return {"ok": True, "requests": [_serialize(r, session) for r in records]}


@router.post("/api/finance/workspace/requests", status_code=201)
async def submit_request(
    payload: ProposalPayload,
    background_tasks: BackgroundTasks,
    x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data"),
):
    user = core.verify_init_data(x_telegram_init_data or "")
    if core.is_owner(user["id"]):
        raise HTTPException(status_code=403, detail="Владелец не создаёт стажёрские заявки")
    if not TOKEN_PATTERN.fullmatch(payload.request_token):
        raise HTTPException(status_code=422, detail="Некорректный идентификатор заявки")
    if len(payload.reason) < 10:
        raise HTTPException(status_code=422, detail="Укажите причину не короче 10 символов")
    if payload.action == "investigate" and payload.amount != 0:
        raise HTTPException(status_code=422, detail="Для проверки операции сумма должна быть 0")
    if payload.action != "investigate" and payload.amount < 1:
        raise HTTPException(status_code=422, detail="Укажите положительную сумму")
    if payload.action != "investigate" and not (payload.target or "").strip():
        raise HTTPException(status_code=422, detail="Укажите получателя")
    if payload.target and len(payload.target) > 128:
        raise HTTPException(status_code=422, detail="Слишком длинная ссылка на операцию")

    with core.SessionLocal() as session:
        with session.begin():
            _staff_or_forbidden(session, user["id"], lock=True)
            existing = session.scalar(
                select(FinanceDecisionRequest).where(
                    FinanceDecisionRequest.trainee_id == user["id"],
                    FinanceDecisionRequest.request_token == payload.request_token,
                )
            )
            if existing:
                normalized = (payload.target or "").lstrip("@").strip().lower()
                target_match = (
                    (existing.target_reference or "").lstrip("@").strip().lower() == normalized
                    or (existing.target_id is not None and str(existing.target_id) == normalized)
                    or (existing.target_id is not None and (
                        _name(session.get(core.User, existing.target_id)).lstrip("@").lower() == normalized
                    ))
                )
                if (not target_match or existing.action != payload.action
                        or existing.amount != payload.amount or existing.reason != payload.reason
                        or (existing.evidence or None) != (payload.evidence or None)):
                    raise HTTPException(status_code=409, detail="Идентификатор уже использован другой заявкой")
                return {"ok": True, "request": _serialize(existing, session), "already_submitted": True}

            pending = session.scalar(select(func.count()).select_from(FinanceDecisionRequest).where(
                FinanceDecisionRequest.trainee_id == user["id"],
                FinanceDecisionRequest.status == "pending",
            )) or 0
            if pending >= MAX_PENDING_PER_TRAINEE:
                raise HTTPException(status_code=429, detail="Сначала дождитесь решения по предыдущим заявкам")
            day_count = session.scalar(select(func.count()).select_from(FinanceDecisionRequest).where(
                FinanceDecisionRequest.trainee_id == user["id"],
                FinanceDecisionRequest.created_at >= core.now_utc() - timedelta(hours=24),
            )) or 0
            if day_count >= MAX_DAILY_PER_TRAINEE:
                raise HTTPException(status_code=429, detail="Лимит заявок за 24 часа исчерпан")

            target_ref = (payload.target or "").strip()
            target = core.find_target_user(session, target_ref) if target_ref else None
            if payload.action != "investigate":
                if target is None:
                    raise HTTPException(status_code=404, detail="Пользователь не найден в Nyan Wallet")
                if core.is_owner(target.telegram_id):
                    raise HTTPException(status_code=400, detail="Заявки на кошелёк владельца не принимаются")
            # Technical investigations can refer to a transfer ID, an external
            # account or a suspect not yet registered in Nyan Wallet.
            # They must never alter wallet balances.
            record = FinanceDecisionRequest(
                trainee_id=user["id"],
                target_id=target.telegram_id if target is not None else None,
                target_reference=target_ref or None,
                action=payload.action,
                amount=payload.amount,
                reason=payload.reason,
                evidence=payload.evidence or None,
                request_token=payload.request_token,
                status="pending",
                created_at=core.now_utc(),
            )
            session.add(record)
            session.flush()
            response = _serialize(record, session)
    kinds = {"grant": "начисление", "debit": "списание", "investigate": "проверку операции"}
    background_tasks.add_task(
        _send_notification,
        core.OWNER_TELEGRAM_ID,
        f"🐾 Nyan Wallet | На согласование\n"
        f"Стажёр: {user['id']}\n"
        f"Заявка №{response['id']}: {kinds[payload.action]}\n"
        f"Пользователь: {response['target_label']}\n"
        f"Сумма: {payload.amount} 🐾\n"
        f"Основание: {payload.reason[:180]}\n\n"
        "Баланс не изменён до решения владельца",
        button=True,
    )
    return {"ok": True, "request": response, "already_submitted": False}


@router.get("/api/owner/finance/trainees")
async def list_trainees(
    x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data"),
):
    user = core.verify_init_data(x_telegram_init_data or "")
    core.require_owner(user)
    with core.SessionLocal() as session:
        roles = session.scalars(select(FinanceTrainee).order_by(FinanceTrainee.granted_at.desc())).all()
        return {"ok": True, "trainees": [{
            "telegram_id": r.telegram_id,
            "name": _name(session.get(core.User, r.telegram_id)),
            "active": bool(r.active),
            "granted_at": r.granted_at.isoformat(),
        } for r in roles]}


@router.post("/api/owner/finance/trainees/application/{application_id}")
async def appoint_trainee(
    application_id: int,
    background_tasks: BackgroundTasks,
    x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data"),
):
    tg_user = core.verify_init_data(x_telegram_init_data or "")
    core.require_owner(tg_user)
    with core.SessionLocal() as session:
        with session.begin():
            application = session.get(FinancialAdminApplication, application_id)
            if not application:
                raise HTTPException(status_code=404, detail="Анкета кандидата не найдена")
            if application.status == "rejected":
                raise HTTPException(status_code=409, detail="Нельзя назначить отклонённого кандидата")
            trainee_id = application.telegram_id
            if core.is_owner(trainee_id):
                raise HTTPException(status_code=400, detail="Владелец не может быть стажёром")
            if session.get(core.User, trainee_id) is None:
                raise HTTPException(status_code=404, detail="Кошелёк кандидата не найден")
            role = session.scalar(select(FinanceTrainee).where(
                FinanceTrainee.telegram_id == trainee_id
            ).with_for_update())
            if role and role.active:
                raise HTTPException(status_code=409, detail="Этот кандидат уже на стажировке")
            if role is None:
                role = FinanceTrainee(
                    telegram_id=trainee_id, active=True,
                    granted_by=tg_user["id"], granted_at=core.now_utc(),
                )
                session.add(role)
            else:
                role.active = True
                role.revoked_at = None
                role.granted_at = core.now_utc()
                role.granted_by = tg_user["id"]
            audit(session, "finance_trainee_appointed", trainee_id, f"Анкета №{application_id}")
    background_tasks.add_task(
        _send_notification, trainee_id,
        "🐾 Nyan Wallet\nТебе открыт доступ к стажировке финансовой администрации. "
        "В профиле кошелька появился раздел «Управление финансами». "
        "Все заявки отправляются владельцу на проверку, самостоятельно менять балансы нельзя.",
        button=True,
    )
    return {"ok": True, "trainee_id": trainee_id, "active": True}


@router.post("/api/owner/finance/trainees/{telegram_id}/revoke")
async def revoke_trainee(
    telegram_id: int,
    background_tasks: BackgroundTasks,
    x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data"),
):
    tg_user = core.verify_init_data(x_telegram_init_data or "")
    core.require_owner(tg_user)
    with core.SessionLocal() as session:
        with session.begin():
            role = session.scalar(select(FinanceTrainee).where(
                FinanceTrainee.telegram_id == telegram_id
            ).with_for_update())
            if not role or not role.active:
                raise HTTPException(status_code=404, detail="Активная стажировка не найдена")
            role.active = False
            role.revoked_at = core.now_utc()
            audit(session, "finance_trainee_revoked", telegram_id, "Доступ отключён владельцем")
    background_tasks.add_task(
        _send_notification, telegram_id,
        "🐾 Nyan Wallet\nДоступ к стажёрской панели финансовой администрации закрыт. "
        "Ожидающие решения заявки останутся на рассмотрении владельца.",
    )
    return {"ok": True, "trainee_id": telegram_id, "active": False}


@router.get("/api/owner/finance/requests")
async def owner_requests(
    status: Literal["pending", "approved", "rejected", "all"] = Query(default="pending"),
    x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data"),
):
    tg_user = core.verify_init_data(x_telegram_init_data or "")
    core.require_owner(tg_user)
    with core.SessionLocal() as session:
        query = select(FinanceDecisionRequest).order_by(FinanceDecisionRequest.id.desc()).limit(150)
        if status != "all":
            query = query.where(FinanceDecisionRequest.status == status)
        records = session.scalars(query).all()
        return {"ok": True, "requests": [
            _serialize(record, session, include_trainee=True) for record in records
        ]}


@router.post("/api/owner/finance/requests/{request_id}/decision")
async def decide_request(
    request_id: int,
    payload: DecisionPayload,
    background_tasks: BackgroundTasks,
    x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data"),
):
    tg_user = core.verify_init_data(x_telegram_init_data or "")
    core.require_owner(tg_user)
    if payload.decision == "reject" and not payload.note:
        raise HTTPException(status_code=422, detail="Укажите причину отказа")
    with core.SessionLocal() as session:
        with session.begin():
            record = session.scalar(
                select(FinanceDecisionRequest).where(
                    FinanceDecisionRequest.id == request_id
                ).with_for_update()
            )
            if record is None:
                raise HTTPException(status_code=404, detail="Заявка не найдена")
            if record.status != "pending":
                raise HTTPException(status_code=409, detail="Заявка уже рассмотрена")
            transaction = None
            if payload.decision == "approve":
                _staff_or_forbidden(session, record.trainee_id)
                if record.action in ("grant", "debit"):
                    target = session.scalar(select(core.User).where(
                        core.User.telegram_id == record.target_id
                    ).with_for_update())
                    if target is None:
                        raise HTTPException(status_code=404, detail="Получатель больше не существует")
                    if core.is_owner(target.telegram_id):
                        raise HTTPException(status_code=400, detail="Баланс владельца нельзя изменять")
                    if record.amount <= 0 or record.amount > MAX_AMOUNT:
                        raise HTTPException(status_code=422, detail="Некорректная сумма заявки")
                    delta = record.amount if record.action == "grant" else -record.amount
                    if target.balance + delta < 0:
                        raise HTTPException(
                            status_code=409,
                            detail=f"Недостаточно лапкоинов для списания. Текущий баланс: {target.balance} 🐾",
                        )
                    target.balance += delta
                    transaction = core.Transaction(
                        telegram_id=target.telegram_id,
                        amount=delta,
                        operation_type="owner_grant" if delta > 0 else "owner_debit",
                        description=f"{record.reason} (стажёрская заявка №{record.id})",
                        created_at=core.now_utc(),
                    )
                    session.add(transaction)
                    session.flush()
                    record.transaction_id = transaction.id
                elif record.action != "investigate":
                    raise HTTPException(status_code=422, detail="Неподдерживаемый тип заявки")
            record.status = "approved" if payload.decision == "approve" else "rejected"
            record.decided_at = core.now_utc()
            record.decided_by = tg_user["id"]
            record.owner_note = payload.note
            audit(
                session,
                "finance_trainee_approved" if payload.decision == "approve" else "finance_trainee_rejected",
                record.target_id,
                f"Заявка №{record.id}, стажёр {record.trainee_id}, "
                f"{record.action}, {record.amount} 🐾, транзакция {record.transaction_id or 'нет'}",
            )
            response = _serialize(record, session, include_trainee=True)
    verdict = "одобрена" if payload.decision == "approve" else "отклонена"
    detail = (
        "Начисление/списание проведено после подтверждения владельца."
        if payload.decision == "approve" and response["transaction_id"] else
        "Это было согласование проверки, баланс пользователя не изменился."
        if payload.decision == "approve" else
        "Баланс пользователя не изменился."
    )
    background_tasks.add_task(
        _send_notification, record.trainee_id,
        f"🐾 Nyan Wallet | Заявка №{request_id} {verdict}\n"
        f"{detail}\n"
        + (f"Комментарий владельца: {payload.note}" if payload.note else ""),
        button=True,
    )
    return {"ok": True, "request": response}


def register_finance_workspace(app) -> None:
    global _REGISTERED
    if _REGISTERED:
        return
    FinanceTrainee.__table__.create(bind=core.engine, checkfirst=True)
    FinanceDecisionRequest.__table__.create(bind=core.engine, checkfirst=True)
    FinanceTelegramDelivery.__table__.create(bind=core.engine, checkfirst=True)
    # Backward-compatible migration for requests created before technical
    # investigations were allowed without a known wallet user.
    if core.engine.dialect.name == "postgresql":
        with core.engine.begin() as connection:
            connection.exec_driver_sql(
                "ALTER TABLE finance_decision_requests ALTER COLUMN target_id DROP NOT NULL"
            )
            connection.exec_driver_sql(
                "ALTER TABLE finance_decision_requests ADD COLUMN IF NOT EXISTS target_reference VARCHAR(128)"
            )
    app.include_router(router)
    _REGISTERED = True
