import importlib.util
from pathlib import Path
import sys
import unittest
from sqlalchemy import select, func, event
import test_nyan_world as base

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location("world_seed",ROOT/"tools/seed_nyan_world_countries.py")
seed=importlib.util.module_from_spec(spec);spec.loader.exec_module(seed)

class SeedTest(unittest.TestCase):
    def setUp(self):
        self.fixture=base.WorldTest();self.fixture.setUp()
        self.engine=self.fixture.engine;self.w=self.fixture.w
        self.fixture.do("country",{"season_id":1,"name":"Россия","opening_budget":15000,"player_id":4,"notes":"keep this"})
        self.fixture.do("country",{"season_id":1,"name":"США","opening_budget":18000,"income":2500})
    def tearDown(self): self.fixture.tearDown()
    def rows(self,table):
        with self.engine.connect() as c:
            return [dict(r) for r in c.execute(select(table).order_by(table.c.id)).mappings()]
    def test_adds_exactly_six_presets_with_ledger(self):
        before=self.rows(self.w.countries)
        old_ids={r["id"] for r in before}
        _,results=seed.seed(self.engine,1)
        after=self.rows(self.w.countries)
        self.assertEqual([r for r in after if r["id"] in old_ids],before)
        new=[r for r in after if r["id"] not in old_ids]
        self.assertEqual({r["name"] for r in new},{p[0] for p in seed.PRESETS})
        self.assertEqual(sum(r["budget"] for r in new),90000)
        self.assertTrue(all(r["player_id"] is None and r["frozen"]==0 and r["debt"]==0 for r in new))
        with self.engine.connect() as c:
            entries=c.execute(select(self.w.ledger).where(self.w.ledger.c.country_id.in_([r["id"] for r in new]))).mappings().all()
        self.assertEqual(len(entries),6);self.assertEqual(sum(e["delta"] for e in entries),90000)
    def test_repeat_does_not_replenish_balances_or_overwrite(self):
        seed.seed(self.engine,1)
        china=next(r for r in self.rows(self.w.countries) if r["name"]=="Китай")
        self.fixture.do("budget",{"country_id":china["id"],"delta":-1000,"reason":"spent"})
        before=self.rows(self.w.countries);ledger=self.rows(self.w.ledger);audit=self.rows(self.w.audit)
        seed.seed(self.engine,1)
        self.assertEqual(self.rows(self.w.countries),before)
        self.assertEqual(self.rows(self.w.ledger),ledger)
        self.assertEqual(self.rows(self.w.audit),audit)
    def test_wrong_season_does_not_create_anything(self):
        self.fixture.do("season",{"name":"Other","currency":"WU","status":"draft","select":True})
        before=self.rows(self.w.countries)
        with self.assertRaisesRegex(RuntimeError,"России и США"): seed.seed(self.engine,1)
        self.assertEqual(self.rows(self.w.countries),before)
    def test_failure_rolls_back_all_new_countries_and_budgets(self):
        before=self.rows(self.w.countries);ledger=self.rows(self.w.ledger)
        def fail(c,cursor,statement,parameters,context,many):
            if statement.lower().startswith("insert into nw_audit"): raise RuntimeError("test failure")
        event.listen(self.engine,"before_cursor_execute",fail)
        try:
            with self.assertRaisesRegex(RuntimeError,"test failure"): seed.seed(self.engine,1)
        finally: event.remove(self.engine,"before_cursor_execute",fail)
        self.assertEqual(self.rows(self.w.countries),before)
        self.assertEqual(self.rows(self.w.ledger),ledger)
    def test_existing_country_case_is_preserved(self):
        self.fixture.do("country",{"season_id":1,"name":"КИТАЙ","opening_budget":999,"notes":"custom"})
        before=next(r for r in self.rows(self.w.countries) if r["name"]=="КИТАЙ")
        seed.seed(self.engine,1)
        after=[r for r in self.rows(self.w.countries) if seed.normalized(r["name"])=="китай"]
        self.assertEqual(after,[before])
if __name__=="__main__": unittest.main()
