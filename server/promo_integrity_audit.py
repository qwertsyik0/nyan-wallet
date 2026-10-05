from __future__ import annotations

from sqlalchemy import func, inspect, select

from . import backend_app as core


def audit_promo_integrity() -> None:
    """Read-only startup audit for promo redemption integrity."""
    with core.SessionLocal() as session:
        duplicates = session.execute(
            select(
                core.PromoRedemption.promo_id,
                core.PromoRedemption.telegram_id,
                func.count(core.PromoRedemption.id).label("n"),
            )
            .group_by(core.PromoRedemption.promo_id, core.PromoRedemption.telegram_id)
            .having(func.count(core.PromoRedemption.id) > 1)
        ).all()

        redemption_counts = dict(
            session.execute(
                select(
                    core.PromoRedemption.promo_id,
                    func.count(core.PromoRedemption.id),
                ).group_by(core.PromoRedemption.promo_id)
            ).all()
        )

        promos = session.scalars(select(core.PromoCode)).all()
        mismatches = [
            (p.id, p.code, int(p.uses_count or 0), int(redemption_counts.get(p.id, 0)))
            for p in promos
            if int(p.uses_count or 0) != int(redemption_counts.get(p.id, 0))
        ]

        promo_tx_count = int(
            session.scalar(
                select(func.count(core.Transaction.id)).where(
                    core.Transaction.operation_type == "promo"
                )
            )
            or 0
        )
        redemption_total = int(
            session.scalar(select(func.count(core.PromoRedemption.id))) or 0
        )

    constraints = inspect(core.engine).get_unique_constraints("promo_redemptions")
    constraint_names = sorted(
        str(item.get("name") or "")
        for item in constraints
        if item.get("column_names") == ["promo_id", "telegram_id"]
        or set(item.get("column_names") or []) == {"promo_id", "telegram_id"}
    )

    print(
        "[promo_integrity] "
        f"duplicate_pairs={len(duplicates)} "
        f"counter_mismatches={len(mismatches)} "
        f"promo_transactions={promo_tx_count} "
        f"redemptions={redemption_total} "
        f"unique_constraints={constraint_names}"
    )
    if duplicates:
        print("[promo_integrity] duplicates=", duplicates[:20])
    if mismatches:
        print("[promo_integrity] mismatches=", mismatches[:20])
