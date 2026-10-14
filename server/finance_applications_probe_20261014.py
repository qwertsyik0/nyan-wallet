"""Temporary, read-only owner-requested check. Delete after collecting results."""
import json
import logging
from sqlalchemy import select, func
from . import backend_app as core
from .finance_recruitment import FinancialAdminApplication as Application

log = logging.getLogger("nyan.finance_applications_probe_20261014")
PREFIX = "[FIN_APPS_20261014]"

def inspect_new_applications():
    try:
        with core.SessionLocal() as session:
            pending = session.scalar(select(func.count()).select_from(Application).where(Application.status == "pending"))
            total = session.scalar(select(func.count()).select_from(Application))
            log.warning("%s TOTAL=%s PENDING=%s", PREFIX, total, pending)
            rows = session.execute(
                select(Application, core.User)
                .join(core.User, core.User.telegram_id == Application.telegram_id)
                .order_by(Application.created_at.desc(), Application.id.desc())
                .limit(5)
            ).all()
            for item, user in rows:
                base = {
                    "id": item.id, "username": user.username, "telegram_id": item.telegram_id,
                    "name": item.display_name, "age_group": item.age_group,
                    "timezone": item.timezone, "availability": item.availability,
                    "status": item.status,
                    "created_at": item.created_at.isoformat() if item.created_at else None,
                }
                log.warning("%s META=%s", PREFIX, json.dumps(base, ensure_ascii=False))
                for key in ("experience", "skills", "motivation", "situation_discrepancy", "situation_farm", "owner_note"):
                    value = getattr(item, key, None)
                    log.warning("%s ID=%s %s=%s", PREFIX, item.id, key, json.dumps(value, ensure_ascii=False))
    except Exception as exc:
        log.exception("%s READ_ERROR: %s", PREFIX, type(exc).__name__)
