"""Temporary read-only finance candidate inspection. Delete after use."""
import json
import logging
from sqlalchemy import select, func
from . import backend_app as core
from .finance_recruitment import FinancialAdminApplication as Application

logger = logging.getLogger("nyan_wallet.finance_new_audit")
MARK = "[FIN_NEW_AUDIT_20261015]"

def audit_new_applications():
    try:
        with core.SessionLocal() as session:
            total = session.scalar(select(func.count()).select_from(Application))
            newer = session.scalar(select(func.count()).select_from(Application).where(Application.id > 2))
            logger.warning("%s COUNTS total=%s new=%s", MARK, total, newer)
            rows = session.execute(
                select(Application, core.User)
                .join(core.User, core.User.telegram_id == Application.telegram_id)
                .where(Application.id > 2)
                .order_by(Application.id.asc())
                .limit(30)
            ).all()
            for app, user in rows:
                public_data = {
                    "id": app.id, "username": user.username or "",
                    "display_name": app.display_name, "age_group": app.age_group,
                    "availability": app.availability, "timezone": app.timezone,
                    "status": app.status,
                    "created_at": app.created_at.isoformat() if app.created_at else None,
                }
                logger.warning("%s APPLICANT=%s", MARK, json.dumps(public_data, ensure_ascii=False))
                for key in ("experience", "skills", "motivation", "situation_discrepancy", "situation_farm"):
                    logger.warning("%s APP=%s FIELD=%s VALUE=%s", MARK, app.id, key,
                                   json.dumps(getattr(app, key), ensure_ascii=False))
    except Exception as exc:
        logger.exception("%s READ_ERROR %s", MARK, type(exc).__name__)
