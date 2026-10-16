"""Read-only one-off production verification requested by Nyan Wallet owner.

No mutation, no user-facing API, and no financial side effects.
Remove bootstrap after first verified log.
"""
import logging
from datetime import timedelta
from sqlalchemy import select

from . import backend_app as core
from .finance_workspace import FinanceDecisionRequest, FinanceTrainee
from .advanced_features import WalletNotification

log = logging.getLogger("nyan_wallet.finance_verify_20261016")


def audit_finance_one_time():
    try:
        with core.SessionLocal() as session:
            for uid in (1129986805, 8252951161):
                role = session.get(FinanceTrainee, uid)
                log.warning(
                    "FINANCE_LIVE_AUDIT staff=%s active=%s",
                    uid,
                    bool(role and role.active),
                )
            request = session.get(FinanceDecisionRequest, 1)
            if request is None:
                log.warning("FINANCE_LIVE_AUDIT request_1_missing")
                return
            tx = session.get(core.Transaction, request.transaction_id) if request.transaction_id else None
            balance = session.get(core.User, request.target_id) if request.target_id else None
            note = None
            if tx is not None:
                note = session.scalar(
                    select(WalletNotification.id).where(
                        WalletNotification.telegram_id == tx.telegram_id,
                        WalletNotification.kind == tx.operation_type,
                        WalletNotification.created_at >= tx.created_at - timedelta(seconds=1),
                        WalletNotification.created_at <= tx.created_at + timedelta(seconds=1),
                    ).limit(1)
                )
            log.warning(
                "FINANCE_LIVE_AUDIT request=1 status=%s action=%s amount=%s "
                "has_transaction=%s transaction_amount=%s in_app_notification=%s "
                "wallet_balance=%s",
                request.status,
                request.action,
                request.amount,
                bool(tx is not None),
                tx.amount if tx is not None else None,
                bool(note is not None),
                balance.balance if balance is not None else None,
            )
    except Exception:
        log.exception("FINANCE_LIVE_AUDIT unexpected error")
