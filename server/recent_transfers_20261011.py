from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import aliased

from . import backend_app as core
from .transfers import WalletTransfer


def print_recent_wallet_transfers_20261011() -> None:
    sender = aliased(core.User)
    recipient = aliased(core.User)
    start = datetime(2026, 10, 9, 21, 0, 0, tzinfo=timezone.utc)
    end = datetime(2026, 10, 11, 21, 0, 0, tzinfo=timezone.utc)

    with core.SessionLocal() as session:
        rows = session.execute(
            select(
                WalletTransfer.public_id,
                WalletTransfer.sender_id,
                sender.username,
                sender.first_name,
                WalletTransfer.recipient_id,
                recipient.username,
                recipient.first_name,
                WalletTransfer.amount,
                WalletTransfer.note,
                WalletTransfer.created_at,
            )
            .join(sender, sender.telegram_id == WalletTransfer.sender_id)
            .join(recipient, recipient.telegram_id == WalletTransfer.recipient_id)
            .where(WalletTransfer.created_at >= start, WalletTransfer.created_at < end)
            .order_by(WalletTransfer.created_at.asc(), WalletTransfer.id.asc())
        ).all()

    payload = []
    for row in rows:
        payload.append({
            "public_id": row[0],
            "sender_id": int(row[1]),
            "sender_username": row[2],
            "sender_first_name": row[3],
            "recipient_id": int(row[4]),
            "recipient_username": row[5],
            "recipient_first_name": row[6],
            "amount": int(row[7]),
            "note": row[8],
            "created_at": row[9].isoformat() if row[9] else None,
        })
    print("[recent_transfers_20261011] " + json.dumps(payload, ensure_ascii=False))
