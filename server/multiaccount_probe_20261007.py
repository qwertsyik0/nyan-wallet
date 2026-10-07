from __future__ import annotations

import logging

from sqlalchemy import or_, select

from server import backend_app as core
from server.advanced_features import Referral
from server.transfers import WalletTransfer

logger = logging.getLogger("nyan_wallet.multiaccount_probe")
MARKER = "MULTIACCOUNT_PROBE_20261007"
TARGETS = ("Verenush12", "BlaineT_R", "mirak_off")


def run_multiaccount_probe_20261007() -> None:
    """One-shot read-only diagnostic for three owner-requested accounts."""
    with core.SessionLocal() as session:
        users = session.scalars(
            select(core.User).where(
                or_(*[core.func.lower(core.User.username) == name.lower() for name in TARGETS])
            )
        ).all()

        by_id = {int(user.telegram_id): user for user in users}
        logger.warning("%s users_found=%s", MARKER, len(users))

        for user in users:
            uid = int(user.telegram_id)
            logger.warning(
                "%s USER username=%s telegram_id=%s balance=%s created_at=%s last_seen_at=%s",
                MARKER,
                user.username,
                uid,
                user.balance,
                user.created_at.isoformat() if user.created_at else None,
                user.last_seen_at.isoformat() if user.last_seen_at else None,
            )

            promo_rows = session.execute(
                select(core.PromoRedemption, core.PromoCode)
                .join(core.PromoCode, core.PromoCode.id == core.PromoRedemption.promo_id)
                .where(core.PromoRedemption.telegram_id == uid)
                .order_by(core.PromoRedemption.created_at.asc())
            ).all()
            for redemption, promo in promo_rows:
                logger.warning(
                    "%s PROMO telegram_id=%s code=%s reward=%s created_at=%s",
                    MARKER,
                    uid,
                    promo.code,
                    redemption.reward_amount,
                    redemption.created_at.isoformat() if redemption.created_at else None,
                )

            txs = session.scalars(
                select(core.Transaction)
                .where(core.Transaction.telegram_id == uid)
                .order_by(core.Transaction.created_at.desc())
                .limit(80)
            ).all()
            for tx in reversed(txs):
                logger.warning(
                    "%s TX telegram_id=%s amount=%s type=%s description=%s created_at=%s",
                    MARKER,
                    uid,
                    tx.amount,
                    tx.operation_type,
                    (tx.description or "").replace("\n", " ")[:180],
                    tx.created_at.isoformat() if tx.created_at else None,
                )

        ids = list(by_id)
        if ids:
            transfers = session.scalars(
                select(WalletTransfer)
                .where(or_(WalletTransfer.sender_id.in_(ids), WalletTransfer.recipient_id.in_(ids)))
                .order_by(WalletTransfer.created_at.asc())
                .limit(200)
            ).all()
            for tr in transfers:
                logger.warning(
                    "%s TRANSFER id=%s sender_id=%s recipient_id=%s amount=%s created_at=%s note=%s",
                    MARKER,
                    tr.public_id,
                    tr.sender_id,
                    tr.recipient_id,
                    tr.amount,
                    tr.created_at.isoformat() if tr.created_at else None,
                    (tr.note or "").replace("\n", " ")[:120],
                )

            refs = session.scalars(
                select(Referral)
                .where(or_(Referral.inviter_id.in_(ids), Referral.invited_id.in_(ids)))
                .order_by(Referral.created_at.asc())
                .limit(100)
            ).all()
            for ref in refs:
                logger.warning(
                    "%s REFERRAL inviter_id=%s invited_id=%s inviter_reward=%s invited_reward=%s created_at=%s",
                    MARKER,
                    ref.inviter_id,
                    ref.invited_id,
                    ref.inviter_reward,
                    ref.invited_reward,
                    ref.created_at.isoformat() if ref.created_at else None,
                )
