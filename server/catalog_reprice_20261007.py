from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from sqlalchemy import text

from server import backend_app as core

ACTION = "catalog_reprice_20261007_v1"
logger = logging.getLogger("nyan_wallet.catalog_reprice")

NEW_PRICES = {
    5: 2250,   # Физический аккаунт США
    6: 200,    # Скидка 5%
    7: 400,    # Скидка 10%
    8: 650,    # Скидка 15%
    9: 350,    # +7 дней гарантии
    10: 900,   # Бесплатная замена аккаунта 1 раз
    11: 350,   # Случайный подарок
    12: 650,   # Улучшенный подарок
    13: 350,   # Билет на закрытый розыгрыш
    14: 650,   # 3 билета на розыгрыш
    15: 450,   # x2 лапкоины за следующую покупку
    16: 850,   # x2 лапкоины на 24 часа
    17: 400,   # Смена номера/дизайна кошелька
    18: 950,   # Редкий номер кошелька
    19: 500,   # Уникальный фон карточки
    20: 1000,  # Анимированный фон профиля
    21: 1900,  # VIP на 30 дней
    22: 650,   # Значок рядом с ником
    23: 2500,  # Лимитированный предмет/значок
}


def apply_catalog_reprice_20261007() -> None:
    with core.SessionLocal() as session:
        with session.begin():
            already_done = session.execute(
                text("SELECT 1 FROM admin_audit WHERE action = :action LIMIT 1"),
                {"action": ACTION},
            ).first()
            if already_done:
                logger.warning("CATALOG_REPRICE_20261007 already_applied")
                return

            changed = []
            for reward_id, new_cost in NEW_PRICES.items():
                row = session.execute(
                    text("""
                        UPDATE reward_catalog
                        SET cost = :cost
                        WHERE id = :reward_id
                        RETURNING id, title, cost
                    """),
                    {"reward_id": reward_id, "cost": new_cost},
                ).mappings().first()
                if row is not None:
                    changed.append({
                        "id": int(row["id"]),
                        "title": row["title"],
                        "cost": int(row["cost"]),
                    })

            session.execute(
                text("""
                    INSERT INTO admin_audit
                        (action, target_telegram_id, details, created_at)
                    VALUES
                        (:action, NULL, :details, :created_at)
                """),
                {
                    "action": ACTION,
                    "details": json.dumps(changed, ensure_ascii=False),
                    "created_at": datetime.now(timezone.utc),
                },
            )

    logger.warning("CATALOG_REPRICE_20261007 applied %s", json.dumps(NEW_PRICES, ensure_ascii=False))
