import importlib.util
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("news_installer", ROOT / "tools/install_world_news_editor.py")
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class InstallerTest(unittest.TestCase):
    def exercise(self, fail):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "server").mkdir()
            (root / "server/nyan_world.py").write_text("# existing world\n")
            (root / "server/__init__.py").write_text("import os\n# custom registration\nregister_world(backend_app.app)\n")
            (root / "nyan-world.html").write_text('<script src="./nyan-world.js?v=old"></script>')
            originals = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
            def get(url, timeout):
                path = url.split("/" + "a" * 40 + "/", 1)[1]
                return io.BytesIO((ROOT / path).read_bytes())
            def ready(editor):
                if fail and editor:
                    raise RuntimeError("simulated readiness failure")
            with patch.object(sys, "argv", ["install", "--ref", "a" * 40]), \
                 patch.object(installer.os, "geteuid", return_value=0), \
                 patch.object(installer, "value", side_effect=lambda key: "active" if key == "ActiveState" else str(root)), \
                 patch.object(installer.urllib.request, "urlopen", side_effect=get), \
                 patch.object(installer, "ready", side_effect=ready), \
                 patch.object(installer.subprocess, "run") as run:
                if fail:
                    with self.assertRaisesRegex(RuntimeError, "simulated"):
                        installer.main()
                else:
                    installer.main()
                    installer.main()
            if fail:
                for path, data in originals.items():
                    self.assertEqual(path.read_bytes(), data)
                self.assertFalse((root / "server/world_news.py").exists())
                self.assertEqual(run.call_count, 2)
            else:
                init = (root / "server/__init__.py").read_text()
                self.assertEqual(init.count("register_world_news(backend_app.app)"), 1)
                self.assertIn("# custom registration", init)
                self.assertEqual((root / "server/nyan_world.py").read_bytes(), originals[root / "server/nyan_world.py"])
                self.assertIn("nyan-world.js?v=20261127-editor1", (root / "nyan-world.html").read_text())
                self.assertTrue((root / "server/world_news_seed.json").is_file())

    def test_install_and_reinstall(self):
        self.exercise(False)

    def test_failure_rolls_back_files(self):
        self.exercise(True)


if __name__ == "__main__":
    unittest.main()
