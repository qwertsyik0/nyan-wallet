"""Isolated VIP regression tests without touching production PostgreSQL."""
from __future__ import annotations

import importlib.util
import re
import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, Text, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    telegram_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    balance: Mapped[int] = mapped_column(Integer, default=0)


class SpendRequest(Base):
    __tablename__ = "spend_requests"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.telegram_id"))
    reward_title: Mapped[str] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(20))


class Transaction(Base):
    __tablename__ = "transactions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.telegram_id"))
    amount: Mapped[int] = mapped_column(Integer)
    operation_type: Mapped[str] = mapped_column(String(50))
    description: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class WalletNotification(Base):
    __tablename__ = "wallet_notifications"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.telegram_id"))
    kind: Mapped[str] = mapped_column(String(40))
    title: Mapped[str] = mapped_column(String(120))
    body: Mapped[str] = mapped_column(Text)
    is_read: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


pkg = types.ModuleType("server")
pkg.__path__ = [str(Path(__file__).resolve().parents[1] / "server")]
core = types.ModuleType("server.backend_app")
core.Base = Base
core.User = User
core.Transaction = Transaction
core.BOT_TOKEN = "test"
core.engine = create_engine("sqlite+pysqlite:///:memory:")
core.SessionLocal = sessionmaker(bind=core.engine, expire_on_commit=False)
ext = types.ModuleType("server.extended_features")
ext.SpendRequest = SpendRequest
ext.Reward = None
advanced = types.ModuleType("server.advanced_features")
advanced.WalletNotification = WalletNotification
sys.modules.update({
    "server": pkg,
    "server.backend_app": core,
    "server.extended_features": ext,
    "server.advanced_features": advanced,
})
pkg.backend_app = core

source = Path(__file__).resolve().parents[1] / "server" / "vip.py"
spec = importlib.util.spec_from_file_location("server.vip", source)
vip = importlib.util.module_from_spec(spec)
sys.modules["server.vip"] = vip
spec.loader.exec_module(vip)
Base.metadata.create_all(core.engine)

assert vip.is_vip_reward("Статус «VIP» на 30 дней")
assert vip.is_vip_reward("статус VIP на 30 дней")
assert vip.is_vip_reward("VIP на 30 дней")
assert not vip.is_vip_reward("VIP")
assert not vip.is_vip_reward("Ранг VIP")
assert not vip.is_vip_reward("Статус VIP на 365 дней")

t0 = datetime(2026, 11, 22, 12, tzinfo=timezone.utc)
with core.SessionLocal() as session:
    with session.begin():
        session.add(User(telegram_id=100, balance=5000))
        session.add(SpendRequest(
            id=1, telegram_id=100,
            reward_title="Статус «VIP» на 30 дней", status="fulfilled"
        ))

    with session.begin():
        a = vip.activate_vip(session, 1, 100, t0)
        b = vip.activate_vip(session, 1, 100, t0)
        assert a.request_id == b.request_id == 1
        session.add(vip.VipPurchaseToken(
            telegram_id=100,
            token="1234567890abcdef",
            request_id=1,
            created_at=t0,
        ))

    with session.begin():
        assert session.get(vip.VipPurchaseToken, (100, "1234567890abcdef")).request_id == 1

    with session.begin():
        assert vip.status_for_user(session, 100, t0)["active"]
        assert vip.credit_due_for_user(session, 100, t0 + timedelta(days=6)) == 0

    for index, day in enumerate((7, 14, 21, 28), start=1):
        with session.begin():
            stamp = t0 + timedelta(days=day)
            assert vip.credit_due_for_user(session, 100, stamp) == 25
            assert vip.credit_due_for_user(session, 100, stamp) == 0
            assert vip.status_for_user(session, 100, stamp)["weekly_paid_in_term"] == 25 * index

    with session.begin():
        assert session.get(User, 100).balance == 5100
        assert len(session.scalars(select(vip.VipWeeklyCredit)).all()) == 4
        assert len(session.scalars(select(Transaction)).all()) == 4
        assert not vip.status_for_user(session, 100, t0 + timedelta(days=30))["active"]
        assert vip.credit_due_for_user(session, 100, t0 + timedelta(days=31)) == 0

    with session.begin():
        session.add(SpendRequest(
            id=2, telegram_id=100, reward_title="Статус VIP на 30 дней",
            status="fulfilled"
        ))
    with session.begin():
        extension = vip.activate_vip(session, 2, 100, t0 + timedelta(days=10))
        assert vip.aware(extension.starts_at) == t0 + timedelta(days=30)
        assert vip.aware(extension.ends_at) == t0 + timedelta(days=60)
        assert vip.status_for_user(session, 100, t0 + timedelta(days=35))["active"]

    with session.begin():
        session.add(SpendRequest(
            id=3, telegram_id=100, reward_title="Статус VIP на 30 дней",
            status="fulfilled"
        ))
    with session.begin():
        extension = vip.activate_vip(session, 3, 100, t0 + timedelta(days=10))
        assert vip.aware(extension.ends_at) == t0 + timedelta(days=90)

    from fastapi import HTTPException
    with session.begin():
        try:
            vip.check_renewal_capacity(session, 100, t0 + timedelta(days=10))
        except HTTPException as exc:
            assert exc.status_code == 409
        else:
            raise AssertionError("Renewal cap was not enforced")

root = Path(__file__).resolve().parents[1]
init = (root / "server/__init__.py").read_text()
ext_source = (root / "server/extended_features.py").read_text()
adv_source = (root / "server/advanced_features.py").read_text()
identity_source = (root / "server/nyan_id.py").read_text()
assert "register_vip(backend_app.app)" in init
assert "activate_vip(session, item.id" in ext_source
assert "X-VIP-Purchase-Key" in ext_source
assert "VipPurchaseToken" in ext_source
assert "vip_purchase_key=" in (root / "vip.js").read_text()
assert "vip_purchase_key:" in ext_source
assert "activate_vip(session, item.id" in adv_source
assert '"vip": status_for_user(session, user.telegram_id)' in identity_source
assert 'vip.js?v=' in (root / "index.html").read_text()
assert 'nyid-vip-active' in (root / "nyan_id.js").read_text()
assert 'is_vip_subscription' in (root / "advanced_features.js").read_text()

print("VIP purchase hooks, 30-day renewal, weekly bonus and idempotency: OK")
