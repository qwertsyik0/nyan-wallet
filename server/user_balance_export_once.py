import json
from sqlalchemy import select

from . import backend_app as core


def export_user_balances_once() -> None:
    with core.SessionLocal() as session:
        users = session.scalars(
            select(core.User).order_by(core.User.telegram_id.asc())
        ).all()

    rows = [
        {
            "telegram_id": int(u.telegram_id),
            "username": u.username or "",
            "first_name": u.first_name or "",
            "last_name": u.last_name or "",
            "balance": int(u.balance),
        }
        for u in users
    ]

    chunk_size = 20
    total_chunks = (len(rows) + chunk_size - 1) // chunk_size
    print(f"[user_balance_export_meta] users={len(rows)} chunks={total_chunks}")
    for index in range(total_chunks):
        chunk = rows[index * chunk_size : (index + 1) * chunk_size]
        print(
            "[user_balance_export_chunk] "
            f"{index + 1}/{total_chunks} "
            + json.dumps(chunk, ensure_ascii=False, separators=(",", ":"))
        )
