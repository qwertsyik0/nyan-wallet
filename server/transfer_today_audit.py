from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import func, select

from . import backend_app as core
from .transfers import WalletTransfer

HELSINKI = ZoneInfo("Europe/Helsinki")


def audit_today_transfers() -> None:
    local_now = datetime.now(HELSINKI)
    local_start = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    utc_start = local_start.astimezone(timezone.utc)
    utc_end = local_now.astimezone(timezone.utc)

    with core.SessionLocal() as session:
        rows = session.execute(
            select(
                WalletTransfer,
                core.User.username,
                core.User.first_name,
            )
            .join(core.User, core.User.telegram_id == WalletTransfer.sender_id)
            .where(
                WalletTransfer.created_at >= utc_start,
                WalletTransfer.created_at <= utc_end,
            )
            .order_by(WalletTransfer.created_at.asc())
        ).all()

        # recipient labels in a separate map
        recipient_ids = sorted({int(row[0].recipient_id) for row in rows})
        recipients = {}
        if recipient_ids:
            for user in session.scalars(
                select(core.User).where(core.User.telegram_id.in_(recipient_ids))
            ).all():
                recipients[int(user.telegram_id)] = user

        total_amount = sum(int(row[0].amount) for row in rows)
        unique_senders = len({int(row[0].sender_id) for row in rows})
        unique_recipients = len({int(row[0].recipient_id) for row in rows})

        transfer_out_count = int(
            session.scalar(
                select(func.count(core.Transaction.id)).where(
                    core.Transaction.operation_type == "transfer_out",
                    core.Transaction.created_at >= utc_start,
                    core.Transaction.created_at <= utc_end,
                )
            ) or 0
        )
        transfer_in_count = int(
            session.scalar(
                select(func.count(core.Transaction.id)).where(
                    core.Transaction.operation_type == "transfer_in",
                    core.Transaction.created_at >= utc_start,
                    core.Transaction.created_at <= utc_end,
                )
            ) or 0
        )

        print(
            "[transfer_today] "
            f"date={local_start.date().isoformat()} "
            f"count={len(rows)} total_amount={total_amount} "
            f"unique_senders={unique_senders} unique_recipients={unique_recipients} "
            f"transfer_out={transfer_out_count} transfer_in={transfer_in_count}"
        )

        previous_by_key: dict[tuple[int, int, int], WalletTransfer] = {}
        rapid_repeats: list[tuple[WalletTransfer, WalletTransfer, float]] = []

        for transfer, sender_username, sender_first_name in rows:
            recipient = recipients.get(int(transfer.recipient_id))
            sender_label = ("@" + sender_username) if sender_username else (sender_first_name or str(transfer.sender_id))
            recipient_label = (
                ("@" + recipient.username)
                if recipient and recipient.username
                else (recipient.first_name if recipient else str(transfer.recipient_id))
            )
            local_created = transfer.created_at.astimezone(HELSINKI)
            print(
                "[transfer_today_item] "
                f"id={transfer.public_id} "
                f"time={local_created.strftime('%H:%M:%S')} "
                f"sender={sender_label}({transfer.sender_id}) "
                f"recipient={recipient_label}({transfer.recipient_id}) "
                f"amount={transfer.amount} "
                f"note={transfer.note!r} "
                f"idem={transfer.idempotency_key}"
            )

            key = (int(transfer.sender_id), int(transfer.recipient_id), int(transfer.amount))
            prev = previous_by_key.get(key)
            if prev is not None:
                seconds = (transfer.created_at - prev.created_at).total_seconds()
                if seconds <= 30:
                    rapid_repeats.append((prev, transfer, seconds))
            previous_by_key[key] = transfer

        print(f"[transfer_today] rapid_repeat_count={len(rapid_repeats)}")
        for prev, cur, seconds in rapid_repeats:
            print(
                "[transfer_today_repeat] "
                f"first={prev.public_id} second={cur.public_id} "
                f"sender={cur.sender_id} recipient={cur.recipient_id} "
                f"amount={cur.amount} seconds={seconds:.3f}"
            )
