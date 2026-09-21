from __future__ import annotations

from server import backend_app as core
from server.daily_tasks import record_task_event

_PATCHED = False
_ORIGINAL_REDEEM = None
_ORIGINAL_GET_OR_CREATE = None


def register_daily_task_hooks() -> None:
    """Attach task events to existing core functions without changing their public API."""

    global _PATCHED, _ORIGINAL_REDEEM, _ORIGINAL_GET_OR_CREATE
    if _PATCHED:
        return

    _ORIGINAL_REDEEM = core.redeem_promo
    _ORIGINAL_GET_OR_CREATE = core.get_or_create_user

    def redeem_with_task_event(tg_user: dict, raw_code: str) -> dict:
        result = _ORIGINAL_REDEEM(tg_user, raw_code)
        try:
            event = record_task_event(tg_user["id"], "promo_redeem")
            result["task_event"] = event
        except Exception:
            result["task_event"] = {"changed": [], "credited_total": 0}
        return result

    def get_or_create_with_task_event(tg_user: dict) -> dict:
        result = _ORIGINAL_GET_OR_CREATE(tg_user)
        try:
            event = record_task_event(tg_user["id"], "open_wallet")
            result["task_event"] = event
        except Exception:
            result["task_event"] = {"changed": [], "credited_total": 0}
        return result

    core.redeem_promo = redeem_with_task_event
    core.get_or_create_user = get_or_create_with_task_event
    _PATCHED = True
