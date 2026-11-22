import ast
import importlib.util
from pathlib import Path
import subprocess
import unittest
from sqlalchemy import (BigInteger, Boolean, Column, DateTime, Integer, MetaData, String,
                        Table, Text, create_engine, event, func, select)

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("rare", ROOT / "tools/assign_rare_wallet_number.py")
rare = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rare)

class RareNumberTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        m = MetaData()
        self.users = Table("users", m, Column("telegram_id", BigInteger, primary_key=True), Column("balance", Integer))
        self.requests = Table("spend_requests", m, Column("id", Integer, primary_key=True),
            Column("telegram_id", BigInteger), Column("reward_title", Text), Column("status", String),
            Column("processed_at", DateTime(timezone=True)))
        self.notes = Table("wallet_notifications", m, Column("id", Integer, primary_key=True),
            Column("telegram_id", BigInteger), Column("kind", String), Column("title", String),
            Column("body", Text), Column("is_read", Boolean), Column("created_at", DateTime(timezone=True)))
        Table("spend_request_meta", m, Column("request_id", Integer, primary_key=True),
              Column("owner_comment", Text), Column("updated_at", DateTime(timezone=True)))
        Table("admin_audit", m, Column("id", Integer, primary_key=True), Column("action", String),
              Column("target_telegram_id", BigInteger), Column("details", Text), Column("created_at", DateTime(timezone=True)))
        m.create_all(self.engine)
        with self.engine.begin() as c:
            c.execute(self.users.insert(), [{"telegram_id": 7, "balance": 1000}, {"telegram_id": 8, "balance": 500}])
            c.execute(self.requests.insert(), [
                {"id": 96, "telegram_id": 7, "reward_title": "Редкий номер кошелька", "status": "pending"},
                {"id": 95, "telegram_id": 8, "reward_title": "Билет", "status": "pending"}])

    def tearDown(self):
        self.engine.dispose()

    def test_assign_closes_only_rare_request_and_preserves_balance(self):
        self.assertTrue(rare.assign(self.engine, 96, 7, "NYAN 7777 0000 7777"))
        n = rare.schema(self.engine)["numbers"]
        with self.engine.connect() as c:
            self.assertEqual(c.execute(select(n.c.number)).scalar_one(), "777700007777")
            self.assertEqual(dict(c.execute(select(self.requests.c.id, self.requests.c.status)).all()),
                             {96: "fulfilled", 95: "pending"})
            self.assertEqual(dict(c.execute(select(self.users.c.telegram_id, self.users.c.balance)).all()), {7: 1000, 8: 500})
            self.assertEqual(c.execute(select(func.count()).select_from(self.notes)).scalar_one(), 1)

    def test_repeat_does_not_duplicate_notice_or_telegram(self):
        rare.assign(self.engine, 96, 7, "777700007777")
        self.assertFalse(rare.assign(self.engine, 96, 7, "777700007777"))
        calls = []
        def sender(token, user, body):
            calls.append((user, body))
            return "sent", 123
        rare.deliver(self.engine, 7, 96, "fake", sender)
        rare.deliver(self.engine, 7, 96, "fake", sender)
        self.assertEqual(len(calls), 1)
        with self.engine.connect() as c:
            self.assertEqual(c.execute(select(func.count()).select_from(self.notes)).scalar_one(), 1)

    def test_generated_number_collision_and_owner_number_rejected(self):
        with self.assertRaises(RuntimeError):
            rare.assign(self.engine, 96, 7, rare.generated_number(8))
        with self.assertRaises(RuntimeError):
            rare.assign(self.engine, 96, 7, "777777777777")
        with self.engine.connect() as c:
            self.assertEqual(c.execute(select(self.requests.c.status).where(self.requests.c.id == 96)).scalar_one(), "pending")

    def test_wrong_recipient_or_nonrare_request_cannot_close(self):
        for rid, uid in ((96, 8), (95, 8)):
            with self.assertRaises(RuntimeError):
                rare.assign(self.engine, rid, uid, "777700007777")

    def test_failure_rolls_back_number_request_and_notification(self):
        def fail(c, cursor, statement, params, context, many):
            if statement.lower().startswith("insert into admin_audit"):
                raise RuntimeError("test audit failure")
        event.listen(self.engine, "before_cursor_execute", fail)
        try:
            with self.assertRaisesRegex(RuntimeError, "test audit failure"):
                rare.assign(self.engine, 96, 7, "777700007777")
        finally:
            event.remove(self.engine, "before_cursor_execute", fail)
        with self.engine.connect() as c:
            self.assertEqual(c.execute(select(self.requests.c.status).where(self.requests.c.id == 96)).scalar_one(), "pending")
            self.assertEqual(c.execute(select(func.count()).select_from(self.notes)).scalar_one(), 0)

    def test_patch_is_idempotent_and_preserves_custom_code(self):
        old = 'Base.metadata.create_all(engine)\n\ndef serialize_user(user):\n    owner = False\n    return {"unlimited_balance": owner,}\n\nLOCAL_CUSTOM = True\n'
        updated = rare.patch_core(old)
        self.assertEqual(rare.patch_core(updated), updated)
        self.assertIn("LOCAL_CUSTOM = True", updated)
        ast.parse(updated)
        current = (ROOT / "server/backend_app.py").read_text()
        self.assertEqual(rare.patch_core(current), current)

    def test_wallet_frontend_uses_custom_number_and_preserves_owner(self):
        source = (ROOT / "app.js").read_text()
        function = source.split("function applyUserState(user)", 1)[1].split("function clearWalletRetrySchedule", 1)[0]
        prelude = """
let currentUser, usernameEl={},walletNumberEl={},walletHolderEl={},walletStatusEl={};
let walletCardEl=null,balanceEl={},currencyNameEl={},ownerButton={};
const OWNER_WALLET_NUMBER="7777 7777 7777";
const createWalletNumber=()=>"generated";
const walletHolderName=()=>"holder";
"""
        for owner, value, expected in ((False, "NYAN 7777 0000 7777", "NYAN 7777 0000 7777"),
                                        (False, None, "generated"), (True, "custom", "7777 7777 7777")):
            import json
            code = prelude + "function applyUserState(user)" + function
            code += "\napplyUserState(" + json.dumps({"is_owner": owner, "wallet_number": value, "telegram_id": 7}) + ");"
            code += "\nconsole.log(walletNumberEl.textContent);"
            self.assertEqual(subprocess.check_output(["node", "-e", code], text=True).strip(), expected)

    def test_hash_matches_original_javascript(self):
        for uid in (1, 8, 123456789):
            code = """
const s="nyan-wallet:"+process.argv[1];let l=0x811c9dc5,r=0x9e3779b9;
for(let i=0;i<s.length;i++){l=Math.imul(l^s.charCodeAt(i),16777619)>>>0;r=Math.imul(r^s.charCodeAt(i),2246822519)>>>0}
console.log(String(l%1000000).padStart(6,"0")+String(r%1000000).padStart(6,"0"));
"""
            actual = subprocess.check_output(["node", "-e", code, str(uid)], text=True).strip()
            self.assertEqual(rare.generated_number(uid), actual)


class HealthProbeTest(unittest.TestCase):
    def test_slow_startup_waits_and_ignores_proxy_environment(self):
        import io
        from unittest.mock import Mock, patch
        clock = [0.0]
        opener = Mock()
        def open_response(*args, **kwargs):
            if clock[0] < 35:
                raise rare.urllib.error.URLError("not started")
            return io.StringIO('{"ok":true}')
        opener.open.side_effect = open_response
        with patch.object(rare.urllib.request, "build_opener", return_value=opener) as builder, \
             patch.object(rare.time, "monotonic", side_effect=lambda: clock[0]), \
             patch.object(rare.time, "sleep", side_effect=lambda seconds: clock.__setitem__(0, clock[0] + seconds)), \
             patch("builtins.print"):
            rare.health()
        self.assertGreaterEqual(clock[0], 35)
        self.assertEqual(builder.call_args.args[0].proxies, {})

    def test_failed_probe_reports_last_http_status(self):
        from unittest.mock import Mock, patch
        clock = [0.0]
        opener = Mock()
        opener.open.side_effect = rare.urllib.error.HTTPError("http://127.0.0.1:8000/api/health", 503, "busy", {}, None)
        with patch.object(rare.urllib.request, "build_opener", return_value=opener), \
             patch.object(rare.time, "monotonic", side_effect=lambda: clock[0]), \
             patch.object(rare.time, "sleep", side_effect=lambda seconds: clock.__setitem__(0, clock[0] + seconds)):
            with self.assertRaisesRegex(RuntimeError, "HTTP 503"):
                rare.health(timeout=2)


if __name__ == "__main__":
    unittest.main()
