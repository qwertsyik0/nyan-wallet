"""One-time owner-authorized access for candidate #2 @nasttchl.

Do not use as a public endpoint. Remove startup hook after verified execution.
No grant occurs unless application #2 matches the specified username.
"""
from __future__ import annotations
import logging
from sqlalchemy import select
from . import backend_app as core
from .finance_recruitment import FinancialAdminApplication
from .finance_workspace import FinanceTrainee
from .extended_features import audit

log = logging.getLogger("nyan_wallet.finance_nastya_20261016")
EXPECTED_APPLICATION_ID = 2
EXPECTED_USERNAME = "nasttchl"

def appoint_verified_nastya_once():
    with core.SessionLocal() as session:
        with session.begin():
            application = session.scalar(
                select(FinancialAdminApplication)
                .where(FinancialAdminApplication.id == EXPECTED_APPLICATION_ID)
                .with_for_update()
            )
            if application is None:
                log.error("FINANCE_NASTYA no_application id=%s", EXPECTED_APPLICATION_ID)
                return
            user = session.scalar(
                select(core.User)
                .where(core.User.telegram_id == application.telegram_id)
            )
            if user is None:
                log.error("FINANCE_NASTYA no_wallet_user application=2")
                return
            if (user.username or "").casefold().lstrip("@") != EXPECTED_USERNAME:
                log.error("FINANCE_NASTYA username_mismatch application=2 current=%s", user.username)
                return
            if application.status == "rejected" or core.is_owner(user.telegram_id):
                log.error("FINANCE_NASTYA refused status=%s", application.status)
                return
            role = session.scalar(
                select(FinanceTrainee)
                .where(FinanceTrainee.telegram_id == user.telegram_id)
                .with_for_update()
            )
            if role is not None and role.active:
                log.warning("FINANCE_NASTYA already_active telegram_id=%s", user.telegram_id)
                return
            timestamp = core.now_utc()
            if role is None:
                session.add(FinanceTrainee(
                    telegram_id=user.telegram_id,
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
            audit(session, "finance_trainee_appointed", user.telegram_id,
                  "Owner-approved internship for @nasttchl, candidate #2")
            log.warning("FINANCE_NASTYA assigned telegram_id=%s username=@nasttchl", user.telegram_id)
