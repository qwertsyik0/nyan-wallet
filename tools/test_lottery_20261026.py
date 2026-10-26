"""Disposable SQLite lottery regression test: never connects to a live wallet."""

from __future__ import annotations

import importlib.util
import sys
from datetime import timedelta
from pathlib import Path

from sqlalchemy import func, select

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("lottery_base_test", ROOT / "tools/test_interactive_builder_profile.py")
base = importlib.util.module_from_spec(spec)
sys.modules["lottery_base_test"] = base
spec.loader.exec_module(base)
lottery = base.load("server.lottery", "lottery.py")
lottery.register_lottery(base.core.app)
base.core.app.openapi_schema = None
assert "/api/lottery/{round_id}/purchase" in base.core.app.openapi()["paths"]

core = base.core


def invoke(handler, user=None, *args):
    return base.DirectClient.invoke(handler, *args, x_telegram_init_data=base.DirectClient.token(user))


def create(user=base.owner, *, mode="manual", limit=4, end=None):
    payload = lottery.RoundInput.model_validate({
        "title": "Счастливый билет Нян", "description": "Лотерея с проверяемым учётом билетов.",
        "mode": mode, "max_per_user": limit, "ends_at": end,
        "tiers": [{"name": "простой", "price": 50, "weight": 1},
                  {"name": "премиум", "price": 150, "weight": 8}],
        "prizes": [{"title": "приз", "amount": 120, "quantity": 1}],
    })
    return invoke(lottery.owner_create, user, payload)


def act(handler, user, round_id, payload=None):
    args = (round_id, payload) if payload is not None else (round_id,)
    return invoke(handler, user, *args)


def buy(round_id, user, tier_id, count, key):
    payload = lottery.PurchaseInput(tier_id=tier_id, count=count, request_key=key)
    return act(lottery.lottery_purchase, user, round_id, payload)


with core.SessionLocal.begin() as session:
    timestamp = core.now_utc()
    for uid in [1001, 1002, 1003]:
        user = session.get(core.User, uid)
        if user is None:
            user = core.User(telegram_id=uid, first_name="Test", username=f"test{uid}",
                             last_name=None, balance=0, created_at=timestamp, last_seen_at=timestamp)
            session.add(user)
        user.balance = 2000


assert invoke(lottery.list_lotteries).status_code == 401
assert create(base.alice).status_code == 403

created = create()
assert created.status_code == 200, created.text
rid = created.json()["round"]["id"]
tier1, tier2 = [tier["id"] for tier in created.json()["round"]["tiers"]]
assert not invoke(lottery.list_lotteries, base.alice).json()["rounds"]
assert buy(rid, base.alice, tier1, 1, "waiting123").status_code == 409
assert act(lottery.owner_activate, base.owner, rid).status_code == 200
assert act(lottery.owner_activate, base.owner, rid).status_code == 409
assert buy(rid, base.alice, tier1, 1, "invalid123").status_code == 200
assert buy(rid, base.alice, tier2, 20, "no-money123").status_code == 409
same = buy(rid, base.alice, tier1, 1, "invalid123")
assert same.status_code == 200 and same.json()["duplicate"]
assert buy(rid, base.alice, tier2, 1, "invalid123").status_code == 409
assert buy(rid, base.alice, tier2, 4, "limit1234").status_code == 409
assert buy(rid, base.bob, tier2, 1, "bob-buy12").status_code == 200
assert buy(rid, base.bob, tier1, 2, "bob-buy13").status_code == 200
assert act(lottery.owner_update, base.owner, rid, lottery.RoundInput.model_validate({
    "title": "Новые условия", "description": "Сменим цены после начала продаж",
    "mode": "automatic", "max_per_user": 4, "ends_at": (core.now_utc() + timedelta(hours=1)).isoformat(),
    "tiers": [{"name": "дорогой", "price": 999, "weight": 100}],
    "prizes": [{"title": "приз", "amount": 120, "quantity": 1}],
})).status_code == 409
detail = act(lottery.lottery_detail, base.alice, rid).json()["round"]
assert detail["my_tickets"] == 1 and detail["my_spent"] == 50
assert "participants" not in detail
assert "mode" not in detail
assert "weight" not in detail["tiers"][0]
assert act(lottery.lottery_detail, base.owner, rid).json()["round"]["mode"] == "manual"
assert act(lottery.lottery_detail, base.owner, rid).json()["round"]["tiers"][0]["weight"] == 1
assert act(lottery.owner_close, base.owner, rid).json()["status"] == "closed"
assert buy(rid, base.alice, tier1, 1, "closed123").status_code == 409
prize = act(lottery.lottery_detail, base.owner, rid).json()["round"]["prizes"][0]
assignment = lottery.AssignInput(prize_id=prize["id"], slot=1, telegram_id=1001)
assert act(lottery.owner_assign, base.alice, rid, assignment).status_code == 403
assert act(lottery.owner_assign, base.owner, rid, assignment).status_code == 200
assert act(lottery.owner_assign, base.owner, rid, assignment).status_code == 409
assert act(lottery.owner_cancel, base.owner, rid).status_code == 409
assert act(lottery.owner_unassign, base.owner, rid, assignment).status_code == 200
assert act(lottery.owner_assign, base.owner, rid, assignment).status_code == 200
assert act(lottery.owner_finalize, base.owner, rid).json()["status"] == "drawn"
assert act(lottery.owner_finalize, base.owner, rid).status_code == 409
assert act(lottery.owner_unassign, base.owner, rid, assignment).status_code == 409

result = act(lottery.lottery_detail, base.alice, rid).json()["round"]
assert result["winners"][0]["is_me"]
assert "telegram_id" not in result["winners"][0]
with core.SessionLocal() as session:
    assert session.get(core.User, 1001).balance == 2070
    assert session.get(core.User, 1002).balance == 1750
    assert session.scalar(select(func.count()).select_from(lottery.LotteryAudit).where(
        lottery.LotteryAudit.round_id == rid)) >= 5
    rows = list(session.scalars(select(core.Transaction).where(
        core.Transaction.telegram_id == 1001,
        core.Transaction.operation_type.in_(["lottery_ticket", "lottery_prize"]))))
    assert sorted(tx.amount for tx in rows) == [-50, 120]

# Cancellation restores the exact purchase costs, never more than once.
cancel_round = create().json()["round"]
cancel_id = cancel_round["id"]
assert act(lottery.owner_activate, base.owner, cancel_id).status_code == 200
cost_before = 1750
assert buy(cancel_id, base.bob, cancel_round["tiers"][1]["id"], 2, "refund123").status_code == 200
assert act(lottery.owner_cancel, base.owner, cancel_id).json()["refunds"] == 1
assert act(lottery.owner_cancel, base.owner, cancel_id).status_code == 409
with core.SessionLocal() as session:
    assert session.get(core.User, 1002).balance == cost_before

# Automatic drawing uses ticket weights; user can win only once per round.
future = (core.now_utc() + timedelta(hours=1)).isoformat()
automatic = create(mode="automatic", end=future).json()["round"]
auto_id = automatic["id"]
auto_basic, auto_good = [tier["id"] for tier in automatic["tiers"]]
assert act(lottery.owner_activate, base.owner, auto_id).status_code == 200
assert buy(auto_id, base.alice, auto_basic, 1, "auto-alice").status_code == 200
assert buy(auto_id, base.bob, auto_good, 1, "auto-bob11").status_code == 200
lottery.secrets.randbelow = lambda total: total - 1
assert act(lottery.owner_close, base.owner, auto_id).json()["status"] == "drawn"
assert act(lottery.lottery_detail, base.bob, auto_id).json()["round"]["winners"][0]["is_me"]
assert act(lottery.owner_close, base.owner, auto_id).status_code == 409

# The scheduled settlement is safe to retry. It doesn't double-credit.
due = create(mode="automatic", end=future).json()["round"]
due_id = due["id"]
act(lottery.owner_activate, base.owner, due_id)
buy(due_id, base.alice, due["tiers"][0]["id"], 1, "due-alice")
with core.SessionLocal.begin() as session:
    session.get(lottery.LotteryRound, due_id).ends_at = core.now_utc() - timedelta(seconds=1)
lottery.process_due_rounds()
lottery.process_due_rounds()
assert act(lottery.lottery_detail, base.alice, due_id).json()["round"]["status"] == "drawn"
with core.SessionLocal() as session:
    assert session.scalar(select(func.count()).select_from(core.Transaction).where(
        core.Transaction.operation_type == "lottery_prize")) == 3

print("PASS: owner permissions, purchases, idempotency, manual and automatic draws, payouts, refunds, schedule")
