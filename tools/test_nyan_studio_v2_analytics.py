"""Offline regression checks against a disposable SQLite wallet.

Running this file never connects to production or sends Telegram messages.
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlencode

from sqlalchemy import select


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("studio_base_test", ROOT / "tools/test_interactive_builder_profile.py")
base = importlib.util.module_from_spec(spec)
sys.modules["studio_base_test"] = base
spec.loader.exec_module(base)

core, studio, client = base.core, base.studio, base.client
owner, alice, bob = base.owner, base.alice, base.bob
finance = base.load("server.finance_analytics", "finance_analytics.py")
finance.register_finance_analytics(core.app)
core.app.openapi_schema = None
assert "/api/owner/finance-analytics" in core.app.openapi()["paths"]


def create_closed(*, starts_at=None, reward=0, testers=None):
    data = {
        "title": "Закрытая проверка Nyan Studio",
        "description": "Проверяем доступ только приглашённых участников.",
        "prompt": "Придумай название магазина Няника и объясни свой вариант.",
        "kind": "manual", "correct_answer": None,
        "reward": reward, "max_winners": 5, "ends_at": None,
        "visibility": "closed", "tester_ids": testers if testers is not None else [1001],
        "starts_at": starts_at,
    }
    response = client.post("/api/owner/activities", headers=owner, json=data)
    return response, data


future = (core.now_utc() + timedelta(days=1)).isoformat()
scheduled, settings = create_closed(starts_at=future)
assert scheduled.status_code == 200, scheduled.text
activity_id = scheduled.json()["activity"]["id"]
assert client.get(f"/api/activities/{activity_id}", headers=alice).status_code == 404
assert client.get(f"/api/activities/{activity_id}", headers=bob).status_code == 404
assert client.get(f"/api/activities/{activity_id}", headers=owner).status_code == 200
assert base.post(f"/api/owner/activities/{activity_id}/status", owner, {"action": "publish"}).status_code == 200
assert not any(x["id"] == activity_id for x in client.get("/api/activities", headers=alice).json()["activities"])
assert base.post(f"/api/activities/{activity_id}/answer", alice, {"answer": "Это мой длинный тестовый ответ"}).status_code == 409

# Before publishing, the owner can move the start time into the past.
ready, data = create_closed()
assert ready.status_code == 200, ready.text
ready_id = ready.json()["activity"]["id"]
assert ready.json()["activity"]["tester_ids"] == [1001]
assert base.post(f"/api/owner/activities/{ready_id}/status", owner, {"action": "publish"}).status_code == 200
assert client.get(f"/api/activities/{ready_id}", headers=bob).status_code == 404
assert base.post(f"/api/activities/{ready_id}/answer", bob, {"answer": "Я прохожу тест"}).status_code == 404
detail = client.get(f"/api/activities/{ready_id}", headers=alice).json()["activity"]
assert "tester_ids" not in detail and "correct_answer" not in detail
assert any(x["id"] == ready_id for x in client.get("/api/activities", headers=alice).json()["activities"])
assert not any(x["id"] == ready_id for x in client.get("/api/activities", headers=bob).json()["activities"])
posted = base.post(f"/api/activities/{ready_id}/answer", alice, {"answer": "Назову его магазином лучших лапок"})
assert posted.status_code == 200 and posted.json()["answer"]["status"] == "pending"
answer_id = posted.json()["answer"]["id"]
assert base.post(f"/api/owner/activities/{ready_id}/answers/{answer_id}/review", owner, {"decision": "approve"}).status_code == 200
assert base.post(f"/api/activities/{ready_id}/answer", alice, {"answer": "Вторая попытка запрещена"}).status_code == 409
assert create_closed(reward=1)[0].status_code == 400
assert create_closed(testers=[])[0].status_code == 400
assert create_closed(testers=[-2])[0].status_code == 400


def stats(days=0, headers=owner):
    return base.DirectClient.invoke(finance.finance_analytics, days=days,
        x_telegram_init_data=base.DirectClient.token(headers))


assert stats(headers=alice).status_code == 403
assert stats(headers=None).status_code == 401
assert stats(days=3).status_code == 422
before = stats().json()
assert before["ok"] and len(before["daily"]) == 30

# Transfers are ledger movements, not new paw issuance. Simulate the paired
# transfer rows and consistent user balance changes in the test-only DB.
with core.SessionLocal.begin() as session:
    first = session.get(core.User, 1001)
    second = session.get(core.User, 1002)
    first.balance -= 10
    second.balance += 10
    session.add_all([
        core.Transaction(telegram_id=1001, amount=-10, operation_type="transfer_out",
                         description="тест", created_at=core.now_utc()),
        core.Transaction(telegram_id=1002, amount=10, operation_type="transfer_in",
                         description="тест", created_at=core.now_utc()),
    ])
after = stats().json()
assert after["wallets"]["balance_in_circulation"] == before["wallets"]["balance_in_circulation"]
assert after["transactions"]["credited_excluding_transfers"] == before["transactions"]["credited_excluding_transfers"]
assert after["transactions"]["debited_excluding_transfers"] == before["transactions"]["debited_excluding_transfers"]
assert after["transactions"]["transfer_volume"] == before["transactions"]["transfer_volume"] + 10
assert after["transactions"]["transfers_count"] == before["transactions"]["transfers_count"] + 1

# The existing durable relay queue is reused for moderation. No HTTP request
# and no Telegram delivery takes place in this test.
os.environ["NYAN_TELEGRAM_RELAY_SECRET"] = "a" * 64
relay = base.load("server.telegram_relay", "telegram_relay.py") if "server.telegram_relay" not in sys.modules else sys.modules["server.telegram_relay"]
relay.register_telegram_relay(core.app)
notify, _ = create_closed()
assert notify.status_code == 200
notify_id = notify.json()["activity"]["id"]
assert base.post(f"/api/owner/activities/{notify_id}/status", owner, {"action": "publish"}).status_code == 200
response = base.post(f"/api/activities/{notify_id}/answer", alice, {"answer": "Хочу назвать магазин лапконыч"})
assert response.status_code == 200
row_id = response.json()["answer"]["id"]
assert base.post(f"/api/owner/activities/{notify_id}/answers/{row_id}/review", owner, {"decision": "reject"}).status_code == 200
with core.SessionLocal() as session:
    notices = session.scalars(select(relay.TelegramRelayMessage).where(
        relay.TelegramRelayMessage.source_key.like(f"studio:answer:{row_id}:%")
    )).all()
    assert len(notices) == 2
    assert {n.chat_id for n in notices} == {999999, 1001}
assert base.post(f"/api/owner/activities/{notify_id}/answers/{row_id}/review", owner, {"decision": "reject"}).status_code == 409

print("PASS: closed testers, scheduled starts, owner isolation, no test payouts, analytics transfer accounting, relay notices")
