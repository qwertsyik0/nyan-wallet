import importlib.util,io,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
root=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('tools_installer',root/'tools/install_wallet_plus.py');mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
class InstallTest(unittest.TestCase):
 def run_install(self,fail=False):
  with tempfile.TemporaryDirectory() as tmp:
   p=Path(tmp);(p/'server').mkdir();(p/'server/__init__.py').write_text('import os\n# customized\n');(p/'index.html').write_text('<body><script src="./advanced_features.js?v=old"></script><div>custom</div></body>');original=(p/'index.html').read_bytes()
   def ready(world):
    if world and fail:raise RuntimeError('failure')
   with patch.object(sys,'argv',['install','--ref','a'*40]),patch.object(mod.os,'geteuid',return_value=0),patch.object(mod,'value',side_effect=lambda key:'active' if key=='ActiveState' else str(p)),patch.object(mod.urllib.request,'urlopen',side_effect=lambda url,timeout:io.BytesIO(b'# module\n' if url.endswith('.py') else b'asset')),patch.object(mod,'ready',side_effect=ready),patch.object(mod.subprocess,'run') as run:
    if fail:
     with self.assertRaises(RuntimeError):mod.main()
    else:mod.main()
   if fail:
    self.assertEqual((p/'index.html').read_bytes(),original);self.assertFalse((p/'server/wallet_plus.py').exists());self.assertEqual(run.call_count,2)
   else:
    self.assertIn('custom',(p/'index.html').read_text());self.assertEqual((p/'index.html').read_text().count('wallet-plus-entry.js'),1);self.assertIn('# customized',(p/'server/__init__.py').read_text());self.assertIn('register_wallet_plus',(p/'server/__init__.py').read_text());self.assertEqual(run.call_count,1);self.assertIn('advanced_features.js?v=20261126-plus2',(p/'index.html').read_text())
 def test_install(self):self.run_install()
 def test_rollback(self):self.run_install(True)
if __name__=='__main__':unittest.main()

