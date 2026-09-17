from __future__ import annotations

import threading

from sqlalchemy import event

from server import backend_app as core
from server.extended_features import AdminAudit, send_telegram_message

_REGISTERED = False

ACTION_LABELS = {
    "owner_grant": "Начисление лапкоинов",
    "owner_debit": "Списание лапкоинов",
    "promo_created": "Создан промокод",
    "promo_toggled": "Изменён статус промокода",
    "promo_limit_changed": "Изменён лимит промокода",
    "promo_deleted": "Удалён промокод",
    "reward_fulfilled": "Приз отмечен выданным",
}


def _send_async(chat_id: int | None, text: str) -> None:
    if not chat_id:
        return
    threading.Thread(
        target=send_telegram_message,
        args=(chat_id, text),
        daemon=True,
    ).start()


def _notify_owner_after_audit_insert(mapper, connection, target: AdminAudit) -> None:
    if not core.OWNER_TELEGRAM_ID:
        return

    title = ACTION_LABELS.get(target.action, target.action)
    lines = ["🐾 Nyan Wallet", title]

    if target.target_telegram_id:
        lines.append(f"Telegram ID: {target.target_telegram_id}")
    if target.details:
        lines.append(target.details)

    _send_async(core.OWNER_TELEGRAM_ID, "\n".join(lines))


def register_instant_notifications() -> None:
    global _REGISTERED
    if _REGISTERED:
        return

    event.listen(AdminAudit, "after_insert", _notify_owner_after_audit_insert)
    _REGISTERED = True
