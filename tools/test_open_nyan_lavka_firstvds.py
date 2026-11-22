"""Stock/open CLI regression checks against an isolated database."""
import importlib.util
from pathlib import Path
import unittest
from datetime import datetime, timedelta, timezone

from sqlalchemy import Column, DateTime, Integer, MetaData, String, Table, create_engine, event, select

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("open_shop", ROOT / "tools/open_nyan_lavka_firstvds.py")
shop = importlib.util.module_from_spec(spec)
spec.loader.exec_module(shop)

class OpenShopTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        metadata = MetaData()
        self.window = Table("nyan_lavka_window", metadata,
            Column("id", Integer, primary_key=True), Column("opened_at", DateTime(timezone=True)),
            Column("closes_at", DateTime(timezone=True)), Column("stopped_at", DateTime(timezone=True)))
        self.items = Table("nyan_lavka_items", metadata,
            Column("sku", String, primary_key=True), Column("total", Integer), Column("sold", Integer))
        self.users = Table("users", metadata, Column("id", Integer, primary_key=True), Column("balance", Integer))
        self.purchases = Table("nyan_lavka_purchases", metadata,
            Column("id", Integer, primary_key=True), Column("sku", String))
        metadata.create_all(self.engine)
        with self.engine.begin() as conn:
            conn.execute(self.window.insert().values(id=1))
            conn.execute(self.items.insert(), [{"sku": sku, "total": 0, "sold": 0} for sku in shop.SKUS])
            conn.execute(self.users.insert().values(id=1, balance=500))
            conn.execute(self.purchases.insert().values(id=1, sku="hint"))

    def tearDown(self):
        self.engine.dispose()

    def read(self):
        with self.engine.connect() as conn:
            return (conn.execute(select(self.window)).mappings().one(),
                    {row["sku"]: dict(row) for row in conn.execute(select(self.items)).mappings()})

    def test_opens_all_fourteen_with_at_least_35(self):
        result = shop.activate(self.engine, 35, 180, "open-1")
        window, items = self.read()
        self.assertEqual(result["items"], 14)
        self.assertTrue(all(i["total"] - i["sold"] >= 35 for i in items.values()))
        self.assertIsNone(window["stopped_at"])
        end = shop.utc(window["closes_at"])
        self.assertGreater(end, datetime.now(timezone.utc) + timedelta(minutes=179))

    def test_existing_sales_stock_balances_and_purchases_are_preserved(self):
        with self.engine.begin() as conn:
            conn.execute(self.items.update().where(self.items.c.sku == "hint").values(total=100, sold=4))
            conn.execute(self.items.update().where(self.items.c.sku == "chance").values(total=12, sold=10))
        shop.activate(self.engine, 35, 180, "open-1")
        _, items = self.read()
        self.assertEqual((items["hint"]["total"], items["hint"]["sold"]), (100, 4))
        self.assertEqual((items["chance"]["total"], items["chance"]["sold"]), (45, 10))
        with self.engine.connect() as conn:
            self.assertEqual(conn.execute(select(self.users.c.balance)).scalar_one(), 500)
            self.assertEqual(conn.execute(select(self.purchases.c.id)).scalars().all(), [1])

    def test_repeat_does_not_refill_after_sale_or_extend_timer(self):
        shop.activate(self.engine, 35, 180, "open-1")
        first_window, _ = self.read()
        with self.engine.begin() as conn:
            conn.execute(self.items.update().where(self.items.c.sku == "hint").values(sold=1))
        result = shop.activate(self.engine, 35, 180, "open-1")
        window, items = self.read()
        self.assertTrue(result["already_applied"])
        self.assertEqual(window["closes_at"], first_window["closes_at"])
        self.assertEqual(items["hint"]["total"] - items["hint"]["sold"], 34)

    def test_owner_requested_reopen_keeps_original_open_date(self):
        old = datetime.now(timezone.utc) - timedelta(days=1)
        with self.engine.begin() as conn:
            conn.execute(self.window.update().values(opened_at=old, closes_at=old, stopped_at=old))
        shop.activate(self.engine, 35, 180, "open-1")
        window, _ = self.read()
        self.assertEqual(shop.utc(window["opened_at"]), old)
        self.assertIsNone(window["stopped_at"])
        self.assertGreater(shop.utc(window["closes_at"]), datetime.now(timezone.utc))

    def test_missing_sku_prevents_opening_or_partial_stock_update(self):
        with self.engine.begin() as conn:
            conn.execute(self.items.delete().where(self.items.c.sku == "crystal"))
        with self.assertRaises(RuntimeError):
            shop.activate(self.engine, 35, 180, "open-1")
        window, items = self.read()
        self.assertIsNone(window["opened_at"])
        self.assertTrue(all(i["total"] == 0 for i in items.values()))

    def test_failure_after_updates_rolls_back_window_and_all_items(self):
        def fail_audit(conn, cursor, statement, parameters, context, executemany):
            if statement.lower().startswith("insert into nyan_lavka_admin_actions"):
                raise RuntimeError("test audit failure")
        event.listen(self.engine, "before_cursor_execute", fail_audit)
        try:
            with self.assertRaisesRegex(RuntimeError, "test audit failure"):
                shop.activate(self.engine, 35, 180, "open-1")
        finally:
            event.remove(self.engine, "before_cursor_execute", fail_audit)
        window, items = self.read()
        self.assertIsNone(window["opened_at"])
        self.assertTrue(all(i["total"] == 0 for i in items.values()))

    def test_same_key_cannot_be_reused_for_different_stock(self):
        shop.activate(self.engine, 35, 180, "open-1")
        with self.assertRaises(RuntimeError):
            shop.activate(self.engine, 50, 180, "open-1")

if __name__ == "__main__":
    unittest.main()
