"""Exercise additive installer success and rollback with an existing customized checkout."""
import importlib.util
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location("world_installer",ROOT/"tools/install_nyan_world.py")
installer=importlib.util.module_from_spec(spec);spec.loader.exec_module(installer)
class InstallTest(unittest.TestCase):
    def exercise(self,fail,frontend=False):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/"server").mkdir()
            (root/"server/__init__.py").write_text("import os\n# custom server setup\n")
            (root/"index.html").write_text('<script src="./home_v2.js?v=old"></script></body>')
            (root/"home_v2.js").write_text('const MORE_ACTIONS = [\n ["custom","x","Custom","custom-button"],\n];')
            originals={p:p.read_bytes() for p in (root/"server/__init__.py",root/"index.html",root/"home_v2.js")}
            def value(key): return "active" if key=="ActiveState" else str(root)
            def get(url,timeout): return io.BytesIO(b"# downloaded module\n" if url.endswith(".py") else b"downloaded asset")
            def ready(world):
                if world and fail: raise RuntimeError("simulated readiness failure")
            with patch.object(sys,"argv",["install","--ref","a"*40]+(["--frontend-only"] if frontend else [])),patch.object(installer.os,"geteuid",return_value=0),patch.object(installer,"value",side_effect=value),patch.object(installer.urllib.request,"urlopen",side_effect=get),patch.object(installer,"ready",side_effect=ready),patch.object(installer.subprocess,"run") as run:
                if fail:
                    with self.assertRaisesRegex(RuntimeError,"simulated"): installer.main()
                else: installer.main()
            if fail:
                for p,data in originals.items(): self.assertEqual(p.read_bytes(),data)
                self.assertFalse((root/"server/nyan_world.py").exists())
                self.assertEqual(run.call_count,2)
            else:
                self.assertIn("custom-button",(root/"home_v2.js").read_text())
                self.assertNotIn('"nyan-world-open"',(root/"home_v2.js").read_text())
                self.assertIn("home_v2.js?v=20261125-world-card1",(root/"index.html").read_text())
                self.assertIn("# custom server setup",(root/"server/__init__.py").read_text())
                self.assertEqual((root/"index.html").read_text().count("nyan-world-entry.js"),1)
                self.assertEqual((root/"index.html").read_text().count("nyan-world-invite.js"),1)
                self.assertTrue((root/"nyan-world-info.html").is_file())
                for name in ("nyan-world-rules.html","nyan-world-rules.js","nyan-world-rules.css"):
                    self.assertTrue((root/name).is_file())
                self.assertTrue((root/"assets/nyan-world/nyanik-hold.webp").is_file())
                self.assertEqual(run.call_count,0 if frontend else 1)
                if frontend: self.assertEqual((root/"server/__init__.py").read_bytes(),originals[root/"server/__init__.py"])
    def test_frontend_update_does_not_restart_api(self): self.exercise(False,True)
    def test_additive_install(self): self.exercise(False)
    def test_failed_restart_restores_existing_files(self): self.exercise(True)
if __name__=="__main__": unittest.main()
