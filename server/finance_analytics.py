"""Owner-only, read-only circulation and transaction analytics.

Transfers are separated from issuance/spending: moving paws between two
wallets does not change the amount in circulation. No balance writes here.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Header, Query
from sqlalchemy import case, func, select

from . import backend_app as core


router = APIRouter()
_REGISTERED = False
MOSCOW = ZoneInfo("Europe/Moscow")


def _period_start(days: int, timestamp: datetime) -> datetime | None:
    if days == 0:
        return None
    day = timestamp.astimezone(MOSCOW).date() - timedelta(days=days - 1)
    return datetime.combine(day, time.min, tzinfo=MOSCOW).astimezone(timezone.utc)


@router.get("/api/owner/finance-analytics")
def finance_analytics(
    days: int = Query(default=7),
    x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data"),
):
    tg_user = core.verify_init_data(x_telegram_init_data or "")
    core.require_owner(tg_user)
    if days not in {0, 1, 7, 30}:
        from fastapi import HTTPException
        raise HTTPException(status_code=422, detail="Доступны периоды: 1, 7, 30 дней или всё время")

    now = core.now_utc()
    since = _period_start(days, now)
    tx = core.Transaction
    amount = tx.amount
    # A transfer generates both transfer_out and transfer_in entries.
    # Exclude both from issuance/debits; show outgoing transfer volume once.
    earned = case(((amount > 0) & (tx.operation_type != "transfer_in"), amount), else_=0)
    spent = case(((amount < 0) & (tx.operation_type != "transfer_out"), -amount), else_=0)
    moved = case((tx.operation_type == "transfer_out", -amount), else_=0)

    with core.SessionLocal() as session:
        wallets = session.execute(select(
            func.count(core.User.telegram_id),
            func.coalesce(func.sum(core.User.balance), 0),
            func.coalesce(func.count(core.User.telegram_id).filter(
                core.User.created_at >= since), 0) if since else func.count(core.User.telegram_id),
            func.coalesce(func.count(core.User.telegram_id).filter(
                core.User.last_seen_at >= since), 0) if since else func.count(core.User.telegram_id),
        )).one()

        filters = [] if since is None else [tx.created_at >= since]
        totals = session.execute(select(
            func.count(tx.id),
            func.coalesce(func.sum(earned), 0),
            func.coalesce(func.sum(spent), 0),
            func.coalesce(func.sum(moved), 0),
            func.coalesce(func.sum(case((tx.operation_type == "transfer_out", 1), else_=0)), 0),
        ).where(*filters)).one()

        categories = session.execute(select(
            tx.operation_type,
            func.count(tx.id),
            func.coalesce(func.sum(earned), 0),
            func.coalesce(func.sum(spent), 0),
            func.coalesce(func.sum(moved), 0),
        ).where(*filters).group_by(tx.operation_type)).all()

        # Keep the graph bounded even if the owner selects "all time".
        chart_days = 30 if days == 0 else days
        chart_since = _period_start(chart_days, now)
        if session.bind.dialect.name == "postgresql":
            day_column = func.date(func.timezone("Europe/Moscow", tx.created_at))
        else:
            # SQLite is used only by the isolated test suite.
            day_column = func.date(tx.created_at)
        daily_rows = session.execute(select(
            day_column.label("day"),
            func.coalesce(func.sum(earned), 0),
            func.coalesce(func.sum(spent), 0),
            func.coalesce(func.sum(moved), 0),
        ).where(tx.created_at >= chart_since)
            .group_by(day_column).order_by(day_column)).all()

    day_map = {str(day): (int(a), int(b), int(c)) for day, a, b, c in daily_rows}
    start_day = now.astimezone(MOSCOW).date() - timedelta(days=chart_days - 1)
    daily = []
    for shift in range(chart_days):
        day = (start_day + timedelta(days=shift)).isoformat()
        a, b, c = day_map.get(day, (0, 0, 0))
        daily.append({"day": day, "earned": a, "spent": b, "transfers": c})

    return {
        "ok": True,
        "days": days,
        "timezone": "Europe/Moscow",
        "generated_at": now.isoformat(),
        "wallets": {
            "total": int(wallets[0]), "balance_in_circulation": int(wallets[1]),
            "new": int(wallets[2]), "active": int(wallets[3]),
        },
        "transactions": {
            "count": int(totals[0]), "credited_excluding_transfers": int(totals[1]),
            "debited_excluding_transfers": int(totals[2]),
            "transfer_volume": int(totals[3]), "transfers_count": int(totals[4]),
        },
        "categories": sorted([
            {"type": str(kind), "count": int(count), "credited": int(a),
             "debited": int(b), "transfers": int(c)}
            for kind, count, a, b, c in categories
        ], key=lambda row: (-row["credited"] - row["debited"] - row["transfers"], row["type"])),
        "daily": daily,
    }


def register_finance_analytics(app) -> None:
    global _REGISTERED
    if _REGISTERED:
        return
    app.include_router(router)
    _REGISTERED = True
