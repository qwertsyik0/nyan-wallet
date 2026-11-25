import importlib.util
import json
from pathlib import Path
import sys
import types
import unittest
from uuid import uuid4
from fastapi import HTTPException, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, Table, MetaData, Column, BigInteger, select, func
from sqlalchemy.orm import registry
from sqlalchemy.pool import StaticPool

ROOT=Path(__file__).resolve().parents[1]
class WorldTest(unittest.TestCase):
    def setUp(self):
        self.engine=create_engine("sqlite://",connect_args={"check_same_thread":False},poolclass=StaticPool)
        mapper=registry()
        users=Table("users",mapper.metadata,Column("telegram_id",BigInteger,primary_key=True))
        class User: pass
        mapper.map_imperatively(User,users);mapper.metadata.create_all(self.engine)
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
        self.client.close();self.engine.dispose()
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
if __name__=="__main__": unittest.main()
