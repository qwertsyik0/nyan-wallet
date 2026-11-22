"""Installer regression tests; never touch a running service or real wallet."""
import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("lavka_installer", ROOT / "tools/deploy_nyan_lavka_firstvds.py")
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)
INITIALIZER = "from .user_bans import register_user_bans\nif True:\n    register_user_bans(backend_app.app)\n"

class InstallerTest(unittest.TestCase):
    def test_initializer_without_retired_awards_and_repeat_install(self):
        updated = installer.patch_initializer(INITIALIZER)
        self.assertIn(installer.IMPORT_NEW, updated)
        self.assertIn(installer.CALL_NEW, updated)
        self.assertEqual(installer.patch_initializer(updated), updated)
        self.assertNotIn("nyan_awards", updated)

    def test_missing_anchor_stops_without_silent_append(self):
        with self.assertRaises(RuntimeError):
            installer.patch_initializer("print('custom entry point')\n")

    def test_module_merge_preserves_local_changes(self):
        base = b"SETTING = 1\nVALUE = 10\n" + b"# unchanged\n" * 12
        local = base + b"\nLOCAL_CUSTOMIZATION = True\n"
        newest = b"SETTING = 1\nVALUE = 14\n" + b"# unchanged\n" * 12
        with patch.object(installer, "download_module", return_value=base):
            merged = installer.merge_module(local, newest)
        self.assertIn(b"VALUE = 14", merged)
        self.assertIn(b"LOCAL_CUSTOMIZATION = True", merged)

    def test_conflicting_module_fails_before_writes(self):
        with patch.object(installer, "download_module", return_value=b"VALUE = 1\n"):
            with self.assertRaises(RuntimeError):
                installer.merge_module(b"VALUE = 2\n", b"VALUE = 3\n")

    def test_failed_service_validation_restores_both_files(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "server").mkdir()
            init = root / "server/__init__.py"
            module = root / "server/nyan_lavka.py"
            init.write_text(INITIALIZER)
            module.write_bytes(b"LOCAL = 1\n")
            command_result = subprocess.CompletedProcess([], 0, stdout="active\n", stderr="")
            with patch.object(sys, "argv", ["installer", "--apply", "--root", str(root)]), \
                 patch.object(installer, "find_project", return_value=root), \
                 patch.object(installer, "download_module", return_value=b"NEW = 1\n"), \
                 patch.object(installer, "merge_module", return_value=b"NEW = 1\n"), \
                 patch.object(installer, "command", return_value=command_result), \
                 patch.object(installer.os, "geteuid", return_value=0), \
                 patch.object(installer, "validate_service", side_effect=RuntimeError("test health failure")):
                with self.assertRaisesRegex(RuntimeError, "test health failure"):
                    installer.main()
            self.assertEqual(init.read_text(), INITIALIZER)
            self.assertEqual(module.read_bytes(), b"LOCAL = 1\n")
            self.assertTrue(any((root / ".nyan-lavka-backups").iterdir()))

if __name__ == "__main__":
    unittest.main()
