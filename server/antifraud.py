from __future__ import annotations

"""Read-only owner antifraud signals. Indicators are not proof of shared identity."""

from collections import Counter, defaultdict
from datetime import datetime, timezone

from fastapi import APIRouter, Header, HTTPException, Query
from sqlalchemy import func, or_, select

from . import backend_app as core
from .advanced_features import Referral
from .transfers import WalletTransfer
from .user_bans import BlockedUser

router = APIRouter()
_REGISTERED = False
SCAN_LIMIT = 1500
RESULT_LIMIT = 80


def owner_auth(init_data: str | None) -> None:
    tg = core.verify_init_data(init_data or "")
    core.require_owner(tg)


def iso(value):
    return value.isoformat() if value is not None else None


def person(user):
    if user is None:
        return None
    return {
        "telegram_id": int(user.telegram_id),
        "username": user.username,
        "first_name": user.first_name,
        "balance": int(user.balance),
        "created_at": iso(user.created_at),
    }


def transfer_row(row):
    return {
        "id": int(row.id),
        "sender_id": int(row.sender_id),
        "recipient_id": int(row.recipient_id),
        "amount": int(row.amount),
        "created_at": iso(row.created_at),
        "note": row.note,
    }


def risk_for(*, linked, promo_count, amount, senders_to_recipient):
    # Scoring is for manual triage only, never for automatic penalties.
    score = (4 if linked else 0) + (2 if promo_count >= 2 else 0)
    score += (1 if amount >= 200 else 0)
    score += (3 if senders_to_recipient >= 2 else 0)
    if score >= 7:
        level = "high"
    elif score >= 4:
        level = "medium"
    else:
        level = "low"
    return score, level


@router.get("/api/owner/antifraud/cases")
async def antifraud_cases(
    x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data"),
):
    owner_auth(x_telegram_init_data)
    with core.SessionLocal() as session:
        # Bounded scan: newest transfers first. The UI discloses this coverage.
        rows = session.scalars(
            select(WalletTransfer)
            .order_by(WalletTransfer.created_at.desc(), WalletTransfer.id.desc())
            .limit(SCAN_LIMIT)
        ).all()
        if not rows:
            return {
                "ok": True, "cases": [], "scanned_transfers": 0,
                "scan_limit": SCAN_LIMIT, "truncated": False,
                "scope": "last_transfers", "total_candidates": 0,
            }

        ids = {int(t.sender_id) for t in rows} | {int(t.recipient_id) for t in rows}
        ref_rows = session.scalars(
            select(Referral).where(
                Referral.inviter_id.in_(ids),
                Referral.invited_id.in_(ids),
            )
        ).all()
        ref_by_pair = {(int(r.inviter_id), int(r.invited_id)): r for r in ref_rows}

        # Only senders in this sample need promo totals.
        senders = {int(t.sender_id) for t in rows}
        promo_totals = {
            int(uid): (int(count), int(amount))
            for uid, count, amount in session.execute(
                select(
                    core.PromoRedemption.telegram_id,
                    func.count(core.PromoRedemption.id),
                    func.coalesce(func.sum(core.PromoRedemption.reward_amount), 0),
                )
                .where(core.PromoRedemption.telegram_id.in_(senders))
                .group_by(core.PromoRedemption.telegram_id)
            )
        }

        grouped = defaultdict(list)
        receivers = defaultdict(set)
        for item in rows:
            sender_id, recipient_id = int(item.sender_id), int(item.recipient_id)
            if sender_id == recipient_id or core.is_owner(sender_id) or core.is_owner(recipient_id):
                continue
            grouped[(sender_id, recipient_id)].append(item)
            receivers[recipient_id].add(sender_id)

        flagged = []
        for (sender_id, recipient_id), transfers in grouped.items():
            ref = ref_by_pair.get((recipient_id, sender_id))
            promo_count, promo_amount = promo_totals.get(sender_id, (0, 0))
            sender_count = len(receivers[recipient_id])
            # A simple transfer or a referral alone is NOT suspicious.
            if ref is None and not (sender_count >= 2 and promo_count >= 2):
                continue

            total = sum(int(t.amount) for t in transfers)
            score, level = risk_for(
                linked=ref is not None,
                promo_count=promo_count,
                amount=total,
                senders_to_recipient=sender_count,
            )
            if level == "low":
                continue

            reasons = []
            if ref is not None:
                reasons.append("Получатель пригласил отправителя по реферальной программе")
            if promo_count >= 2:
                reasons.append(f"Отправитель активировал {promo_count} промокодов (+{promo_amount} 🐾)")
            if sender_count >= 2:
                reasons.append(f"Получатель получал переводы от {sender_count} аккаунтов в выборке")
            if total >= 200:
                reasons.append(f"Получателю переведено {total} 🐾 в выборке")

            flagged.append({
                "sender_id": sender_id,
                "recipient_id": recipient_id,
                "referral_id": int(ref.id) if ref else None,
                "promo_count": promo_count,
                "promo_amount": promo_amount,
                "transfer_count": len(transfers),
                "transfer_total": total,
                "last_transfer_at": iso(max(t.created_at for t in transfers)),
                "risk_score": score,
                "risk_level": level,
                "reasons": reasons,
            })

        flagged.sort(key=lambda c: (-c["risk_score"], -c["transfer_total"], c["recipient_id"], c["sender_id"]))
        total_candidates = len(flagged)
        flagged = flagged[:RESULT_LIMIT]
        needed_ids = {id for case in flagged for id in (case["sender_id"], case["recipient_id"])}
        people = {
            int(user.telegram_id): user
            for user in session.scalars(
                select(core.User).where(core.User.telegram_id.in_(needed_ids))
            ).all()
        } if needed_ids else {}
        banned = {
            int(uid) for uid in session.scalars(
                select(BlockedUser.telegram_id).where(BlockedUser.telegram_id.in_(needed_ids))
            ).all()
        } if needed_ids else set()
        for case in flagged:
            case["sender"] = person(people.get(case["sender_id"]))
            case["recipient"] = person(people.get(case["recipient_id"]))
            case["sender_banned"] = case["sender_id"] in banned
            case["recipient_banned"] = case["recipient_id"] in banned

        return {
            "ok": True,
            "cases": flagged,
            "scanned_transfers": len(rows),
            "scan_limit": SCAN_LIMIT,
            "truncated": len(rows) == SCAN_LIMIT or total_candidates > RESULT_LIMIT,
            "scope": "last_transfers",
            "total_candidates": total_candidates,
        }


@router.get("/api/owner/antifraud/pair/{sender_id}/{recipient_id}")
async def antifraud_pair(
    sender_id: int,
    recipient_id: int,
    x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data"),
):
    owner_auth(x_telegram_init_data)
    if sender_id <= 0 or recipient_id <= 0 or sender_id == recipient_id:
        raise HTTPException(status_code=400, detail="Некорректная пара аккаунтов")

    with core.SessionLocal() as session:
        users = {int(u.telegram_id): u for u in session.scalars(
            select(core.User).where(core.User.telegram_id.in_([sender_id, recipient_id]))
        ).all()}
        if sender_id not in users or recipient_id not in users:
            raise HTTPException(status_code=404, detail="Аккаунт не найден")

        ref = session.scalar(
            select(Referral).where(
                Referral.inviter_id == recipient_id, Referral.invited_id == sender_id
            )
        )
        transfers = session.scalars(
            select(WalletTransfer)
            .where(
                WalletTransfer.sender_id == sender_id,
                WalletTransfer.recipient_id == recipient_id,
            )
            .order_by(WalletTransfer.created_at.desc(), WalletTransfer.id.desc())
            .limit(100)
        ).all()

        promo_rows = session.execute(
            select(
                core.PromoCode.code,
                core.PromoRedemption.reward_amount,
                core.PromoRedemption.created_at,
            )
            .join(core.PromoCode, core.PromoCode.id == core.PromoRedemption.promo_id)
            .where(core.PromoRedemption.telegram_id == sender_id)
            .order_by(core.PromoRedemption.created_at.desc())
            .limit(50)
        ).all()

        # Separate operation summaries help check prior sanctions and
        # earned balances without leaking data to non-owners.
        transactions = session.scalars(
            select(core.Transaction)
            .where(
                core.Transaction.telegram_id.in_([sender_id, recipient_id]),
                core.Transaction.operation_type.in_([
                    "owner_debit", "referral_invitee", "referral_inviter",
                    "transfer_in", "transfer_out",
                ]),
            )
            .order_by(core.Transaction.created_at.desc(), core.Transaction.id.desc())
            .limit(80)
        ).all()
        bans = {
            int(b.telegram_id): {"reason": b.reason, "blocked_at": iso(b.blocked_at)}
            for b in session.scalars(
                select(BlockedUser).where(BlockedUser.telegram_id.in_([sender_id, recipient_id]))
            ).all()
        }
        return {
            "ok": True,
            "sender": person(users[sender_id]),
            "recipient": person(users[recipient_id]),
            "sender_ban": bans.get(sender_id),
            "recipient_ban": bans.get(recipient_id),
            "referral": {
                "id": int(ref.id),
                "inviter_reward": int(ref.inviter_reward),
                "invited_reward": int(ref.invited_reward),
                "created_at": iso(ref.created_at),
            } if ref else None,
            "transfers": [transfer_row(t) for t in transfers],
            "transfer_total_in_history": sum(int(t.amount) for t in transfers),
            "transfers_truncated": len(transfers) == 100,
            "promos": [
                {"code": code, "amount": int(amount), "created_at": iso(at)}
                for code, amount, at in promo_rows
            ],
            "promos_truncated": len(promo_rows) == 50,
            "operations": [
                {
                    "telegram_id": int(t.telegram_id),
                    "amount": int(t.amount),
                    "type": t.operation_type,
                    "description": t.description,
                    "created_at": iso(t.created_at),
                } for t in transactions
            ],
            "operations_truncated": len(transactions) == 80,
            "ip_comparison_available": False,
            "note": "Совпадение IP/устройства не устанавливается. Сигналы требуют ручной проверки.",
        }


def register_antifraud(app) -> None:
    global _REGISTERED
    if _REGISTERED:
        return
    app.include_router(router)
    _REGISTERED = True
