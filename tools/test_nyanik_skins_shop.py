"""Isolated tests: no live PostgreSQL, bot, wallet balances or notifications."""

from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
import types
from datetime import datetime, timezone
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, LargeBinary, String, Text, func, select
from sqlalchemy.orm import Mapped, mapped_column


ROOT = Path(__file__).resolve().parents[1]
temporary = tempfile.TemporaryDirectory(prefix="nyanik-shop-test-")
os.environ["BOT_TOKEN"] = "nyanik-test-only-token"
os.environ["OWNER_TELEGRAM_ID"] = "900000"
os.environ["DATABASE_URL"] = "sqlite:///" + str(Path(temporary.name) / "wallet.sqlite")

package = types.ModuleType("server")
package.__path__ = [str(ROOT / "server")]
sys.modules["server"] = package


def load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "server" / filename)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


core = load("server.backend_app", "backend_app.py")


class WalletSkin(core.Base):
    __tablename__ = "wallet_skins"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text)
    text_theme: Mapped[str] = mapped_column(String(12))
    image_mime: Mapped[str] = mapped_column(String(32))
    image_data: Mapped[bytes] = mapped_column(LargeBinary)
    image_sha256: Mapped[str] = mapped_column(String(64))
    image_width: Mapped[int] = mapped_column(Integer)
    image_height: Mapped[int] = mapped_column(Integer)
    is_template: Mapped[bool] = mapped_column(Boolean)
    is_active: Mapped[bool] = mapped_column(Boolean)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class UserWalletSkin(core.Base):
    __tablename__ = "user_wallet_skins"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.telegram_id"))
    skin_id: Mapped[int] = mapped_column(Integer, ForeignKey("wallet_skins.id"))
    is_active: Mapped[bool] = mapped_column(Boolean)
    acquired_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


def assign_skin_to_user(session, user_id, skin, timestamp):
    for row in session.scalars(select(UserWalletSkin).where(UserWalletSkin.telegram_id == user_id)):
        row.is_active = False
    result = UserWalletSkin(telegram_id=user_id, skin_id=skin.id, is_active=True, acquired_at=timestamp)
    session.add(result)
    return result


class WalletNotification(core.Base):
    __tablename__ = "wallet_notifications"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.telegram_id"))
    kind: Mapped[str] = mapped_column(String(40))
    title: Mapped[str] = mapped_column(String(120))
    body: Mapped[str] = mapped_column(Text)
    is_read: Mapped[bool] = mapped_column(Boolean)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class BlockedUser(core.Base):
    __tablename__ = "blocked_users"
    telegram_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.telegram_id"), primary_key=True)
    reason: Mapped[str] = mapped_column(Text)
    blocked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


appeals = types.ModuleType("server.appeals")
appeals.WalletSkin = WalletSkin
appeals.assign_skin_to_user = assign_skin_to_user
sys.modules["server.appeals"] = appeals
advanced = types.ModuleType("server.advanced_features")
advanced.WalletNotification = WalletNotification
sys.modules["server.advanced_features"] = advanced
bans = types.ModuleType("server.user_bans")
bans.BlockedUser = BlockedUser
sys.modules["server.user_bans"] = bans

shop = load("server.nyanik_skins_shop", "nyanik_skins_shop.py")
core.Base.metadata.create_all(core.engine)
now = datetime.now(timezone.utc)
with core.SessionLocal.begin() as session:
    for uid in range(10001, 10010):
        session.add(core.User(
            telegram_id=uid, first_name="Тест", last_name=None,
            username=None, balance=600 if uid != 10009 else 250,
            created_at=now, last_seen_at=now,
        ))
    session.add(BlockedUser(telegram_id=10008, reason="test", blocked_at=now))

core.verify_init_data = lambda token: {"id": int(token), "first_name": "Тест"}
shop.register_nyanik_skins_shop(core.app)
shop._seed()  # repeated startup must never mint inventory


def buy(user, sku, key):
    return shop.buy(shop.BuySkin(sku=sku, request_key=key), x_telegram_init_data=str(user))


def fails(fn, code):
    try:
        fn()
    except HTTPException as exc:
        assert exc.status_code == code, (exc.status_code, code)
    else:
        raise AssertionError(f"Expected HTTP {code}")


initial = shop.catalog()
assert initial["ready"] and len(initial["items"]) == 4
assert {item["remaining"] for item in initial["items"]} == {6}
assert {item["price"] for item in initial["items"]} == {500}
assert shop.status(x_telegram_init_data="10001")["balance"] == 600
assert shop.status(x_telegram_init_data="10008")["blocked"] is True

first = buy(10001, "moon_sail", "request_abcdefghijklmnop1")
assert first["balance"] == 100 and first["remaining"] == 5
assert buy(10001, "moon_sail", "request_abcdefghijklmnop1")["repeated"] is True
fails(lambda: buy(10001, "moon_sail", "request_abcdefghijklmnop2"), 409)
fails(lambda: buy(10001, "lighthouse", "request_abcdefghijklmnop3"), 409)
fails(lambda: buy(10001, "arch", "request_abcdefghijklmnop1"), 409)
fails(lambda: buy(10008, "arch", "request_abcdefghijklmnop4"), 403)
fails(lambda: buy(10009, "arch", "request_abcdefghijklmnop5"), 409)
fails(lambda: buy(10007, "missing", "request_abcdefghijklmnop6"), 404)
fails(lambda: buy(10007, "arch", "abcdefghijklmnop!"), 422)

for uid in range(10002, 10007):
    result = buy(uid, "moon_sail", f"request_{uid}_abcdefghijklmnop")
    assert result["remaining"] == 10006 - uid
fails(lambda: buy(10007, "moon_sail", "request_abcdefghijklmno9"), 409)

with core.SessionLocal() as session:
    assert session.get(core.User, 10001).balance == 100
    assert session.get(core.User, 10007).balance == 600
    assert session.get(core.User, 10008).balance == 600
    assert session.get(core.User, 10009).balance == 250
    assert session.scalar(select(func.count()).select_from(core.Transaction)) == 6
    assert session.scalar(select(func.count()).select_from(shop.NyanikSkinPurchase)) == 6
    assert session.scalar(select(func.count()).select_from(WalletNotification)) == 6
    assert session.scalar(select(func.count()).select_from(UserWalletSkin)) == 6
    assert session.scalar(select(func.count()).select_from(WalletSkin)) == 4
    assert all(row.is_active for row in session.scalars(select(UserWalletSkin)))

shop._seed()
assert [item["remaining"] for item in shop.catalog()["items"]] == [0, 6, 6, 6]
assert shop.status(x_telegram_init_data="10001")["items"][0]["purchased"] is True
print("Nyanik skins: 4×6 inventory, atomic debit, equip, duplicate protection and bans OK")
temporary.cleanup()
