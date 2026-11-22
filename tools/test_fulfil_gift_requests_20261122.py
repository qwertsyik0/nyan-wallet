import importlib.util
import json
from pathlib import Path
import unittest
from sqlalchemy import (BigInteger, Boolean, Column, DateTime, Integer, MetaData,
                        String, Table, Text, create_engine, event, func, select)

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("gift_batch", ROOT / "tools/fulfil_gift_requests_20261122.py")
gift = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gift)

gift.EXPECTED = {rid: (rid, 800 if rid in (91, 92, 94) else 450)
                 for rid in (90, 91, 92, 93, 94, 99)}
gift.EXPECTED.update({rid: (1000, 450) for rid in range(100, 105)})
gift.PLANNED = {
    99: {"kind": "lapcoins", "amount": 300}, 94: {"kind": "lapcoins", "amount": 650},
    93: {"kind": "discount", "percent": 10, "code": "#ABCDEF"},
    92: {"kind": "lapcoins", "amount": 1050},
    91: {"kind": "discount", "percent": 20, "code": "#GHIJKL"},
    90: {"kind": "lapcoins", "amount": 600},
}

class AwardTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        m = MetaData()
        self.users = Table("users", m, Column("telegram_id", BigInteger, primary_key=True), Column("balance", Integer))
        self.requests = Table("spend_requests", m, Column("id", Integer, primary_key=True),
            Column("telegram_id", BigInteger), Column("reward_title", Text), Column("cost", Integer),
            Column("status", String), Column("processed_at", DateTime(timezone=True)))
        self.tx = Table("transactions", m, Column("id", Integer, primary_key=True),
            Column("telegram_id", BigInteger), Column("amount", Integer), Column("operation_type", String),
            Column("description", Text), Column("created_at", DateTime(timezone=True)))
        self.notifications = Table("wallet_notifications", m, Column("id", Integer, primary_key=True),
            Column("telegram_id", BigInteger), Column("kind", String), Column("title", String),
            Column("body", Text), Column("is_read", Boolean), Column("created_at", DateTime(timezone=True)))
        Table("spend_request_meta", m, Column("request_id", Integer, primary_key=True),
            Column("owner_comment", Text), Column("updated_at", DateTime(timezone=True)))
        Table("admin_audit", m, Column("id", Integer, primary_key=True), Column("action", String),
            Column("target_telegram_id", BigInteger), Column("details", Text), Column("created_at", DateTime(timezone=True)))
        m.create_all(self.engine)
        with self.engine.begin() as c:
            for uid in set(uid for uid, _ in gift.EXPECTED.values()):
                c.execute(self.users.insert().values(telegram_id=uid, balance=1000))
            for rid, (uid, cost) in gift.EXPECTED.items():
                title = "Улучшенный подарок" if cost == 800 else "Случайный подарок"
                c.execute(self.requests.insert().values(id=rid, telegram_id=uid, reward_title=title, cost=cost, status="pending"))
            for rid, title in ((95, "Билет"), (96, "Редкий номер"), (105, "Случайный подарок")):
                c.execute(self.requests.insert().values(id=rid, telegram_id=1000, reward_title=title, cost=450, status="pending"))

    def tearDown(self):
        self.engine.dispose()

    def run_batch(self):
        return gift.fulfil(self.engine, chooser=lambda improved: {"kind": "lapcoins", "amount": 500})

    def stats(self):
        with self.engine.connect() as c:
            return (c.execute(select(func.sum(self.tx.c.amount))).scalar_one(),
                    c.execute(select(func.count()).select_from(self.notifications)).scalar_one(),
                    dict(c.execute(select(self.requests.c.id, self.requests.c.status)).all()))

    def test_exact_eleven_requests_and_two_notifications_per_request(self):
        self.run_batch()
        amount, notifications, states = self.stats()
        self.assertEqual(amount, 5100)
        self.assertEqual(notifications, 22)
        self.assertTrue(all(states[rid] == "fulfilled" for rid in gift.EXPECTED))
        self.assertTrue(all(states[rid] == "pending" for rid in (95, 96, 105)))

    def test_repeat_is_noop_for_balances_notifications_and_prizes(self):
        self.run_batch()
        first = self.stats()
        self.run_batch()
        self.assertEqual(self.stats(), first)

    def test_multiple_requests_for_same_user_all_credit_without_lost_updates(self):
        self.run_batch()
        with self.engine.connect() as c:
            balance = c.execute(select(self.users.c.balance).where(self.users.c.telegram_id == 1000)).scalar_one()
        self.assertEqual(balance, 3500)

    def test_invalid_request_rolls_back_earlier_changes(self):
        with self.engine.begin() as c:
            c.execute(self.requests.update().where(self.requests.c.id == 104).values(cost=999))
        with self.assertRaises(RuntimeError):
            self.run_batch()
        amount, notifications, states = self.stats()
        self.assertIsNone(amount)
        self.assertEqual(notifications, 0)
        self.assertTrue(all(v == "pending" for v in states.values()))

    def test_promo_registered_with_cap_and_redeemed_once(self):
        self.run_batch()
        awards = gift.tables(self.engine)["awards"]
        with self.engine.connect() as c:
            rows = c.execute(select(awards).where(awards.c.code.is_not(None))).mappings().all()
        self.assertEqual(len(rows), 2)
        for row in rows:
            self.assertRegex(row["code"], r"^#[A-Z]{6}$")
            self.assertLessEqual(json.loads(row["payload"])["percent"], 20)
        gift.redeem(self.engine, "#GHIJKL")
        with self.assertRaises(RuntimeError):
            gift.redeem(self.engine, "#GHIJKL")

    def test_telegram_repeat_does_not_send_again(self):
        self.run_batch()
        calls = []
        def sender(token, uid, body):
            calls.append((uid, body))
            return "sent", len(calls)
        gift.deliver(self.engine, "fake-test-token", sender=sender)
        self.assertEqual(len(calls), 22)
        gift.deliver(self.engine, "fake-test-token", sender=sender)
        self.assertEqual(len(calls), 22)

    def test_unknown_delivery_is_not_retried_automatically(self):
        self.run_batch()
        calls = []
        def sender(token, uid, body):
            calls.append(body)
            return "uncertain", None
        gift.deliver(self.engine, "fake-test-token", sender=sender)
        gift.deliver(self.engine, "fake-test-token", sender=sender)
        self.assertEqual(len(calls), 22)
        self.assertEqual(self.stats()[1], 22)

    def test_all_new_pool_prizes_have_deliverable_description(self):
        for prize in ({"kind": "cashback"}, {"kind": "warranty", "days": 7}, {"kind": "replacement"},
                      {"kind": "background"}, {"kind": "badge"}, {"kind": "bundle", "amount": 200, "percent": 10, "code": "#ABCDEF"}):
            gift.validate_prize(prize)
            self.assertTrue(gift.describe(prize, 104))
        with self.assertRaises(RuntimeError):
            gift.validate_prize({"kind": "discount", "percent": 21})

if __name__ == "__main__":
    unittest.main()

