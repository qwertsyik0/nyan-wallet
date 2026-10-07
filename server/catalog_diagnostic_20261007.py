from __future__ import annotations

import json
import logging
import os

from sqlalchemy import text

from server import backend_app as core

logger = logging.getLogger("nyan_wallet.catalog_diagnostic")


def log_catalog_diagnostic_20261007() -> None:
    if os.getenv("NYAN_CATALOG_DIAGNOSTIC_VERSION") != "1":
        return
    try:
        with core.SessionLocal() as session:
            stats = session.execute(text("""
                SELECT
                    COUNT(*) FILTER (WHERE telegram_id <> :owner_id) AS users,
                    COALESCE(SUM(balance) FILTER (WHERE telegram_id <> :owner_id), 0) AS circulation,
                    ROUND(AVG(balance) FILTER (WHERE telegram_id <> :owner_id)::numeric, 2) AS avg_balance,
                    PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY balance)
                        FILTER (WHERE telegram_id <> :owner_id) AS median_balance,
                    MIN(balance) FILTER (WHERE telegram_id <> :owner_id) AS min_balance,
                    MAX(balance) FILTER (WHERE telegram_id <> :owner_id) AS max_balance
                FROM users
            """), {"owner_id": core.OWNER_TELEGRAM_ID or -1}).mappings().one()

            rewards = session.execute(text("""
                SELECT id, title, cost, is_active, sort_order
                FROM reward_catalog
                ORDER BY sort_order ASC, id ASC
            """)).mappings().all()

            payload = {
                "users": int(stats["users"] or 0),
                "circulation": int(stats["circulation"] or 0),
                "avg_balance": float(stats["avg_balance"] or 0),
                "median_balance": float(stats["median_balance"] or 0),
                "min_balance": int(stats["min_balance"] or 0),
                "max_balance": int(stats["max_balance"] or 0),
                "rewards": [
                    {
                        "id": int(row["id"]),
                        "title": row["title"],
                        "cost": int(row["cost"]),
                        "is_active": bool(row["is_active"]),
                        "sort_order": int(row["sort_order"]),
                    }
                    for row in rewards
                ],
            }
            logger.warning("CATALOG_DIAGNOSTIC_20261007 %s", json.dumps(payload, ensure_ascii=False))
    except Exception:
        logger.exception("CATALOG_DIAGNOSTIC_20261007_FAILED")
