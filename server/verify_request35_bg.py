from sqlalchemy import text
import logging
from server import backend_app as core

logger = logging.getLogger("nyan_wallet.verify_request35")

def verify_request35_background() -> None:
    try:
        with core.SessionLocal() as session:
            row = session.execute(text("""
                SELECT uc.telegram_id, uc.profile_background, uc.updated_at,
                       sr.id AS request_id, sr.status, sr.processed_at
                FROM user_cosmetics uc
                LEFT JOIN spend_requests sr
                  ON sr.id = 35 AND sr.telegram_id = uc.telegram_id
                WHERE uc.telegram_id = 6665456961
            """)).mappings().first()
            print("REQUEST35_VERIFY", dict(row) if row else None, flush=True)
    except Exception:
        import traceback; traceback.print_exc(); print("REQUEST35_VERIFY_FAILED", flush=True)
