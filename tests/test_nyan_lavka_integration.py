"""Isolated shop tests. No production credentials, database or Telegram calls."""
import ast
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import types
import unittest
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI, HTTPException
from sqlalchemy import BigInteger, Boolean, Column, DateTime, Integer, String, Text, create_engine, func, select
from sqlalchemy.orm import declarative_base, sessionmaker

ROOT = Path(__file__).resolve().parents[1]
Base = declarative_base()

class User(Base):
    __tablename__ = "users"
    telegram_id = Column(BigInteger, primary_key=True)
    balance = Column(Integer, nullable=False, default=0)
    username = Column(String, nullable=True)

class Transaction(Base):
    __tablename__ = "transactions"
    id = Column(Integer, primary_key=True, autoincrement=True)
    telegram_id = Column(BigInteger)
    amount = Column(Integer)
    operation_type = Column(String)
    description = Column(Text)
    created_at = Column(DateTime(timezone=True))

class Notification(Base):
    __tablename__ = "wallet_notifications_test"
    id = Column(Integer, primary_key=True, autoincrement=True)
    telegram_id = Column(BigInteger)
    kind = Column(String)
    title = Column(String)
    body = Column(Text)
    is_read = Column(Boolean)
    created_at = Column(DateTime(timezone=True))

class BlockedUser(Base):
    __tablename__ = "blocked_users_test"
    telegram_id = Column(BigInteger, primary_key=True)

package = types.ModuleType("server")
package.__path__ = [str(ROOT / "server")]
sys.modules["server"] = package
core = types.ModuleType("server.backend_app")
core.Base = Base
core.User = User
core.Transaction = Transaction
core.now_utc = lambda: datetime.now(timezone.utc)
core.apply_telegram_profile = lambda *args: None
core.is_owner = lambda user_id: user_id == 1

def verify(raw):
    if raw != "test-signed":
        raise HTTPException(status_code=401, detail="Invalid test signature")
    return {"id": 42}

core.verify_init_data = verify
core.require_owner = lambda user: None if user["id"] == 1 else (_ for _ in ()).throw(HTTPException(status_code=403))
sys.modules["server.backend_app"] = core
advanced = types.ModuleType("server.advanced_features")
advanced.WalletNotification = Notification
sys.modules[advanced.__name__] = advanced
bans = types.ModuleType("server.user_bans")
bans.BlockedUser = BlockedUser
sys.modules[bans.__name__] = bans
spec = importlib.util.spec_from_file_location("server.nyan_lavka", ROOT / "server/nyan_lavka.py")
shop = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = shop
spec.loader.exec_module(shop)

class ShopTest(unittest.TestCase):
    def setUp(self):
        core.engine = create_engine("sqlite:///:memory:")
        core.SessionLocal = sessionmaker(bind=core.engine, expire_on_commit=False)
        Base.metadata.create_all(core.engine)
        shop._REGISTERED = False
        shop._seed()
        with core.SessionLocal.begin() as session:
            session.add(User(telegram_id=42, balance=1000))

    def tearDown(self):
        core.engine.dispose()

    def open_item(self, sku):
        with core.SessionLocal.begin() as session:
            window = session.get(shop.LavkaWindow, 1)
            window.opened_at = core.now_utc() - timedelta(seconds=5)
            window.closes_at = core.now_utc() + timedelta(minutes=10)
            session.get(shop.LavkaItem, sku).total = 2

    def balances(self, sku):
        with core.SessionLocal() as session:
            return (session.get(User, 42).balance, session.get(shop.LavkaItem, sku).sold,
                    session.scalar(select(func.count()).select_from(Transaction)))

    def test_all_fourteen_items_seed_closed_with_zero_stock(self):
        data = shop.public_catalog()
        self.assertFalse(data["is_open"])
        self.assertFalse(data["has_opened"])
        self.assertEqual(len(data["items"]), 14)
        self.assertTrue(all(i["remaining"] == 0 for i in data["items"]))
        self.assertNotIn("balance", data)
        self.assertTrue(all("purchased" not in i for i in data["items"]))

    def test_new_product_purchase_is_idempotent_and_seed_preserves_it(self):
        self.open_item("crystal")
        payload = shop.BuyRequest(sku="crystal", request_key="lavka_test_request_000001")
        first = shop.buy(payload, "test-signed")
        again = shop.buy(payload, "test-signed")
        self.assertFalse(first["purchase"]["repeated"])
        self.assertTrue(again["purchase"]["repeated"])
        self.assertEqual(first["purchase"]["id"], again["purchase"]["id"])
        shop._seed()
        self.assertEqual(self.balances("crystal"), (550, 1, 1))
        with core.SessionLocal() as session:
            self.assertEqual(session.get(shop.LavkaItem, "crystal").total, 2)

    def test_insufficient_funds_rolls_back(self):
        self.open_item("potion")
        with core.SessionLocal.begin() as session:
            session.get(User, 42).balance = 100
        with self.assertRaises(HTTPException) as error:
            shop.buy(shop.BuyRequest(sku="potion", request_key="lavka_test_request_000002"), "test-signed")
        self.assertEqual(error.exception.status_code, 409)
        self.assertEqual(self.balances("potion"), (100, 0, 0))

    def test_closed_shop_and_unsigned_purchase_cannot_debit(self):
        payload = shop.BuyRequest(sku="time", request_key="lavka_test_request_000003")
        with self.assertRaises(HTTPException) as unsigned:
            shop.buy(payload, "")
        self.assertEqual(unsigned.exception.status_code, 401)
        with self.assertRaises(HTTPException) as closed:
            shop.buy(payload, "test-signed")
        self.assertEqual(closed.exception.status_code, 410)
        self.assertEqual(self.balances("time"), (1000, 0, 0))

    def test_blocked_user_cannot_purchase(self):
        self.open_item("charm")
        with core.SessionLocal.begin() as session:
            session.add(BlockedUser(telegram_id=42))
        with self.assertRaises(HTTPException) as error:
            shop.buy(shop.BuyRequest(sku="charm", request_key="lavka_test_request_000004"), "test-signed")
        self.assertEqual(error.exception.status_code, 403)
        self.assertEqual(self.balances("charm"), (1000, 0, 0))

    def test_registration_is_idempotent(self):
        app = FastAPI()
        shop.register_nyan_lavka(app)
        shop.register_nyan_lavka(app)
        routes = [route.path for route in app.routes if route.path.startswith("/api/nyan-lavka/")]
        self.assertEqual(len(routes), 8)
        self.assertEqual(len(set(routes)), 8)

    def test_client_catalog_prices_assets_and_main_app_route_match(self):
        source = (ROOT / "nyan-lavka.js").read_text()
        prefix = source.split("  const dialog =", 1)[0]
        prefix = prefix.split("  const goods =", 1)[1]
        snippet = "const goods =" + prefix + "\nconsole.log(JSON.stringify({goods, fallbackPrices}));"
        client = json.loads(subprocess.check_output(["node", "-e", snippet], text=True))
        server = {row[0]: row[3] for row in shop.CATALOG}
        self.assertEqual(client["fallbackPrices"], server)
        self.assertEqual({item["id"] for item in client["goods"]}, set(server))
        self.assertEqual(len(client["goods"]), 14)
        for item in client["goods"]:
            path = (ROOT / item["image"]).resolve()
            self.assertTrue(path.is_file(), str(path))
            self.assertEqual(path.suffix, ".svg")
        html = (ROOT / "nyan-lavka.html").read_text()
        self.assertIn("Художник иконок: Byllye$", html)
        self.assertNotIn("\U0001f43e", html + source)
        self.assertIn('"nyan_lavka"', (ROOT / "index.html").read_text())
        self.assertIn("register_nyan_lavka(backend_app.app)", (ROOT / "server/__init__.py").read_text())

if __name__ == "__main__":
    unittest.main()
