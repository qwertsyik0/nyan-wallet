import importlib.util
import json
import os
from pathlib import Path
import sys
import types
import unittest
from uuid import uuid4
from fastapi import HTTPException, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, Table, MetaData, Column, BigInteger, Integer, String, Text, DateTime, select, func
from sqlalchemy.orm import registry
from sqlalchemy.pool import StaticPool

ROOT=Path(__file__).resolve().parents[1]
class WorldTest(unittest.TestCase):
    def setUp(self):
        pg=os.getenv("NYAN_WORLD_TEST_DATABASE_URL")
        if pg:
            if not pg.endswith("/world_test"): raise RuntimeError("Only the dedicated world_test database is allowed")
            self.engine=create_engine(pg)
        else:
            self.engine=create_engine("sqlite://",connect_args={"check_same_thread":False},poolclass=StaticPool)
        mapper=registry()
        users=Table("users",mapper.metadata,Column("telegram_id",BigInteger,primary_key=True),
            Column("username",String),Column("first_name",String),Column("last_name",String))
        self.outbox=Table("telegram_relay_outbox",mapper.metadata,
            Column("id",Integer,primary_key=True),Column("source_key",String,unique=True),
            Column("chat_id",BigInteger),Column("body",Text),Column("state",String),
            Column("attempts",Integer),Column("created_at",DateTime(timezone=True)))
        class User: pass
        mapper.map_imperatively(User,users);mapper.metadata.create_all(self.engine);self.usersmeta=mapper.metadata
        def verify(raw):
            if raw not in {"owner","player","other","third"}: raise HTTPException(401,"bad auth")
            return {"id":{"owner":1,"player":2,"other":3,"third":4}[raw]}
        def require(user):
            if user["id"]!=1: raise HTTPException(403,"owner")
        self.core=types.ModuleType("server.backend_app")
        self.core.engine=self.engine; self.core.User=User
        self.core.verify_init_data=verify;self.core.require_owner=require
        self.core.is_owner=lambda uid:uid==1;self.core.OWNER_TELEGRAM_ID=1
        parent=types.ModuleType("server");parent.backend_app=self.core
        self.previous={k:sys.modules.get(k) for k in ("server","server.backend_app")}
        sys.modules["server"]=parent;sys.modules["server.backend_app"]=self.core
        spec=importlib.util.spec_from_file_location("world_test_module",ROOT/"server/nyan_world.py")
        self.w=importlib.util.module_from_spec(spec);sys.modules[spec.name]=self.w;spec.loader.exec_module(self.w)
        app=FastAPI();self.w.register_world(app);self.client=TestClient(app)
        with self.engine.begin() as c: c.execute(users.insert(),[{"telegram_id":i} for i in range(1,5)])
        self.do("season",{"name":"Test","currency":"WU","status":"active","select":True})
        self.do("country",{"season_id":1,"name":"A","player_id":2,"opening_budget":1000,"indicators":{"stability":50}})
        self.do("country",{"season_id":1,"name":"B","player_id":3,"opening_budget":500})
    def tearDown(self):
        self.client.close();self.w.m.drop_all(self.engine);self.usersmeta.drop_all(self.engine);self.engine.dispose()
        for k,v in self.previous.items():
            if v is None: sys.modules.pop(k,None)
            else: sys.modules[k]=v
    def do(self,kind,data,role="owner",key=None,code=200):
        r=self.client.post("/api/world/actions",json={"operation_id":key or str(uuid4()),"kind":kind,"data":data},headers={"X-Telegram-Init-Data":role})
        self.assertEqual(r.status_code,code,r.text)
        return r
    def state(self,role="owner"):
        r=self.client.get("/api/world/state",headers={"X-Telegram-Init-Data":role});self.assertEqual(r.status_code,200,r.text);return r.json()
    def submit(self):
        self.do("submit",{"country_id":1,"title":"Build","body":"Build plant","kind":"decision"},"player")
        return self.state()["requests"][0]["id"]
    def test_concurrent_duplicate_budget_action(self):
        if self.engine.dialect.name!="postgresql": self.skipTest("PostgreSQL concurrency check")
        from concurrent.futures import ThreadPoolExecutor
        key=str(uuid4())
        def run():
            return self.client.post("/api/world/actions",json={"operation_id":key,"kind":"budget","data":{"country_id":1,"delta":25,"reason":"concurrent"}},headers={"X-Telegram-Init-Data":"owner"}).status_code
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(lambda _:run(), range(2)))
        self.assertEqual(results,[200,200])
        self.assertEqual(self.state()["countries"][0]["budget"],1025)
    def test_auth_and_private_state(self):
        self.assertEqual(self.client.get("/api/world/state").status_code,401)
        self.do("budget",{"country_id":1,"delta":100,"reason":"x"},"player",code=403)
        st=self.state("player")
        self.assertEqual(st["audit"],[])
        self.assertNotIn("budget",st["countries"][1]);self.assertNotIn("player_id",st["countries"][1])
        self.assertEqual(st["countries"][0]["budget"],1000)
        self.do("submit",{"country_id":2,"title":"x","body":"x"},"player",code=403)
    def test_moderation_and_exact_once_effects(self):
        rid=self.submit()
        self.do("review",{"id":rid,"status":"approved","effects":{"budget_delta":-200,"indicators":{"stability":55}}})
        self.assertEqual(self.state()["countries"][0]["budget"],1000)
        key=str(uuid4());self.do("apply",{"id":rid},key=key);self.do("apply",{"id":rid},key=key)
        self.assertEqual(self.state()["countries"][0]["budget"],800)
        self.assertEqual(self.state()["countries"][0]["indicators"]["stability"],55)
        self.do("apply",{"id":rid},code=400)
        self.assertEqual(self.state()["requests"][0]["status"],"completed")
    def test_transfer_atomic_insufficient_and_reverse(self):
        self.do("transfer",{"country_id":1,"recipient_id":2,"amount":1500,"reason":"x"},code=400)
        self.assertEqual([c["budget"] for c in self.state()["countries"]],[1000,500])
        key=str(uuid4());data={"country_id":1,"recipient_id":2,"amount":100,"reason":"Trade"}
        self.do("transfer",data,key=key);self.do("transfer",data,key=key)
        st=self.state();self.assertEqual([c["budget"] for c in st["countries"]],[900,600])
        lid=st["ledger"][0]["id"];self.do("reverse",{"id":lid,"reason":"correction"})
        self.assertEqual([c["budget"] for c in self.state()["countries"]],[1000,500])
        self.do("reverse",{"id":lid,"reason":"again"},code=400)
    def test_reverse_combined_funding_and_transfer(self):
        rid=self.submit()
        self.do("review",{"id":rid,"status":"approved","effects":{"budget_delta":1500,"recipient_id":2,"transfer_amount":2000}})
        self.do("apply",{"id":rid})
        st=self.state();self.assertEqual([c["budget"] for c in st["countries"]],[500,2500])
        self.do("reverse",{"id":st["ledger"][0]["id"],"reason":"undo combined decision"})
        self.assertEqual([c["budget"] for c in self.state()["countries"]],[1000,500])
    def test_revision_and_history_permissions(self):
        rid=self.submit()
        self.do("review",{"id":rid,"status":"needs_revision","comment":"add cost"})
        self.do("resubmit",{"id":rid,"title":"Plant","body":"Cost 200"},"other",code=403)
        self.do("resubmit",{"id":rid,"title":"Plant","body":"Cost 200"},"player")
        self.assertEqual(self.state("player")["requests"][0]["revision"],2)
        self.assertEqual(self.client.get(f"/api/world/requests/{rid}/history",headers={"X-Telegram-Init-Data":"other"}).status_code,403)
        h=self.client.get(f"/api/world/requests/{rid}/history",headers={"X-Telegram-Init-Data":"player"}).json()
        self.assertEqual(len(h["items"]),3)
    def test_assignment_unique_and_player_cannot_self_assign(self):
        self.do("country",{"id":2,"season_id":1,"name":"B","player_id":2},code=409)
        self.do("country",{"id":2,"season_id":1,"name":"B","player_id":4},"third",code=403)
        self.assertEqual(self.state()["countries"][1]["player_id"],3)
    def test_registration_and_pause(self):
        self.do("country",{"season_id":1,"name":"C"})
        self.do("submit",{"country_id":3,"kind":"registration","title":"Join","body":"Want C"},"third")
        rid=self.state()["requests"][0]["id"]
        self.do("review",{"id":rid,"status":"approved","comment":"welcome"})
        self.assertEqual(self.state("third")["my_country_id"],3)
        self.do("season",{"id":1,"name":"Test","currency":"WU","status":"paused"})
        self.do("submit",{"country_id":1,"title":"x","body":"x"},"player",code=400)
    def test_season_isolation_and_no_wallet_money(self):
        self.do("season",{"name":"Next","currency":"NEXT","status":"draft","select":True})
        self.assertEqual(self.state("player")["countries"],[])
        self.assertEqual(self.state("player")["requests"],[])
        self.assertEqual(self.state("player")["ledger"],[])
        with self.engine.connect() as c: self.assertEqual(c.execute(select(func.count()).select_from(self.w.countries)).scalar(),2)
    def test_validation_key_reuse_and_rollback(self):
        key=str(uuid4())
        self.do("budget",{"country_id":1,"delta":20,"reason":"x"},key=key)
        self.do("budget",{"country_id":1,"delta":30,"reason":"x"},key=key,code=409)
        self.do("budget",{"country_id":1,"delta":True,"reason":"x"},code=400)
        rid=self.submit();self.do("review",{"id":rid,"status":"approved","effects":{"budget_delta":-999999}})
        self.do("apply",{"id":rid},code=400)
        self.assertEqual(self.state()["countries"][0]["budget"],1020)
        self.assertEqual(self.state()["requests"][0]["status"],"approved")

    def registration(self):
        self.do("country",{"season_id":1,"name":"C"})
        self.do("submit",{"country_id":3,"kind":"registration","title":"Join","body":"Want C"},"third")
        return self.state()["requests"][0]["id"]
    def test_approval_invite_private_and_idempotent(self):
        rid=self.registration()
        self.assertEqual(self.state("third")["season"]["chat_url"],"")
        with self.engine.begin() as c:
            c.execute(self.core.User.__table__.update().where(
                self.core.User.telegram_id==4).values(username="applicant"))
        key=str(uuid4());data={"id":rid,"status":"approved"}
        self.do("review",data,key=key);self.do("review",data,key=key)
        self.do("review",data,code=400)
        st=self.state("third")
        self.assertEqual(st["my_country_id"],3)
        self.assertEqual(st["season"]["chat_url"],self.w.WORLD_CHAT_URL)
        with self.engine.connect() as c:
            rows=[r for r in c.execute(select(self.outbox)).mappings().all()
                  if r["body"].startswith("NYAN_TG_RICH_V1:")]
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]["chat_id"],4)
        body=rows[0]["body"]
        self.assertTrue(body.startswith("NYAN_TG_RICH_V1:"))
        payload=json.loads(body.removeprefix("NYAN_TG_RICH_V1:"))
        self.assertIn("@applicant",payload["text"])
        self.assertIn("C",payload["text"])
        self.assertEqual(payload["buttons"],[{"text":"Вступить в чат","url":self.w.WORLD_CHAT_URL}])
        self.assertIn("одобрена",st["notices"][0]["body"])
    def test_approval_escapes_name_and_uses_season_link(self):
        rid=self.registration()
        self.do("season",{"id":1,"name":"Test","currency":"WU","status":"active",
                          "chat_url":"https://t.me/+anotherInvite"})
        with self.engine.begin() as c:
            c.execute(self.core.User.__table__.update().where(
                self.core.User.telegram_id==4).values(first_name="<Alice & Bob>"))
        self.do("review",{"id":rid,"status":"approved"})
        with self.engine.connect() as c:
            body=next(r for r in c.execute(select(self.outbox.c.body)).scalars()
                      if r.startswith("NYAN_TG_RICH_V1:"))
        payload=json.loads(body.removeprefix("NYAN_TG_RICH_V1:"))
        self.assertIn("&lt;Alice &amp; Bob&gt;",payload["text"])
        self.assertEqual(payload["buttons"][0]["url"],"https://t.me/+anotherInvite")
    def test_rejected_registration_has_no_invite(self):
        rid=self.registration()
        self.do("review",{"id":rid,"status":"rejected","comment":"Incomplete"})
        self.assertEqual(self.state("third")["season"]["chat_url"],"")
        with self.engine.connect() as c:
            self.assertFalse(any(r.startswith("NYAN_TG_RICH_V1:") for r in c.execute(select(self.outbox.c.body)).scalars()))
        self.assertIsNone(self.state("third")["my_country_id"])
    def test_missing_outbox_rolls_back_approval(self):
        rid=self.registration()
        self.outbox.drop(self.engine)
        self.do("review",{"id":rid,"status":"approved"},code=503)
        st=self.state("third")
        self.assertIsNone(st["my_country_id"])
        self.assertEqual(st["requests"][0]["status"],"submitted")


    def queued(self,uid=None):
        with self.engine.connect() as c:
            query=select(self.outbox).order_by(self.outbox.c.id)
            if uid is not None: query=query.where(self.outbox.c.chat_id==uid)
            return [dict(r) for r in c.execute(query).mappings()]
    def clear_queued(self):
        with self.engine.begin() as c: c.execute(self.outbox.delete())
    def test_request_notifications_lifecycle_and_retry(self):
        self.clear_queued()
        with self.engine.begin() as c:
            c.execute(self.core.User.__table__.update().where(
                self.core.User.telegram_id==2).values(username="player_name"))
        key=str(uuid4());data={"country_id":1,"title":"Quality","body":"Inspect food","kind":"decision"}
        self.do("submit",data,"player",key=key);self.do("submit",data,"player",key=key)
        rid=self.state()["requests"][0]["id"]
        self.assertEqual(len(self.queued(1)),1)
        self.assertIn("@player_name",self.queued(1)[0]["body"])
        self.assertIn("Inspect food",self.queued(1)[0]["body"])
        self.assertIn("Государственное решение",self.queued(1)[0]["body"])
        self.assertEqual(len(self.queued(2)),1)
        self.clear_queued()
        key=str(uuid4());data={"id":rid,"status":"needs_revision","comment":"Please add a location"}
        self.do("review",data,key=key);self.do("review",data,key=key)
        for uid in (1,2):
            self.assertEqual(len(self.queued(uid)),1)
            self.assertIn("возвращена на доработку",self.queued(uid)[0]["body"])
            self.assertIn("Please add a location",self.queued(uid)[0]["body"])
        self.clear_queued()
        self.do("resubmit",{"id":rid,"title":"Quality","body":"Inspect factory A"},"player")
        self.assertIn("Inspect factory A",self.queued(1)[0]["body"])
        self.clear_queued()
        self.do("review",{"id":rid,"status":"approved","effects":{"budget_delta":-300,"indicators":{"stability":52}}})
        for uid in (1,2):
            self.assertIn("одобрена",self.queued(uid)[0]["body"])
            self.assertIn("ещё не применены",self.queued(uid)[0]["body"])
        self.assertEqual(self.state()["countries"][0]["budget"],1000)
        self.clear_queued()
        key=str(uuid4());self.do("apply",{"id":rid},key=key);self.do("apply",{"id":rid},key=key)
        for uid in (1,2):
            self.assertEqual(len(self.queued(uid)),1)
            self.assertIn("выполнена",self.queued(uid)[0]["body"])
            self.assertIn("-300",self.queued(uid)[0]["body"])
            self.assertIn("700",self.queued(uid)[0]["body"])
        self.assertEqual(self.queued(3),[])
    def test_registration_rejection_and_withdraw_notifications(self):
        rid=self.registration();self.clear_queued()
        self.do("review",{"id":rid,"status":"rejected","comment":"Need more details"})
        for uid in (1,4):
            self.assertIn("отклонена",self.queued(uid)[0]["body"])
            self.assertIn("Need more details",self.queued(uid)[0]["body"])
            self.assertNotIn("https://t.me/",self.queued(uid)[0]["body"])
        self.do("submit",{"country_id":3,"kind":"registration","title":"Join again","body":"New application"},"third")
        rid=self.state()["requests"][0]["id"];self.clear_queued()
        self.do("withdraw",{"id":rid},"third")
        self.assertIn("отозвана",self.queued(1)[0]["body"])
        self.assertIn("отозвана",self.queued(4)[0]["body"])
    def test_rollback_does_not_queue_notifications(self):
        rid=self.submit()
        self.do("review",{"id":rid,"status":"approved","effects":{"budget_delta":-2000}})
        self.clear_queued()
        self.do("apply",{"id":rid},code=400)
        self.assertEqual(self.queued(),[])
        self.assertEqual(self.state()["countries"][0]["budget"],1000)
    def test_long_messages_split_safely_and_preserve_content(self):
        self.clear_queued()
        body="😀"*5000
        with self.engine.begin() as c: self.w.notify(c,2,body,mirror=False)
        rows=self.queued(2);self.assertGreater(len(rows),1)
        reconstructed=""
        for row in rows:
            self.assertLessEqual(len(row["body"].encode("utf-16-le"))//2,4096)
            reconstructed+=row["body"].split("\n",2)[2]
        self.assertEqual(reconstructed,body)
        self.assertEqual(len({r["source_key"] for r in rows}),len(rows))
    def test_season_state_and_budget_notifications(self):
        self.clear_queued()
        self.do("season",{"id":1,"name":"Test","currency":"WU","status":"paused"})
        for uid in (1,2,3):
            self.assertEqual(len(self.queued(uid)),1)
            self.assertIn("Пауза",self.queued(uid)[0]["body"])
        self.assertEqual(self.queued(4),[])
        self.clear_queued()
        key=str(uuid4());data={"country_id":1,"delta":10,"reason":"Correction"}
        self.do("budget",data,key=key);self.do("budget",data,key=key)
        for uid in (1,2):
            self.assertEqual(len(self.queued(uid)),1)
            self.assertIn("1010",self.queued(uid)[0]["body"])
    def test_owner_player_no_duplicate_mirror(self):
        self.do("country",{"season_id":1,"name":"Ownerland","player_id":1})
        self.clear_queued()
        self.do("budget",{"country_id":3,"delta":10,"reason":"Owner country"})
        self.assertEqual(len(self.queued(1)),1)


    def test_news_once_per_account_and_auth(self):
        endpoint="/api/world/news/claim"
        self.assertEqual(self.client.post(endpoint).status_code,401)
        def claim(role):return self.client.post(endpoint,headers={"X-Telegram-Init-Data":role}).json()
        self.assertTrue(claim("player")["show"])
        self.assertFalse(claim("player")["show"])
        self.assertTrue(claim("third")["show"])
        self.assertFalse(claim("third")["show"])
        self.assertEqual(self.state()["countries"][0]["budget"],1000)
    def test_news_paused_does_not_consume_view(self):
        self.do("season",{"id":1,"name":"Test","currency":"WU","status":"paused"})
        endpoint="/api/world/news/claim";headers={"X-Telegram-Init-Data":"third"}
        self.assertFalse(self.client.post(endpoint,headers=headers).json()["available"])
        self.do("season",{"id":1,"name":"Test","currency":"WU","status":"active"})
        self.assertTrue(self.client.post(endpoint,headers=headers).json()["show"])
    def test_news_concurrent_claim(self):
        if self.engine.dialect.name!="postgresql":self.skipTest("PostgreSQL concurrency")
        from concurrent.futures import ThreadPoolExecutor
        def claim(_):
            return self.client.post("/api/world/news/claim",
                headers={"X-Telegram-Init-Data":"third"}).json()["show"]
        with ThreadPoolExecutor(max_workers=2) as pool: results=list(pool.map(claim,range(2)))
        self.assertEqual(sorted(results),[False,True])
if __name__=="__main__": unittest.main()

