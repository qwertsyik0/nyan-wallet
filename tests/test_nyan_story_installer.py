"""Tests for safe idempotent bot command installation (no Telegram access)."""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "install_nyan_story_bot", REPO / "tools/install_nyan_story_bot.py",
)
assert SPEC and SPEC.loader
installer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(installer)


class StoryBotInstallerTests(unittest.TestCase):
    def test_adds_import_and_registration_once(self) -> None:
        source = (
            b'"""Existing bot."""\n'
            b'from __future__ import annotations\n'
            b'from telegram.ext import Application\n'
            b'def main():\n'
            b'    bot_app = Application.builder().token("test").build()\n'
            b'    bot_app.run_polling()\n'
        )
        updated = installer.patch_bot(source)
        text = updated.decode()
        self.assertIn(installer.IMPORT, text)
        self.assertIn("register_nyan_story_bot_handlers(bot_app)", text)
        self.assertLess(text.index("register_nyan_story_bot_handlers(bot_app)"),
                        text.index("bot_app.run_polling()"))
        self.assertEqual(updated, installer.patch_bot(updated))

    def test_refuses_ambiguous_polling(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "ожидался один run_polling"):
            installer.patch_bot(b"def main():\n    pass\n")


if __name__ == "__main__":
    unittest.main()
