import importlib.util
import json
from pathlib import Path
import sys
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select, func

from test_nyan_world import WorldTest

ROOT = Path(__file__).resolve().parents[1]
SEED_COUNT = len(json.loads((ROOT / "server/world_news_seed.json").read_text()))


class NewsTest(WorldTest):
    def setUp(self):
        super().setUp()
        self.old_world = sys.modules.get("server.nyan_world")
        sys.modules["server.nyan_world"] = self.w
        sys.modules["server"].nyan_world = self.w
        spec = importlib.util.spec_from_file_location("server.world_news_test", ROOT / "server/world_news.py")
        self.news = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.news)
        app = FastAPI()
        self.news.register_world_news(app)
        self.newsclient = TestClient(app)

    def tearDown(self):
        self.newsclient.close()
        self.news.m.drop_all(self.engine)
        if self.old_world is None:
            sys.modules.pop("server.nyan_world", None)
        else:
            sys.modules["server.nyan_world"] = self.old_world
        super().tearDown()

    def command(self, kind, role="owner", code=200, key=None, **values):
        response = self.newsclient.post("/api/world/news/actions", json={
            "operation_id": key or str(uuid4()), "kind": kind, **values,
        }, headers={"X-Telegram-Init-Data": role})
        self.assertEqual(response.status_code, code, response.text)
        return response.json()

    def news_list(self):
        response = self.newsclient.get("/api/world/news/editor", headers={"X-Telegram-Init-Data": "owner"})
        self.assertEqual(response.status_code, 200)
        return response.json()["items"]

    def public(self):
        response = self.newsclient.get("/api/world/news/feed")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["cache-control"], "no-store")
        return response.json()["items"]

    def draft(self, **extra):
        return self.command("save", category="РОССИЯ • США", title="Draft", body="First paragraph\n\nSecond", **extra)["id"]

    def test_news_auth_and_public_privacy(self):
        self.assertEqual(len(self.public()), SEED_COUNT)
        self.assertEqual(self.newsclient.get("/api/world/news/editor").status_code, 401)
        self.assertEqual(self.newsclient.get("/api/world/news/editor", headers={"X-Telegram-Init-Data": "player"}).status_code, 403)
        self.command("save", role="player", code=403, category="x", title="x", body="x")
        rid = self.draft()
        self.assertFalse(any(p["id"] == rid for p in self.public()))
        self.assertNotIn("revision", self.public()[0])
        self.assertNotIn("created_at", self.public()[0])
        self.assertNotIn("published_content", self.news_list()[0])

    def test_publish_edit_and_unpublish(self):
        rid = self.draft()
        self.command("publish", id=rid, expected_revision=1)
        post = next(p for p in self.public() if p["id"] == rid)
        self.assertEqual(post["category"], "РОССИЯ // США")
        self.assertFalse(self.news_list()[0]["has_changes"])
        self.command("save", id=rid, expected_revision=2, category="A", title="Unfinished", body="Private draft")
        self.assertEqual(next(p for p in self.public() if p["id"] == rid)["title"], "Draft")
        self.assertTrue(self.news_list()[0]["has_changes"])
        self.command("publish", id=rid, expected_revision=3)
        self.assertEqual(next(p for p in self.public() if p["id"] == rid)["title"], "Unfinished")
        self.command("unpublish", id=rid, expected_revision=4)
        self.assertFalse(any(p["id"] == rid for p in self.public()))
        self.assertEqual(self.news_list()[0]["title"], "Unfinished")
        self.command("publish", id=rid, expected_revision=5)
        self.assertTrue(any(p["id"] == rid for p in self.public()))

    def test_duplicate_retry_and_stale_revision(self):
        key = str(uuid4())
        rid = self.draft(key=key)
        self.assertEqual(self.draft(key=key), rid)
        self.command("save", key=key, category="A", title="Changed", body="x", code=409)
        key = str(uuid4())
        self.command("publish", key=key, id=rid, expected_revision=1)
        self.command("publish", key=key, id=rid, expected_revision=1)
        self.command("save", id=rid, expected_revision=1, category="A", title="Stale", body="x", code=409)
        self.command("unpublish", id=rid, expected_revision=1, code=409)
        self.assertEqual(len(self.news_list()), SEED_COUNT + 1)

    def test_seed_reinstall_does_not_overwrite_or_republish(self):
        post = self.news_list()[0]
        self.command("save", id=post["id"], expected_revision=post["revision"], category="A", title="Edited legacy", body="x")
        self.command("unpublish", id=post["id"], expected_revision=post["revision"] + 1)
        self.news.seed_existing()
        self.assertEqual(len(self.news_list()), SEED_COUNT)
        self.assertEqual(self.news_list()[0]["title"], "Edited legacy")
        self.assertFalse(self.news_list()[0]["is_published"])

    def test_invalid_and_missing_posts(self):
        self.command("save", category=" ", title="x", body="x", code=400)
        self.command("publish", code=400)
        self.command("publish", id=999, expected_revision=1, code=404)
        self.command("delete", code=400)
        rid = self.draft()
        self.command("save", id=rid, category="A", title="No revision", body="x", code=409)

    def test_no_financial_side_effects(self):
        before = self.state()["countries"]
        rid = self.draft()
        self.command("publish", id=rid, expected_revision=1)
        self.assertEqual(self.state()["countries"], before)

    def test_news_concurrent_duplicate_retry(self):
        if self.engine.dialect.name != "postgresql":
            self.skipTest("PostgreSQL concurrency check")
        from concurrent.futures import ThreadPoolExecutor
        key = str(uuid4())
        def save(_):
            return self.newsclient.post("/api/world/news/actions", json={
                "operation_id": key, "kind": "save",
                "category": "A", "title": "Concurrent", "body": "One news item",
            }, headers={"X-Telegram-Init-Data": "owner"})
        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(pool.map(save, range(2)))
        self.assertEqual([r.status_code for r in responses], [200, 200])
        self.assertEqual(responses[0].json()["id"], responses[1].json()["id"])
        self.assertEqual(len(self.news_list()), SEED_COUNT + 1)


if __name__ == "__main__":
    import unittest
    unittest.main()
