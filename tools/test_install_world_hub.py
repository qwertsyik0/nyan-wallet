import importlib.util,io,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
root=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('hub_installer',root/'tools/install_world_hub.py');mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
class InstallTest(unittest.TestCase):
 def exercise(self,fail):
  with tempfile.TemporaryDirectory() as tmp:
   p=Path(tmp);(p/'server').mkdir();(p/'server/__init__.py').write_text('import os\n# custom\n');(p/'index.html').write_text('<body><div>custom</div></body>');(p/'nyan-world.html').write_text('<body><div id="status"></div></body>');original={name:(p/name).read_bytes() for name in ['server/__init__.py','index.html','nyan-world.html']}
   def ready(world):
    if world and fail:raise RuntimeError('failure')
   with patch.object(sys,'argv',['install','--ref','a'*40]),patch.object(mod.os,'geteuid',return_value=0),patch.object(mod,'value',side_effect=lambda key:'active' if key=='ActiveState' else str(p)),patch.object(mod.urllib.request,'urlopen',side_effect=lambda url,timeout:io.BytesIO(b'# module\n' if url.endswith('.py') else b'asset')),patch.object(mod,'ready',side_effect=ready),patch.object(mod.subprocess,'run') as run:
    if fail:
     with self.assertRaises(RuntimeError):mod.main()
    else:mod.main()
   if fail:
    for name,value in original.items():self.assertEqual((p/name).read_bytes(),value)
    self.assertFalse((p/'server/world_hub.py').exists());self.assertEqual(run.call_count,2)
   else:
    self.assertIn('# custom',(p/'server/__init__.py').read_text());self.assertIn('world-hub-link',(p/'nyan-world.html').read_text());self.assertEqual((p/'index.html').read_text().count('world-hub-entry.js'),1);self.assertEqual(run.call_count,1)
 def test_success(self):self.exercise(False)
 def test_rollback(self):self.exercise(True)
if __name__=='__main__':unittest.main()
