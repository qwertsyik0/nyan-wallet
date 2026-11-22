import importlib.util
import json
from pathlib import Path
import unittest
from sqlalchemy import BigInteger, Column, DateTime, Integer, MetaData, String, Table, Text, event, func, select

ROOT = Path(__file__).resolve().parents[1]
def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

fixtures = load("gift_fixtures", "tools/test_fulfil_gift_requests_20261122.py")
voucher = load("voucher", "tools/grant_custom_gift_coupon.py")

class VoucherTest(unittest.TestCase):
    def setUp(self):
        fixtures.AwardTest.setUp(self)
        self.outbox = Table("telegram_relay_outbox", MetaData(),
            Column("id", Integer, primary_key=True), Column("source_key", String, unique=True),
            Column("chat_id", BigInteger), Column("body", Text), Column("state", String),
            Column("attempts", Integer), Column("created_at", DateTime(timezone=True)))
        self.outbox.create(self.engine)

    def tearDown(self):
        self.engine.dispose()

    def test_issue_one_earliest_request_with_both_benefits_and_no_balance_change(self):
        rid, code, repeated = voucher.grant(self.engine, 1000, "test-operation")
        self.assertEqual(rid, 100)
        self.assertFalse(repeated)
        self.assertRegex(code, r"^#[A-Z]{6}$")
        with self.engine.connect() as c:
            self.assertEqual(c.execute(select(self.users.c.balance).where(self.users.c.telegram_id == 1000)).scalar_one(), 1000)
            self.assertEqual(c.execute(select(func.count()).select_from(self.tx)).scalar_one(), 0)
            states = dict(c.execute(select(self.requests.c.id, self.requests.c.status)).all())
            self.assertEqual(states[100], "fulfilled")
            self.assertTrue(all(value == "pending" for key, value in states.items() if key != 100))
            self.assertEqual(c.execute(select(func.count()).select_from(self.notifications)).scalar_one(), 2)
            self.assertEqual(c.execute(select(func.count()).select_from(self.outbox)).scalar_one(), 2)
            bodies = c.execute(select(self.outbox.c.body)).scalars().all()
            self.assertTrue(any("30%" in body and "200 ₽" in body and "ФИЗ США" in body and code in body for body in bodies))
            awards = voucher.tables(self.engine)["awards"]
            payload = json.loads(c.execute(select(awards.c.payload)).scalar_one())
            self.assertEqual(payload["scope"], "any_account")
            self.assertEqual(payload["purchase_from_rub"], 200)

    def test_retry_reuses_same_voucher_and_does_not_close_another_request(self):
        first = voucher.grant(self.engine, 1000, "test-operation")
        second = voucher.grant(self.engine, 1000, "test-operation")
        self.assertEqual(first[:2], second[:2])
        self.assertTrue(second[2])
        with self.engine.connect() as c:
            self.assertEqual(c.execute(select(func.count()).select_from(self.notifications)).scalar_one(), 2)
            self.assertEqual(c.execute(select(func.count()).select_from(self.outbox)).scalar_one(), 2)
            self.assertEqual(c.execute(select(self.requests.c.status).where(self.requests.c.id == 101)).scalar_one(), "pending")

    def test_improved_gift_is_not_selected_for_random_gift_command(self):
        with self.assertRaises(RuntimeError):
            voucher.grant(self.engine, 91, "test-operation")
        with self.engine.connect() as c:
            self.assertEqual(c.execute(select(func.count()).select_from(self.outbox)).scalar_one(), 0)

    def test_failure_rolls_back_request_coupon_and_both_notification_channels(self):
        def fail(conn, cursor, statement, params, context, many):
            if statement.lower().startswith("insert into admin_audit"):
                raise RuntimeError("test failure")
        event.listen(self.engine, "before_cursor_execute", fail)
        try:
            with self.assertRaises(RuntimeError):
                voucher.grant(self.engine, 1000, "test-operation")
        finally:
            event.remove(self.engine, "before_cursor_execute", fail)
        with self.engine.connect() as c:
            self.assertEqual(c.execute(select(self.requests.c.status).where(self.requests.c.id == 100)).scalar_one(), "pending")
            self.assertEqual(c.execute(select(func.count()).select_from(self.outbox)).scalar_one(), 0)
            self.assertEqual(c.execute(select(func.count()).select_from(self.notifications)).scalar_one(), 0)

    def test_regular_random_pool_discount_cap_stays_at_twenty(self):
        with self.assertRaises(RuntimeError):
            fixtures.gift.validate_prize({"kind": "discount", "percent": 30})

if __name__ == "__main__":
    unittest.main()
