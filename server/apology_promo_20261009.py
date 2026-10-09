from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select

from server import backend_app as core

PROMO_CODE = "SORRY-535459-50"


def ensure_apology_promo_20261009() -> None:
    timestamp = datetime.now(timezone.utc)
    with core.SessionLocal() as session:
        with session.begin():
            existing = session.scalar(
                select(core.PromoCode).where(core.PromoCode.code == PROMO_CODE)
            )
            if existing is not None:
                return

            session.add(
                core.PromoCode(
                    code=PROMO_CODE,
                    reward_amount=50,
                    max_uses=1,
                    uses_count=0,
                    is_active=True,
                    description="Промокод-извинение за ошибочное списание 2500 🐾",
                    created_at=timestamp,
                    expires_at=None,
                )
            )
