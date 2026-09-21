from sqlalchemy import select

from .backend_app import PROMO_PATTERN, PromoCode, SessionLocal, normalize_promo_code, now_utc


CAMPAIGN_PROMOS = [
    {
        "code": "NYANFLASH600",
        "reward_amount": 600,
        "max_uses": 5,
        "description": "Рассылка Nyan Wallet: экспресс-бонус 600 ЛК для первых 5 пользователей",
    },
    {
        "code": "NYANPACT700",
        "reward_amount": 700,
        "max_uses": 1,
        "description": "Секретное промо Nyan Wallet: 700 ЛК для одной активации",
    },
]

DISABLED_CAMPAIGN_PROMOS = [
    "NYANROFL700",
]


def register_campaign_promos() -> None:
    """Create or update fixed campaign promos without resetting existing activations."""

    timestamp = now_utc()

    with SessionLocal() as session:
        with session.begin():
            for campaign in CAMPAIGN_PROMOS:
                code = normalize_promo_code(campaign["code"])
                if not PROMO_PATTERN.fullmatch(code):
                    raise RuntimeError(f"Некорректный системный промокод: {code}")

                reward_amount = int(campaign["reward_amount"])
                max_uses = campaign.get("max_uses")
                max_uses = int(max_uses) if max_uses is not None else None

                if reward_amount <= 0:
                    raise RuntimeError(f"Некорректная награда промокода {code}")
                if max_uses is not None and max_uses <= 0:
                    raise RuntimeError(f"Некорректный лимит промокода {code}")

                existing = session.scalar(select(PromoCode).where(PromoCode.code == code))

                if existing is None:
                    session.add(
                        PromoCode(
                            code=code,
                            reward_amount=reward_amount,
                            max_uses=max_uses,
                            uses_count=0,
                            is_active=True,
                            description=campaign.get("description"),
                            created_at=timestamp,
                            expires_at=None,
                        )
                    )
                    continue

                existing.reward_amount = reward_amount
                existing.max_uses = max_uses
                existing.is_active = True
                existing.description = campaign.get("description")
                existing.expires_at = None

            for legacy_code in DISABLED_CAMPAIGN_PROMOS:
                code = normalize_promo_code(legacy_code)
                if not PROMO_PATTERN.fullmatch(code):
                    raise RuntimeError(f"Некорректный отключаемый промокод: {code}")
                existing = session.scalar(select(PromoCode).where(PromoCode.code == code))
                if existing is not None:
                    existing.is_active = False
                    existing.description = "Отключённый черновой промокод"
