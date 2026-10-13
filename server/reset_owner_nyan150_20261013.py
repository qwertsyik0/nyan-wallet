from sqlalchemy import delete, select

from . import backend_app as core
from .promo150_subscription_penalty import Promo150SubscriptionWatch


PROMO_CODE = "NYAN150"


def reset_owner_nyan150_20261013() -> None:
    owner_id = int(core.OWNER_TELEGRAM_ID)
    with core.SessionLocal() as session:
        with session.begin():
            promo = session.scalar(
                select(core.PromoCode)
                .where(core.PromoCode.code == PROMO_CODE)
                .with_for_update()
            )
            if promo is None:
                print("[reset_owner_nyan150_20261013] promo_missing")
                return

            redemption = session.scalar(
                select(core.PromoRedemption)
                .where(
                    core.PromoRedemption.promo_id == promo.id,
                    core.PromoRedemption.telegram_id == owner_id,
                )
                .with_for_update()
            )

            watch = session.scalar(
                select(Promo150SubscriptionWatch)
                .where(
                    Promo150SubscriptionWatch.promo_id == promo.id,
                    Promo150SubscriptionWatch.telegram_id == owner_id,
                )
                .with_for_update()
            )

            tx = session.scalar(
                select(core.Transaction)
                .where(
                    core.Transaction.telegram_id == owner_id,
                    core.Transaction.operation_type == "promo",
                    core.Transaction.description == f"Промокод {PROMO_CODE}",
                )
                .order_by(core.Transaction.id.desc())
                .with_for_update()
            )

            user = session.scalar(
                select(core.User)
                .where(core.User.telegram_id == owner_id)
                .with_for_update()
            )

            removed_redemption = redemption is not None
            removed_watch = watch is not None
            reversed_amount = 0

            if redemption is not None:
                session.delete(redemption)
                if int(promo.uses_count or 0) > 0:
                    promo.uses_count = int(promo.uses_count) - 1

            if watch is not None:
                session.delete(watch)

            if tx is not None:
                reversed_amount = int(tx.amount or 0)
                if user is not None:
                    user.balance = int(user.balance or 0) - reversed_amount
                session.delete(tx)

            print(
                "[reset_owner_nyan150_20261013] "
                f"owner_id={owner_id} redemption={removed_redemption} "
                f"watch={removed_watch} reversed_amount={reversed_amount} "
                f"uses_count={int(promo.uses_count or 0)}"
            )
