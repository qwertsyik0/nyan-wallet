"""Temporary read-only aggregate sizes for Nyan Wallet ad broadcast pricing."""
import logging
from datetime import timedelta
from sqlalchemy import select, func
from . import backend_app as core

_LOG = logging.getLogger("nyan_wallet.audience_audit")
_MARK = "[AUDIENCE_AD_PRICING_20261015]"

def report_broadcast_audience():
    try:
        now = core.now_utc()
        owner_id = core.OWNER_TELEGRAM_ID
        with core.SessionLocal() as session:
            stmt = select(func.count()).select_from(core.User)
            if owner_id is not None:
                stmt = stmt.where(core.User.telegram_id != owner_id)
            all_users = session.scalar(stmt) or 0
            active_7 = session.scalar(stmt.where(core.User.last_seen_at >= now - timedelta(days=7))) or 0
            active_30 = session.scalar(stmt.where(core.User.last_seen_at >= now - timedelta(days=30))) or 0
            new_7 = session.scalar(stmt.where(core.User.created_at >= now - timedelta(days=7))) or 0
            new_30 = session.scalar(stmt.where(core.User.created_at >= now - timedelta(days=30))) or 0
            _LOG.warning("%s total=%d active_7d=%d active_30d=%d new_7d=%d new_30d=%d",
                         _MARK, all_users, active_7, active_30, new_7, new_30)
    except Exception as exc:
        _LOG.warning("%s READ_ERROR %s", _MARK, type(exc).__name__, exc_info=True)
