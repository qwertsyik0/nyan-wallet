import importlib.util
import json
import unittest
from pathlib import Path
from sqlalchemy import create_engine, MetaData, Table, Column, Integer, String, Text, DateTime, Boolean, select, func

spec=importlib.util.spec_from_file_location("batch",Path(__file__).with_name("issue_prizes_20261127.py"))
b=importlib.util.module_from_spec(spec);spec.loader.exec_module(b)

class BatchTests(unittest.TestCase):
    def setUp(self):
        self.e=create_engine("sqlite://")
        m=MetaData()
        self.t={}
        def table(name,*cols):
            self.t[name]=Table(name,m,*cols)
        table("users",Column("telegram_id",Integer,primary_key=True),Column("balance",Integer))
        table("spend_requests",Column("id",Integer,primary_key=True),Column("telegram_id",Integer),Column("cost",Integer),Column("reward_title",String),Column("status",String),Column("processed_at",DateTime))
        table("transactions",Column("id",Integer,primary_key=True),Column("telegram_id",Integer),Column("amount",Integer),Column("operation_type",String),Column("description",Text),Column("created_at",DateTime))
        table("wallet_notifications",Column("id",Integer,primary_key=True),Column("telegram_id",Integer),Column("kind",String),Column("title",String),Column("body",Text),Column("is_read",Boolean),Column("created_at",DateTime))
        table("spend_request_meta",Column("request_id",Integer,primary_key=True),Column("owner_comment",Text),Column("updated_at",DateTime))
        table("admin_audit",Column("id",Integer,primary_key=True),Column("action",String),Column("target_telegram_id",Integer),Column("details",Text),Column("created_at",DateTime))
        table("telegram_relay_outbox",Column("id",Integer,primary_key=True),Column("source_key",String,unique=True),Column("chat_id",Integer),Column("body",Text),Column("state",String),Column("attempts",Integer),Column("created_at",DateTime))
        table("prize_gifts",Column("request_id",Integer,primary_key=True),Column("recipient_id",Integer))
        m.create_all(self.e)
        with self.e.begin() as c:
            for rid,(uid,cost,p) in b.PLAN.items():
                c.execute(self.t["users"].insert().values(telegram_id=uid,balance=100))
                c.execute(self.t["spend_requests"].insert().values(id=rid,telegram_id=uid,cost=cost,reward_title="Улучшенный подарок" if cost==800 else "Случайный подарок",status="pending"))
            c.execute(self.t["spend_requests"].insert().values(id=95,telegram_id=8169369912,cost=550,reward_title="Билет",status="pending"))
    def count(self,name):
        with self.e.connect() as c:return c.scalar(select(func.count()).select_from(self.t[name]))
    def test_distribution_and_retry(self):
        b.fulfil(self.e);b.fulfil(self.e)
        self.assertEqual(self.count("transactions"),2)
        self.assertEqual(self.count("telegram_relay_outbox"),12)
        with self.e.connect() as c:
            self.assertEqual(c.scalar(select(self.t["users"].c.balance).where(self.t["users"].c.telegram_id==7235315034)),600)
            self.assertEqual(c.scalar(select(self.t["users"].c.balance).where(self.t["users"].c.telegram_id==6968551476)),1100)
            self.assertEqual(c.scalar(select(self.t["spend_requests"].c.status).where(self.t["spend_requests"].c.id==95)),"pending")
            a=b.award_table(MetaData())
            rows=c.execute(select(a)).mappings().all()
            self.assertEqual(len(rows),6)
            codes=[r["code"] for r in rows if r["code"]]
            self.assertEqual(len(set(codes)),3)
            self.assertTrue(all(len(x)<=7 for x in codes))
            self.assertTrue(any("150 ₽" in r["description"] for r in rows))
    def test_changed_request_rolls_back_everything(self):
        with self.e.begin() as c:c.execute(self.t["spend_requests"].update().where(self.t["spend_requests"].c.id==120).values(cost=999))
        with self.assertRaises(RuntimeError):b.fulfil(self.e)
        self.assertEqual(self.count("transactions"),0)
        self.assertEqual(self.count("telegram_relay_outbox"),0)
        with self.e.connect() as c:self.assertEqual(c.scalar(select(self.t["spend_requests"].c.status).where(self.t["spend_requests"].c.id==110)),"pending")
    def test_gift_recipient_must_match(self):
        with self.e.begin() as c:c.execute(self.t["prize_gifts"].insert().values(request_id=114,recipient_id=99))
        with self.assertRaises(RuntimeError):b.fulfil(self.e)
        self.assertEqual(self.count("telegram_relay_outbox"),0)
    def test_code_collision_rolls_back(self):
        a=b.award_table(MetaData());a.create(self.e)
        from datetime import datetime
        with self.e.begin() as c:c.execute(a.insert().values(request_id=999,telegram_id=1,kind="discount",code="#ZQMVKA",payload="{}",description="old",created_at=datetime.now(),first_state="sent",second_state="sent"))
        with self.assertRaises(RuntimeError):b.fulfil(self.e)
        self.assertEqual(self.count("telegram_relay_outbox"),0)

if __name__=="__main__":unittest.main()
