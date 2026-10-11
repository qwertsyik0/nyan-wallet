from __future__ import annotations

import json

from sqlalchemy import func, select

from .backend_app import SessionLocal, Transaction, User, now_utc


OPERATION_TYPE = "nyan_market_leftover_exchange_20261011"

GRANTS = (
    ("@floriannq", 1, 20),
    ("@Ceniora_vanil", 4, 80),
    ("@k4r11_xD", 7, 140),
    ("5291356933", 7, 140),
    ("@mppwb", 1, 20),
    ("@chershq", 1, 20),
    ("@wwiettt", 1, 20),
    ("@rc_otq", 15, 300),
    ("@rosws", 8, 160),
    ("@assstre", 16, 320),
    ("@reveriieeii", 9, 180),
    ("@liviskas", 1, 20),
    ("@noksaaaa", 8, 160),
    ("@hef_krutoy", 10, 200),
    ("@KiviSon", 2, 40),
    ("@Sakaighezd", 13, 260),
)


def _resolve_user(session, target: str):
    raw = target.strip()
    if raw.isdigit():
        user = session.get(User, int(raw))
        return user, "ok" if user else "not_found"

    username = raw.lstrip("@")
    users = session.scalars(
        select(User)
        .where(func.lower(User.username) == username.lower())
        .order_by(User.last_seen_at.desc())
    ).all()

    if not users:
        return None, "not_found"
    if len(users) > 1:
        return None, "ambiguous"
    return users[0], "ok"


def apply_nyan_market_leftover_exchange_20261011() -> None:
    timestamp = now_utc()
    report = []

    with SessionLocal() as session:
        with session.begin():
            for target, tickets, amount in GRANTS:
                user, status = _resolve_user(session, target)

                if user is None:
                    report.append({
                        "target": target,
                        "tickets": tickets,
                        "amount": amount,
                        "status": status,
                    })
                    continue

                already = session.scalar(
                    select(Transaction.id).where(
                        Transaction.telegram_id == user.telegram_id,
                        Transaction.operation_type == OPERATION_TYPE,
                    )
                )
                if already is not None:
                    report.append({
                        "target": target,
                        "telegram_id": int(user.telegram_id),
                        "username": user.username,
                        "tickets": tickets,
                        "amount": amount,
                        "status": "already_granted",
                        "balance": int(user.balance),
                    })
                    continue

                user.balance += amount
                session.add(
                    Transaction(
                        telegram_id=user.telegram_id,
                        amount=amount,
                        operation_type=OPERATION_TYPE,
                        description=f"Обмен остатков Nyan Market: {tickets} 🎟 → {amount} 🐾",
                        created_at=timestamp,
                    )
                )
                session.flush()

                report.append({
                    "target": target,
                    "telegram_id": int(user.telegram_id),
                    "username": user.username,
                    "tickets": tickets,
                    "amount": amount,
                    "status": "granted",
                    "balance": int(user.balance),
                })

    print("[nyan_market_leftover_exchange_20261011] " + json.dumps(report, ensure_ascii=False))
