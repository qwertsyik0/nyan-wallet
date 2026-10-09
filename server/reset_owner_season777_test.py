from __future__ import annotations

from sqlalchemy import delete

from server import backend_app as core
from server.season_777 import Season777State

_ACTION = "season777_owner_test_reset_20261009_v1"


def reset_owner_season777_test_once() -> None:
    owner_id = core.OWNER_TELEGRAM_ID
    if owner_id is None:
        return

    with core.SessionLocal() as session:
        with session.begin():
            # Reuse the audit table only if it is available; otherwise deletion is still idempotent enough
            # because this helper is removed after verification.
            session.execute(
                delete(Season777State).where(Season777State.telegram_id == int(owner_id))
            )
