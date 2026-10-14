"""Temporary read-only second-stage result inspection; remove after review."""
import json
import logging
from sqlalchemy import select
from . import backend_app as core
from .finance_stage2 import FinanceStage2Response

logger = logging.getLogger("nyan_wallet.stage2_inspection")
TAG = "[STAGE2_REVIEW_20261014]"

def inspect_stage2():
    try:
        with core.SessionLocal() as session:
            row = session.scalar(
                select(FinanceStage2Response)
                .where(FinanceStage2Response.application_id == 2)
                .limit(1)
            )
            if row is None:
                logger.warning("%s NO_SUBMISSION", TAG)
                return
            logger.warning("%s SUBMITTED id=%s created=%s", TAG, row.id, row.created_at.isoformat())
            for key in ("balance", "duplicate", "audit", "fraud", "access", "dispute", "internship"):
                logger.warning("%s %s=%s", TAG, key, json.dumps(getattr(row, key), ensure_ascii=False))
    except Exception as exc:
        logger.warning("%s INSPECTION_FAILED type=%s", TAG, type(exc).__name__, exc_info=True)
