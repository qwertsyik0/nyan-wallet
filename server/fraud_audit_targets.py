from __future__ import annotations

import json
from collections import defaultdict
from datetime import timedelta

from sqlalchemy import func, or_, select

from . import backend_app as core
from .transfers import WalletTransfer

TARGETS = ("zumiexx", "lolitqq_a", "Margarylo")


def _label(user: core.User | None, fallback: int | None = None) -> str:
    if user is None:
        return str(fallback or "")
    if user.username:
        return "@" + user.username
    return (user.first_name or str(user.telegram_id)).strip()


def audit_target_accounts() -> None:
    with core.SessionLocal() as session:
        users = session.scalars(
            select(core.User).where(
                func.lower(core.User.username).in_([name.lower() for name in TARGETS])
            )
        ).all()

        user_by_id = {int(u.telegram_id): u for u in users}
        ids = sorted(user_by_id)
        print("[fraud_audit] targets=" + json.dumps([
            {
                "username": u.username,
                "telegram_id": int(u.telegram_id),
                "balance": int(u.balance),
                "created_at": u.created_at.isoformat(),
                "last_seen_at": u.last_seen_at.isoformat(),
            }
            for u in users
        ], ensure_ascii=False))

        if not ids:
            print("[fraud_audit] no_target_accounts_found")
            return

        redemptions = session.execute(
            select(core.PromoRedemption, core.PromoCode)
            .join(core.PromoCode, core.PromoCode.id == core.PromoRedemption.promo_id)
            .where(core.PromoRedemption.telegram_id.in_(ids))
            .order_by(core.PromoRedemption.created_at.asc())
        ).all()

        red_by_user: dict[int, list[tuple[core.PromoRedemption, core.PromoCode]]] = defaultdict(list)
        for redemption, promo in redemptions:
            red_by_user[int(redemption.telegram_id)].append((redemption, promo))

        for uid in ids:
            u = user_by_id[uid]
            data = [
                {
                    "code": promo.code,
                    "amount": int(red.reward_amount),
                    "created_at": red.created_at.isoformat(),
                }
                for red, promo in red_by_user.get(uid, [])
            ]
            print("[fraud_audit_promos] " + json.dumps({
                "user": _label(u),
                "count": len(data),
                "total": sum(x["amount"] for x in data),
                "items": data,
            }, ensure_ascii=False))

        transfers = session.scalars(
            select(WalletTransfer)
            .where(or_(WalletTransfer.sender_id.in_(ids), WalletTransfer.recipient_id.in_(ids)))
            .order_by(WalletTransfer.created_at.asc())
        ).all()

        other_ids = sorted({
            int(t.sender_id) for t in transfers
        } | {
            int(t.recipient_id) for t in transfers
        })
        others = {
            int(u.telegram_id): u
            for u in session.scalars(
                select(core.User).where(core.User.telegram_id.in_(other_ids))
            ).all()
        }

        for t in transfers:
            print("[fraud_audit_transfer] " + json.dumps({
                "created_at": t.created_at.isoformat(),
                "sender": _label(others.get(int(t.sender_id)), int(t.sender_id)),
                "recipient": _label(others.get(int(t.recipient_id)), int(t.recipient_id)),
                "amount": int(t.amount),
                "note": t.note,
                "public_id": t.public_id,
            }, ensure_ascii=False))

        # Income source breakdown and timeline for each target.
        for uid in ids:
            u = user_by_id[uid]
            breakdown = session.execute(
                select(
                    core.Transaction.operation_type,
                    func.count(core.Transaction.id),
                    func.sum(core.Transaction.amount),
                )
                .where(
                    core.Transaction.telegram_id == uid,
                    core.Transaction.amount > 0,
                )
                .group_by(core.Transaction.operation_type)
                .order_by(func.sum(core.Transaction.amount).desc())
            ).all()
            print("[fraud_audit_income] " + json.dumps({
                "user": _label(u),
                "items": [
                    {
                        "type": op,
                        "count": int(n),
                        "total": int(total or 0),
                    }
                    for op, n, total in breakdown
                ],
            }, ensure_ascii=False))

            positive = session.scalars(
                select(core.Transaction)
                .where(
                    core.Transaction.telegram_id == uid,
                    core.Transaction.amount > 0,
                )
                .order_by(core.Transaction.created_at.asc())
            ).all()
            for tx in positive:
                print("[fraud_audit_income_item] " + json.dumps({
                    "user": _label(u),
                    "created_at": tx.created_at.isoformat(),
                    "type": tx.operation_type,
                    "amount": int(tx.amount),
                    "description": tx.description,
                }, ensure_ascii=False))

        # Same recipient aggregation for the suspect accounts as senders.
        grouped = session.execute(
            select(
                WalletTransfer.sender_id,
                WalletTransfer.recipient_id,
                func.count(WalletTransfer.id),
                func.sum(WalletTransfer.amount),
            )
            .where(WalletTransfer.sender_id.in_(ids))
            .group_by(WalletTransfer.sender_id, WalletTransfer.recipient_id)
            .order_by(func.sum(WalletTransfer.amount).desc())
        ).all()
        for sender_id, recipient_id, n, amount in grouped:
            print("[fraud_audit_flow] " + json.dumps({
                "sender": _label(others.get(int(sender_id)), int(sender_id)),
                "recipient": _label(others.get(int(recipient_id)), int(recipient_id)),
                "count": int(n),
                "total": int(amount or 0),
            }, ensure_ascii=False))

        # Promo -> outgoing transfer windows: 15m, 1h, 24h after each redemption.
        suspect_outgoing = [t for t in transfers if int(t.sender_id) in ids]
        for uid in ids:
            user = user_by_id[uid]
            for red, promo in red_by_user.get(uid, []):
                after = [
                    t for t in suspect_outgoing
                    if int(t.sender_id) == uid
                    and t.created_at >= red.created_at
                    and t.created_at <= red.created_at + timedelta(hours=24)
                ]
                if not after:
                    continue
                first = min(after, key=lambda t: t.created_at)
                delta = (first.created_at - red.created_at).total_seconds()
                print("[fraud_audit_promo_to_transfer] " + json.dumps({
                    "user": _label(user),
                    "promo": promo.code,
                    "promo_amount": int(red.reward_amount),
                    "promo_at": red.created_at.isoformat(),
                    "first_transfer_at": first.created_at.isoformat(),
                    "seconds_after": int(delta),
                    "recipient": _label(others.get(int(first.recipient_id)), int(first.recipient_id)),
                    "amount": int(first.amount),
                    "within_15m": delta <= 900,
                    "within_1h": delta <= 3600,
                }, ensure_ascii=False))

        # Strong signal: multiple targets funneling to the same recipient.
        recipient_senders: dict[int, set[int]] = defaultdict(set)
        recipient_total: dict[int, int] = defaultdict(int)
        for t in suspect_outgoing:
            recipient_senders[int(t.recipient_id)].add(int(t.sender_id))
            recipient_total[int(t.recipient_id)] += int(t.amount)

        for recipient_id, senders in recipient_senders.items():
            if len(senders) >= 2:
                print("[fraud_audit_common_recipient] " + json.dumps({
                    "recipient": _label(others.get(recipient_id), recipient_id),
                    "senders": sorted(_label(user_by_id.get(uid), uid) for uid in senders),
                    "total": recipient_total[recipient_id],
                }, ensure_ascii=False))
