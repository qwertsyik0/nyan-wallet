"""One-time owner-requested trainee access for a specific existing Nyan Wallet user.

This is deliberately NOT a public API endpoint or a general ID-based role grant.
Remove the startup call after the first verified deployment.
"""
from __future__ import annotations

import logging

from sqlalchemy import select

from . import backend_app as core
from .extended_features import AdminAudit
from .finance_workspace import FinanceTrainee

log = logging.getLogger("nyan_wallet.finance_test_grant_20261016")
TARGET_ID = 8252951161
AUDIT_ACTION = "finance_test_trainee_access_20261016"


def grant_specific_test_account_once() -> None:
    with core.SessionLocal() as session:
        with session.begin():
            target = session.scalar(
                select(core.User)
                .where(core.User.telegram_id == TARGET_ID)
                .with_for_update()
            )
            if target is None:
                log.error("FINANCE_TEST_GRANT target_not_registered telegram_id=%s", TARGET_ID)
                return
            if core.is_owner(TARGET_ID):
                log.error("FINANCE_TEST_GRANT refused_owner")
                return

            role = session.scalar(
                select(FinanceTrainee)
                .where(FinanceTrainee.telegram_id == TARGET_ID)
                .with_for_update()
            )
            if role is not None and role.active:
                log.warning("FINANCE_TEST_GRANT already_active telegram_id=%s", TARGET_ID)
                return

            timestamp = core.now_utc()
            if role is None:
                session.add(FinanceTrainee(
                    telegram_id=TARGET_ID,
                    active=True,
                    granted_by=core.OWNER_TELEGRAM_ID,
                    granted_at=timestamp,
                    revoked_at=None,
                ))
            else:
                role.active = True
                role.granted_by = core.OWNER_TELEGRAM_ID
                role.granted_at = timestamp
                role.revoked_at = None
            session.add(AdminAudit(
                action=AUDIT_ACTION,
                target_telegram_id=TARGET_ID,
                details="Owner-requested temporary trainee access for own second account; no financial approvals",
                created_at=timestamp,
            ))
        log.warning("FINANCE_TEST_GRANT success telegram_id=%s role=trainee", TARGET_ID)
