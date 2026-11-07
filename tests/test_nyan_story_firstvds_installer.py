"""Regression tests for safe installation into the manually patched FirstVDS API."""

import importlib.util
import unittest
from pathlib import Path


source = Path(__file__).resolve().parents[1] / "tools/install_nyan_story_firstvds.py"
spec = importlib.util.spec_from_file_location("story_vps_installer", source)
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class RegistryTests(unittest.TestCase):
    def test_preserves_manual_changes_and_is_idempotent(self):
        current = (
            "from .telegram_relay import register_telegram_relay\n"
            "from .nyan_spy import register_nyan_spy\n"
            "# custom owner's patch\n"
            "if True:\n"
            "    register_telegram_relay(backend_app.app)\n"
            "    register_nyan_spy(backend_app.app)\n"
        ).encode()
        updated = installer.patch_registry(current)
        self.assertIn(b"# custom owner's patch", updated)
        self.assertIn(installer.IMPORT.encode(), updated)
        self.assertIn(installer.REGISTER.encode(), updated)
        self.assertEqual(installer.patch_registry(updated), updated)

    def test_fallback_to_existing_telegram_relay_registration(self):
        original = (
            "from .telegram_relay import register_telegram_relay\n"
            "if True:\n"
            "    register_telegram_relay(backend_app.app)\n"
        ).encode()
        updated = installer.patch_registry(original)
        self.assertIn(installer.IMPORT.encode(), updated)
        self.assertIn(installer.REGISTER.encode(), updated)

    def test_rejects_ambiguous_insertion(self):
        with self.assertRaises(RuntimeError):
            installer.patch_registry(b"# no known registration points\n")

    def test_rejects_partially_installed_registry(self):
        before = (installer.IMPORT + "\n").encode()
        with self.assertRaises(RuntimeError):
            installer.patch_registry(before)


if __name__ == "__main__":
    unittest.main()
