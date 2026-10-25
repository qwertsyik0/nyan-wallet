"""Isolated API and accounting tests. Never touches production or Telegram."""

from __future__ import annotations

import hashlib
import hmac
import importlib.util
import json
import os
import re
import sys
import tempfile
import time
import types
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, select
from sqlalchemy.orm import Mapped, mapped_column



ROOT = Path(__file__).resolve().parents[1]
TEMP = tempfile.TemporaryDirectory(prefix="nyan-studio-tests-")
os.environ["BOT_TOKEN"] = "nyan-studio-test-token"
os.environ["OWNER_TELEGRAM_ID"] = "999999"
os.environ["DATABASE_URL"] = "sqlite:///" + str(Path(TEMP.name) / "test.db")
package = types.ModuleType("server")
package.__path__ = [str(ROOT / "server")]
sys.modules["server"] = package


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / "server" / filename)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


core = load("server.backend_app", "backend_app.py")


class BlockedUser(core.Base):
    __tablename__ = "blocked_users"
    telegram_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.telegram_id"), primary_key=True)


class AchievementUnlock(core.Base):
    __tablename__ = "achievement_unlocks"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.telegram_id"))


class Appeal(core.Base):
    __tablename__ = "appeals"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.telegram_id"))
    public_id: Mapped[str | None] = mapped_column(String(24), nullable=True)
    status: Mapped[str] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


for name, attrs in [
    ("server.user_bans", {"BlockedUser": BlockedUser}),
    ("server.achievements", {"AchievementUnlock": AchievementUnlock}),
    ("server.appeals", {"Appeal": Appeal}),
]:
    mod = types.ModuleType(name)
    mod.__dict__.update(attrs)
    sys.modules[name] = mod

ideas = load("server.interactive_ideas", "interactive_ideas.py")
studio = load("server.interactive_builder", "interactive_builder.py")
profile = load("server.profile_overview", "profile_overview.py")
core.Base.metadata.create_all(core.engine)
studio.register_interactive_builder(core.app)
profile.register_profile_overview(core.app)
assert {
    "/api/profile/overview", "/api/activities", "/api/activities/{activity_id}",
    "/api/activities/{activity_id}/answer", "/api/owner/activities",
    "/api/owner/activities/{activity_id}/edit",
    "/api/owner/activities/{activity_id}/status",
    "/api/owner/activities/{activity_id}/answers",
    "/api/owner/activities/{activity_id}/answers/{answer_id}/review",
}.issubset(core.app.openapi()["paths"])

class Response:
    def __init__(self, status_code, data):
        self.status_code = status_code
        self.data = data
        self.text = str(data)

    def json(self):
        return self.data


class DirectClient:
    """Invoke registered handler logic without an ASGI event loop or live DB."""
    @staticmethod
    def invoke(fn, *args, **kwargs):
        try:
            return Response(200, fn(*args, **kwargs))
        except HTTPException as exc:
            return Response(exc.status_code, {"detail": exc.detail})
        except ValidationError as exc:
            return Response(422, {"detail": str(exc)})

    @staticmethod
    def token(headers):
        return (headers or {}).get("X-Telegram-Init-Data")

    def get(self, path, headers=None, params=None):
        token = self.token(headers)
        params = params or {}
        if path == "/api/activities":
            return self.invoke(studio.list_activities, x_telegram_init_data=token)
        if path == "/api/profile/overview":
            return self.invoke(profile.profile_overview,
                               before_id=params.get("before_id"), limit=params.get("limit", 25),
                               x_telegram_init_data=token)
        if match := re.fullmatch(r"/api/activities/(\d+)", path):
            return self.invoke(studio.activity_detail, int(match[1]), x_telegram_init_data=token)
        if match := re.fullmatch(r"/api/owner/activities/(\d+)/answers", path):
            return self.invoke(studio.owner_activity_answers, int(match[1]), x_telegram_init_data=token)
        raise AssertionError(path)

    def post(self, path, headers=None, json=None):
        token = self.token(headers)
        data = json or {}
        if path == "/api/owner/activities":
            return self.invoke(studio.create_activity, studio.ActivityCreate.model_validate(data),
                               x_telegram_init_data=token)
        if match := re.fullmatch(r"/api/owner/activities/(\d+)/edit", path):
            return self.invoke(studio.edit_activity, int(match[1]), studio.ActivityCreate.model_validate(data),
                               x_telegram_init_data=token)
        if match := re.fullmatch(r"/api/owner/activities/(\d+)/status", path):
            return self.invoke(studio.set_activity_status, int(match[1]), studio.ActivityStatus.model_validate(data),
                               x_telegram_init_data=token)
        if match := re.fullmatch(r"/api/activities/(\d+)/answer", path):
            return self.invoke(studio.submit_answer, int(match[1]), studio.ActivitySubmit.model_validate(data),
                               x_telegram_init_data=token)
        if match := re.fullmatch(r"/api/owner/activities/(\d+)/answers/(\d+)/review", path):
            return self.invoke(studio.review_activity_answer, int(match[1]), int(match[2]),
                               studio.ActivityReview.model_validate(data),
                               x_telegram_init_data=token)
        raise AssertionError(path)


client = DirectClient()


def header(uid: int):
    fields = {
        "auth_date": str(int(time.time())),
        "user": json.dumps({"id": uid, "first_name": "Nyan Test"}, ensure_ascii=False),
    }
    signed = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    secret = hmac.new(b"WebAppData", os.environ["BOT_TOKEN"].encode(), hashlib.sha256).digest()
    fields["hash"] = hmac.new(secret, signed.encode(), hashlib.sha256).hexdigest()
    return {"X-Telegram-Init-Data": urlencode(fields)}


owner = header(999999)
alice = header(1001)
bob = header(1002)
blocked = header(1003)


def create(kind, *, reward=70, max_winners=2):
    kwargs = {
        "title": "Тайна исчезнувшей лапки",
        "description": "Разгадайте короткую загадку от Няника.",
        "prompt": "Какой вариант подходит?",
        "kind": kind, "choices": ["первый", "второй"] if kind == "choice" else [],
        "correct_answer": "1" if kind == "choice" else "няник" if kind == "text" else None,
        "reward": reward, "max_winners": max_winners, "ends_at": None,
    }
    response = client.post("/api/owner/activities", json=kwargs, headers=owner)
    assert response.status_code == 200, response.text
    return response.json()["activity"]["id"], kwargs


def post(path, user, payload):
    return client.post(path, headers=user, json=payload)


assert client.get("/api/activities").status_code == 401
assert post("/api/owner/activities", alice, {
    "title": "Проверка доступа", "description": "Только для владельца",
    "prompt": "Какой ответ верный?", "kind": "text",
    "correct_answer": "да", "reward": 1, "max_winners": 1,
}).status_code == 403
assert client.get("/api/profile/overview").status_code == 401
assert client.get("/api/profile/overview", headers=alice).status_code == 200

choice, form = create("choice")
assert client.get("/api/activities", headers=alice).json()["activities"] == []
assert client.get(f"/api/activities/{choice}", headers=alice).status_code == 404
assert post(f"/api/owner/activities/{choice}/edit", owner, form).status_code == 200
assert post(f"/api/owner/activities/{choice}/status", alice, {"action": "publish"}).status_code == 403
assert post(f"/api/owner/activities/{choice}/status", owner, {"action": "publish"}).status_code == 200
detail = client.get(f"/api/activities/{choice}", headers=alice).json()["activity"]
assert "correct_answer" not in detail
assert detail["choices"] == ["первый", "второй"]
assert post(f"/api/owner/activities/{choice}/edit", owner, form).status_code == 409
bad = post(f"/api/activities/{choice}/answer", alice, {"answer": "0"})
assert bad.status_code == 200 and bad.json()["answer"]["status"] == "rejected"
assert post(f"/api/activities/{choice}/answer", alice, {"answer": "1"}).status_code == 409
ok = post(f"/api/activities/{choice}/answer", bob, {"answer": "1"})
assert ok.status_code == 200 and ok.json()["answer"]["status"] == "approved"
assert post(f"/api/activities/{choice}/answer", bob, {"answer": "1"}).status_code == 409

manual, _ = create("manual", reward=120, max_winners=1)
assert post(f"/api/owner/activities/{manual}/status", owner, {"action": "publish"}).status_code == 200
answer = post(f"/api/activities/{manual}/answer", alice, {"answer": "Нарисовал плакат с Няником и загрузил его."})
assert answer.status_code == 200 and answer.json()["answer"]["status"] == "pending"
answer_id = answer.json()["answer"]["id"]
assert post(f"/api/owner/activities/{manual}/answers/{answer_id}/review", alice, {"decision": "approve"}).status_code == 403
approved = post(f"/api/owner/activities/{manual}/answers/{answer_id}/review", owner, {"decision": "approve"})
assert approved.status_code == 200 and approved.json()["answer"]["reward_amount"] == 120
assert post(f"/api/owner/activities/{manual}/answers/{answer_id}/review", owner, {"decision": "approve"}).status_code == 409
assert client.get(f"/api/activities/{manual}", headers=bob).status_code == 404

text_kind, _ = create("text", reward=30, max_winners=2)
assert post(f"/api/owner/activities/{text_kind}/status", owner, {"action": "publish"}).status_code == 200
assert post(f"/api/activities/{text_kind}/answer", alice, {"answer": " НЯНИК "}).json()["answer"]["status"] == "approved"
assert post(f"/api/activities/{text_kind}/answer", bob, {"answer": "другой ответ"}).json()["answer"]["status"] == "rejected"

with core.SessionLocal.begin() as session:
    session.add(BlockedUser(telegram_id=1001))
blocked_test, _ = create("manual")
assert post(f"/api/owner/activities/{blocked_test}/status", owner, {"action": "publish"}).status_code == 200
assert post(f"/api/activities/{blocked_test}/answer", alice, {"answer": "я сделал дополнительный тест"}).status_code == 403
with core.SessionLocal.begin() as session:
    session.delete(session.get(BlockedUser, 1001))

with core.SessionLocal.begin() as session:
    session.add(AchievementUnlock(id=1, telegram_id=1001))
    session.add(Appeal(id=1, telegram_id=1001, public_id="NWR-000001", status="new", created_at=core.now_utc()))
    for n in range(30):
        session.add(core.Transaction(
            telegram_id=1001, amount=1 if n % 2 == 0 else -1,
            operation_type="test", description="проверка истории", created_at=core.now_utc(),
        ))
overview = client.get("/api/profile/overview", headers=alice).json()
assert overview["operations_count"] == 32
assert overview["earned"] == 165 and overview["spent"] == 15, overview
assert overview["achievements_count"] == 1
assert overview["requests"][0]["id"] == "NWR-000001"
assert len(overview["transactions"]) == 25 and overview["next_cursor"]
page2 = client.get("/api/profile/overview",
                   params={"before_id": overview["next_cursor"]}, headers=alice).json()
assert len(page2["transactions"]) == 7 and page2["next_cursor"] is None
assert profile.profile_overview is not None

with core.SessionLocal() as session:
    assert session.get(core.User, 1001).balance == 150
    assert session.get(core.User, 1002).balance == 70
    rewards = session.scalars(select(core.Transaction).where(
        core.Transaction.operation_type == "interactive_activity_reward"
    )).all()
    assert len(rewards) == 3, rewards

print("PASS: owner auth, drafts, answers, moderation, blocked users, one-time rewards, wallet profile")
