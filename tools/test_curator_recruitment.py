"""Offline curator recruitment tests with an isolated SQLite wallet copy.

No real balances, Telegram messages, or FirstVDS resources are touched.
"""

from __future__ import annotations

import hashlib
import hmac
import importlib.util
import json
import os
import sys
import tempfile
import time
import types
from pathlib import Path
from urllib.parse import urlencode

from fastapi import HTTPException
from sqlalchemy import func, select


ROOT = Path(__file__).resolve().parents[1]
TEMP = tempfile.TemporaryDirectory(prefix="nyan-curator-test-")
os.environ["BOT_TOKEN"] = "nyan-curator-test-token"
os.environ["OWNER_TELEGRAM_ID"] = "999999"
os.environ["DATABASE_URL"] = "sqlite:///" + str(Path(TEMP.name) / "test.db")
os.environ["NYAN_TELEGRAM_RELAY_SECRET"] = "c" * 64

package = types.ModuleType("server")
package.__path__ = [str(ROOT / "server")]
sys.modules["server"] = package


def load(name: str, file: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "server" / file)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


core = load("server.backend_app", "backend_app.py")
relay = load("server.telegram_relay", "telegram_relay.py")
curator = load("server.curator_recruitment", "curator_recruitment.py")
relay.register_telegram_relay(core.app)
curator.register_curator_recruitment(core.app)


def token(uid: int) -> str:
    fields = {"auth_date": str(int(time.time())),
              "user": json.dumps({"id": uid, "username": f"test_{uid}", "first_name": "Nyan Test"})}
    check = "\n".join(f"{key}={value}" for key, value in sorted(fields.items()))
    secret = hmac.new(b"WebAppData", os.environ["BOT_TOKEN"].encode(), hashlib.sha256).digest()
    fields["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(fields)


def rejects(fn, code: int) -> None:
    try:
        fn()
    except HTTPException as exc:
        assert exc.status_code == code, (exc.status_code, exc.detail)
    else:
        raise AssertionError(f"Expected HTTP {code}")


def payload() -> curator.ApplyRequest:
    return curator.ApplyRequest(
        display_name="Тестовый кандидат", age=17,
        timezone="МСК (UTC+3)", availability="2–4 часа по вечерам",
        answers={key: f"Самостоятельное решение {key}: проверю факты, сохраню доказательства, согласую риски с владельцем и сообщу результат."
                 for key in curator.ANSWER_KEYS},
        rules_accepted=True,
    )


assert "/api/recruitment/curator/apply" in core.app.openapi()["paths"]
assert "/api/owner/recruitment/curator/{application_id}/review" in core.app.openapi()["paths"]
rejects(lambda: curator.my_application(x_telegram_init_data=""), 401)
assert curator.my_application(x_telegram_init_data=token(123))["application"] is None
rejects(lambda: curator.list_applications(status="all", x_telegram_init_data=token(123)), 403)

invalid = payload()
invalid.answers["payroll"] = "Не знаю"
rejects(lambda: curator.submit_application(invalid, x_telegram_init_data=token(123)), 422)
invalid.answers = {"experience": "x" * 50, **{key: "y" * 50 for key in list(curator.ANSWER_KEYS)[1:-1]}, "unexpected": "z" * 50}
rejects(lambda: curator.submit_application(invalid, x_telegram_init_data=token(123)), 422)

created = curator.submit_application(payload(), x_telegram_init_data=token(123))["application"]
app_id = created["id"]
assert created["status"] == "pending"
assert "owner_note" not in created and "answers" not in created
rejects(lambda: curator.submit_application(payload(), x_telegram_init_data=token(123)), 409)

with core.SessionLocal() as session:
    assert session.get(core.User, 123).balance == 0
    assert session.scalar(select(func.count()).select_from(core.Transaction)) == 0
    assert session.scalar(select(func.count()).select_from(curator.CuratorApplication)) == 1
    rows = session.scalars(select(relay.TelegramRelayMessage)).all()
    assert len(rows) == 1
    assert rows[0].chat_id == 999999 and rows[0].source_key == f"curator:application:{app_id}:owner"
    assert "curator_review" in rows[0].body

rejects(lambda: curator.get_application(app_id, x_telegram_init_data=token(123)), 403)
rejects(lambda: curator.review_application(app_id, curator.ReviewRequest(decision="rejected", score=30), x_telegram_init_data=token(123)), 403)
owners = curator.list_applications(status="pending", x_telegram_init_data=token(999999))["applications"]
assert len(owners) == 1 and owners[0]["id"] == app_id
assert "answers" not in owners[0]
full = curator.get_application(app_id, x_telegram_init_data=token(999999))["application"]
assert set(full["answers"]) == set(curator.ANSWER_KEYS)
assert full["age"] == 17 and full["username"] == "test_123"
rejects(lambda: curator.list_applications(status="bogus", x_telegram_init_data=token(999999)), 400)

review = curator.ReviewRequest(
    decision="interview", score=84,
    owner_note="Личное замечание, не отправлять кандидату",
    candidate_note="Свяжемся для собеседования",
)
decided = curator.review_application(app_id, review, x_telegram_init_data=token(999999))["application"]
assert decided["status"] == "interview"
assert decided["candidate_note"] == "Свяжемся для собеседования"
rejects(lambda: curator.review_application(app_id, review, x_telegram_init_data=token(999999)), 409)
public = curator.my_application(x_telegram_init_data=token(123))["application"]
assert public["status"] == "interview"
assert "owner_note" not in public and "owner_score" not in public

with core.SessionLocal() as session:
    assert session.get(core.User, 123).balance == 0
    assert session.scalar(select(func.count()).select_from(core.Transaction)) == 0
    rows = session.scalars(select(relay.TelegramRelayMessage).order_by(relay.TelegramRelayMessage.id)).all()
    assert len(rows) == 2
    assert rows[1].chat_id == 123 and rows[1].source_key == f"curator:application:{app_id}:result"
    assert "Личное замечание" not in rows[1].body

# Rejection is also terminal, and accounts cannot reapply after rejection.
second = curator.submit_application(payload(), x_telegram_init_data=token(456))["application"]
curator.review_application(second["id"], curator.ReviewRequest(decision="rejected", score=22), x_telegram_init_data=token(999999))
rejects(lambda: curator.submit_application(payload(), x_telegram_init_data=token(456)), 409)
assert len(curator.list_applications(status="all", x_telegram_init_data=token(999999))["applications"]) == 2
assert curator.list_applications(status="pending", x_telegram_init_data=token(999999))["applications"] == []

print("PASS: one-time curator applications, 15 fields, private review, status, relay, no wallet mutations")
TEMP.cleanup()
