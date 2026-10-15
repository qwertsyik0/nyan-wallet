"""Read-only, one-time review of finance stage two for application #4."""
import json
import logging
from sqlalchemy import select
from . import backend_app as core
from .finance_recruitment import FinancialAdminApplication
from .finance_stage2 import FinanceStage2Response, FinanceStage2Invitation

log = logging.getLogger("nyan_wallet.finance_vlad_review")
MARK = "[VLAD_STAGE2_REVIEW_20261015]"

def inspect_candidate_four():
    try:
        with core.SessionLocal() as session:
            application = session.get(FinancialAdminApplication, 4)
            invitation = session.get(FinanceStage2Invitation, 4)
            response = session.scalar(select(FinanceStage2Response).where(FinanceStage2Response.application_id == 4).limit(1))
            log.warning("%s STATE=%s", MARK, json.dumps({
                "application_exists": bool(application),
                "application_status": application.status if application else None,
                "invitation_sent": invitation.sent_at.isoformat() if invitation else None,
                "submission_exists": bool(response),
                "submission_at": response.created_at.isoformat() if response else None
            }, ensure_ascii=False))
            if response:
                for key in ("balance", "duplicate", "audit", "fraud", "access", "dispute", "internship"):
                    log.warning("%s %s=%s", MARK, key, json.dumps(getattr(response, key), ensure_ascii=False))
    except Exception as exc:
        log.error("%s FAILED=%s", MARK, type(exc).__name__, exc_info=True)
