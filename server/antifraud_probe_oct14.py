from __future__ import annotations

"""Temporary READ ONLY account-pair analysis, prints to owner-visible Render logs."""

def probe() -> None:
    from sqlalchemy import select, func, or_
    from . import backend_app as core
    from .advanced_features import Referral
    from .transfers import WalletTransfer
    from .user_bans import BlockedUser

    prefix = "[AFPAIR_20261014]"
    def out(kind, **data):
        parts = " ".join(f"{key}={value!r}" for key, value in data.items())
        print(f"{prefix} {kind} {parts}", flush=True)

    try:
        with core.SessionLocal() as session:
            wanted = ("grommovvvv", "ad_15_03")
            people = session.scalars(
                select(core.User).where(func.lower(core.User.username).in_(wanted))
            ).all()
            by_username = {str(u.username or "").lower(): u for u in people}
            for name in wanted:
                u = by_username.get(name)
                if not u:
                    out("USER_MISSING", username=name)
                    continue
                ban = session.get(BlockedUser, int(u.telegram_id))
                out("USER", username=u.username, id=u.telegram_id, balance=u.balance,
                    created_at=u.created_at, last_seen=u.last_seen_at,
                    blocked=bool(ban), ban_reason=ban.reason if ban else None)

            if len(by_username) != 2:
                out("INCOMPLETE", reason="Not both usernames resolved exactly")
                return

            first = by_username["grommovvvv"]
            second = by_username["ad_15_03"]
            ids = [int(first.telegram_id), int(second.telegram_id)]
            referrals = session.scalars(
                select(Referral).where(
                    Referral.inviter_id.in_(ids), Referral.invited_id.in_(ids)
                )
            ).all()
            for row in referrals:
                out("REF", inviter_id=row.inviter_id, invited_id=row.invited_id,
                    inviter_reward=row.inviter_reward, invited_reward=row.invited_reward,
                    created_at=row.created_at)
            if not referrals:
                out("NO_DIRECT_REFERRAL")

            transfers = session.scalars(
                select(WalletTransfer).where(
                    or_(
                        (WalletTransfer.sender_id == ids[0]) & (WalletTransfer.recipient_id == ids[1]),
                        (WalletTransfer.sender_id == ids[1]) & (WalletTransfer.recipient_id == ids[0])
                    )
                ).order_by(WalletTransfer.created_at.asc(), WalletTransfer.id.asc()).limit(100)
            ).all()
            out("TRANSFER_SUMMARY", count=len(transfers),
                from_grom_to_ad=sum(t.amount for t in transfers if t.sender_id == ids[0]),
                from_ad_to_grom=sum(t.amount for t in transfers if t.sender_id == ids[1]),
                truncated=(len(transfers) == 100))
            for t in transfers:
                out("TRANSFER", id=t.id, sender_id=t.sender_id, recipient_id=t.recipient_id,
                    amount=t.amount, created_at=t.created_at, note=t.note)

            promos = session.execute(
                select(core.PromoRedemption.telegram_id, core.PromoCode.code,
                    core.PromoRedemption.reward_amount, core.PromoRedemption.created_at)
                .join(core.PromoCode, core.PromoCode.id == core.PromoRedemption.promo_id)
                .where(core.PromoRedemption.telegram_id.in_(ids))
                .order_by(core.PromoRedemption.created_at.asc())
                .limit(100)
            ).all()
            for p in promos:
                out("PROMO", id=p.telegram_id, code=p.code, reward=p.reward_amount, at=p.created_at)

            txs = session.scalars(
                select(core.Transaction)
                .where(core.Transaction.telegram_id.in_(ids),
                       core.Transaction.operation_type.in_(["owner_debit","referral_inviter",
                           "referral_invitee","transfer_in","transfer_out"]))
                .order_by(core.Transaction.created_at.desc())
                .limit(35)
            ).all()
            for tx in txs:
                out("TX", id=tx.telegram_id, amount=tx.amount, type=tx.operation_type,
                    description=(tx.description or "")[:150], at=tx.created_at)
            out("DONE", people=len(people), transfers=len(transfers), promos=len(promos), operations=len(txs))
    except Exception as exc:
        out("ERROR", error=type(exc).__name__, message=str(exc)[:180])
