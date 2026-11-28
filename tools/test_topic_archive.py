import asyncio
import importlib.util
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from telegram.ext import ApplicationHandlerStop

ROOT=Path(__file__).resolve().parents[1]
def load(name,path):
    spec=importlib.util.spec_from_file_location(name,ROOT/path)
    mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod);return mod
archive=load("archive","bot_extensions/topic_archive.py")
installer=load("installer","tools/install_topic_archive.py")

class Tests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        archive.DB=Path(self.temp.name)/"archive.sqlite3"
        archive.initialize()
    def tearDown(self):
        self.temp.cleanup()
    def message(self,mid,topic=11,text="hello"):
        return SimpleNamespace(chat_id=archive.CHAT,message_id=mid,message_thread_id=topic,
            text=text,caption=None,date=datetime.now(timezone.utc),sender_chat=None,
            from_user=SimpleNamespace(id=7,full_name="Player",username="player"),
            effective_attachment=None)
    def test_topic_order_boundary_and_commands(self):
        for m in [self.message(1),self.message(2,8),self.message(3),
                  self.message(5),self.message(4,text="/export 100")]:
            archive.record(m)
        rows=archive.select_rows(archive.CHAT,11,5,1000)
        self.assertEqual([r["mid"] for r in rows],[1,3])
        self.assertEqual([r["mid"] for r in archive.select_rows(archive.CHAT,11,6,1)],[5])
        archive.record(self.message(3,text="edited"))
        self.assertEqual(archive.select_rows(archive.CHAT,11,5,1)[0]["text"],"edited")
    def test_snapshot_immutable_and_idempotent(self):
        archive.record(self.message(1))
        rows=archive.select_rows(archive.CHAT,11,2,10)
        sid=archive.snapshot(archive.CHAT,11,2,rows)
        archive.record(self.message(1,text="changed"))
        self.assertEqual(sid,archive.snapshot(archive.CHAT,11,2,[]))
        with archive.connect() as c:
            content=json.loads(c.execute("SELECT content FROM snapshots").fetchone()[0])
        self.assertEqual(content[0]["text"],"hello")
        self.assertIn("hello",archive.render(content))
    def test_owner_only(self):
        update=SimpleNamespace(effective_message=self.message(3),effective_user=SimpleNamespace(id=999))
        with self.assertRaises(ApplicationHandlerStop):
            asyncio.run(archive.command(update,SimpleNamespace(args=["10"])))
    def test_patch(self):
        source="def main():\n    app.run_polling(drop_pending_updates=True)\n"
        changed=installer.patch(source)
        self.assertIn("    register_topic_archive(app)\n    app.run_polling",changed)
        self.assertEqual(installer.patch(changed),changed)
        with self.assertRaises(RuntimeError):
            installer.patch("print('no bot')")
    def test_group_priority(self):
        class App:
            handlers={-3:[]}
            def add_handler(self,h,group):
                self.handlers.setdefault(group,[]).append(h)
        app=App();archive.register_topic_archive(app)
        self.assertEqual(sorted(app.handlers),[-5,-4,-3])

if __name__=="__main__": unittest.main()
