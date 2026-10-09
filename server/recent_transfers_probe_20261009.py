from datetime import datetime, timezone
from sqlalchemy import select
from server import backend_app as core
from server.transfers import WalletTransfer

def probe_recent_transfers_20261009() -> None:
    start = datetime(2026, 10, 7, 21, 0, 0, tzinfo=timezone.utc)  # 08.10 00:00 UTC+3
    with core.SessionLocal() as session:
        rows = session.scalars(
            select(WalletTransfer)
            .where(WalletTransfer.created_at >= start)
            .order_by(WalletTransfer.created_at.asc(), WalletTransfer.id.asc())
        ).all()
        print(f"RECENT_TRANSFERS_20261009 count={len(rows)}", flush=True)
        for row in rows:
            print(
                "RECENT_TRANSFERS_20261009 "
                f"id={row.public_id} sender_id={row.sender_id} recipient_id={row.recipient_id} "
                f"amount={row.amount} created_at={row.created_at.isoformat()} note={row.note!r}",
                flush=True,
            )
