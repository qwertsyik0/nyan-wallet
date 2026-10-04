from sqlalchemy import select

from .backend_app import SessionLocal, Transaction, User, now_utc
from .manual_grants_20261004 import (
    GRANT_AMOUNT,
    GRANT_DESCRIPTION,
    GRANT_OPERATION_TYPE,
    GRANT_TELEGRAM_IDS,
)


def backfill_interactive_grants_20261004() -> None:
    timestamp = now_utc()
    granted = 0
    already = 0
    created_users = 0

    with SessionLocal() as session:
        with session.begin():
            for telegram_id in GRANT_TELEGRAM_IDS:
                existing_tx = session.scalar(
                    select(Transaction.id).where(
                        Transaction.telegram_id == telegram_id,
                        Transaction.operation_type == GRANT_OPERATION_TYPE,
                    )
                )
                if existing_tx is not None:
                    already += 1
                    continue

                user = session.scalar(
                    select(User)
                    .where(User.telegram_id == telegram_id)
                    .with_for_update()
                )
                if user is None:
                    user = User(
                        telegram_id=telegram_id,
                        username=None,
                        first_name="Пользователь",
                        last_name=None,
                        balance=0,
                        created_at=timestamp,
                        last_seen_at=timestamp,
                    )
                    session.add(user)
                    session.flush()
                    created_users += 1

                user.balance += GRANT_AMOUNT
                session.add(
                    Transaction(
                        telegram_id=telegram_id,
                        amount=GRANT_AMOUNT,
                        operation_type=GRANT_OPERATION_TYPE,
                        description=GRANT_DESCRIPTION,
                        created_at=timestamp,
                    )
                )
                granted += 1

    print(
        "[interactive_reward_backfill_20261004] "
        f"granted={granted} already={already} created_users={created_users} amount={GRANT_AMOUNT}"
    )
