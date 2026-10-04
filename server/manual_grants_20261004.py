from sqlalchemy import select

from .backend_app import SessionLocal, Transaction, User, now_utc


GRANT_OPERATION_TYPE = "interactive_reward_20261004"
GRANT_DESCRIPTION = "Интерактив"
GRANT_AMOUNT = 777
GRANT_TELEGRAM_IDS = (
    7320177412,
    8178699225,
    8692747898,
)


def apply_interactive_grants_20261004() -> None:
    """Grant the interactive reward once per listed Telegram account.

    The operation type is unique to this batch, so repeated application starts
    are idempotent and cannot credit the same account twice.
    """

    timestamp = now_utc()

    with SessionLocal() as session:
        with session.begin():
            for telegram_id in GRANT_TELEGRAM_IDS:
                already_granted = session.scalar(
                    select(Transaction.id).where(
                        Transaction.telegram_id == telegram_id,
                        Transaction.operation_type == GRANT_OPERATION_TYPE,
                    )
                )
                if already_granted is not None:
                    continue

                user = session.scalar(
                    select(User)
                    .where(User.telegram_id == telegram_id)
                    .with_for_update()
                )
                if user is None:
                    # Keep retrying on future starts until the wallet account exists.
                    continue

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
