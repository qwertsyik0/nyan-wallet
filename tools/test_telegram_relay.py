"""Offline tests of SprintHost outbox leases, auth, and financial atomicity.

Only an in-memory SQLite database is used: no actual bot sends or credits.
"""

import importlib.util
import os
import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException
from sqlalchemy import BigInteger, DateTime, Integer, String, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from sqlalchemy.pool import StaticPool


ROOT = Path(__file__).resolve().parents[1]
SECRET = "f" * 64
os.environ["NYAN_TELEGRAM_RELAY_SECRET"] = SECRET


class Base(DeclarativeBase):
    pass


class Transaction(Base):
    __tablename__ = "transactions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger)
    amount: Mapped[int] = mapped_column(Integer)
    operation_type: Mapped[str] = mapped_column(String(64))
    description: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
core = types.ModuleType("server.backend_app")
core.Base = Base
core.engine = engine
core.SessionLocal = SessionLocal
core.Transaction = Transaction
core.OWNER_TELEGRAM_ID = 1

package = types.ModuleType("server")
package.__path__ = [str(ROOT / "server")]
package.backend_app = core
sys.modules["server"] = package
sys.modules["server.backend_app"] = core

spec = importlib.util.spec_from_file_location("server.telegram_relay", ROOT / "server/telegram_relay.py")
relay = importlib.util.module_from_spec(spec)
sys.modules["server.telegram_relay"] = relay
spec.loader.exec_module(relay)

app = FastAPI()
relay.register_telegram_relay(app)
Base.metadata.create_all(engine)

def status(secret=SECRET):
    return relay.relay_status(x_nyan_relay_secret=secret)


def pull(secret=SECRET):
    return relay.pull_messages(limit=20, x_nyan_relay_secret=secret)


def ack(data, secret=SECRET):
    return relay.acknowledge_message(
        payload=relay.Ack(**data), x_nyan_relay_secret=secret
    )


def rejects(func, code):
    try:
        func()
    except HTTPException as exc:
        assert exc.status_code == code
    else:
        raise AssertionError(f"Expected HTTP {code}")


rejects(lambda: status(None), 401)
rejects(lambda: pull("bad"), 401)

with SessionLocal.begin() as session:
    session.add(Transaction(
        telegram_id=202, amount=200, operation_type="quote_reflection_reward",
        description="участие в интерактиве", created_at=datetime.now(timezone.utc),
    ))

with SessionLocal() as session:
    rows = session.scalars(select(relay.TelegramRelayMessage).order_by(relay.TelegramRelayMessage.id)).all()
    assert len(rows) == 2, "One user and one owner notice per committed ledger entry"
    assert rows[0].chat_id == 202 and "+200" in rows[0].body
    assert rows[1].chat_id == 1
    assert all(row.state == "pending" for row in rows)

# A failed/rolled-back balance operation must not create any relay message.
try:
    with SessionLocal.begin() as session:
        session.add(Transaction(
            telegram_id=202, amount=-992, operation_type="owner_debit",
            description="test rollback", created_at=datetime.now(timezone.utc),
        ))
        session.flush()
        raise RuntimeError("rollback")
except RuntimeError:
    pass

with SessionLocal() as session:
    assert len(session.scalars(select(relay.TelegramRelayMessage)).all()) == 2

report = status()
assert report["counts"] == {"pending": 2}

claimed = pull()
items = claimed["items"]
assert len(items) == 2
assert pull()["items"] == []

first = items[0]
rejects(lambda: ack({
    "id": first["id"], "lease_token": "0" * 40, "delivered": True,
}), 409)

sent = ack({
    "id": first["id"], "lease_token": first["lease_token"],
    "delivered": True, "telegram_message_id": 987,
})
assert sent["state"] == "sent"
assert ack({
    "id": first["id"], "lease_token": first["lease_token"], "delivered": True,
})["state"] == "sent"

second = items[1]
retry = ack({
    "id": second["id"], "lease_token": second["lease_token"],
    "delivered": False, "error": "temporary failure",
})
assert retry["state"] == "pending"
assert pull()["items"] == []

with SessionLocal.begin() as session:
    row = session.get(relay.TelegramRelayMessage, second["id"])
    row.retry_at = datetime.now(timezone.utc) - timedelta(seconds=1)

retry_items = pull()["items"]
assert len(retry_items) == 1
assert retry_items[0]["lease_token"] != second["lease_token"]
rejects(lambda: ack({
    "id": second["id"], "lease_token": second["lease_token"], "delivered": True,
}), 409)

assert ack({
    "id": second["id"], "lease_token": retry_items[0]["lease_token"],
    "delivered": False, "permanent_failure": True, "error": "bot blocked",
})["state"] == "failed"

relay.queue_message(202, "Проверка обычного уведомления")
with SessionLocal() as session:
    latest = session.scalars(select(relay.TelegramRelayMessage).order_by(relay.TelegramRelayMessage.id.desc())).first()
    assert latest.body == "Проверка обычного уведомления"
    assert latest.state == "pending"

print("PASS: relay transactions atomic, owner/user messages, auth, lease, ACK, retries, generic queue")
