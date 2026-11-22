"""Offline validation of the VIP kit; no connection to live wallet data."""
from pathlib import Path
import ast
import subprocess
import shutil

ROOT = Path(__file__).resolve().parents[1]


def test_all_original_assets_present():
    images = list((ROOT / 'assets' / 'vip').glob('*.png'))
    assert len(images) == 17
    for image in images:
        assert image.stat().st_size > 0
    sources = '\n'.join((ROOT / name).read_text() for name in ('vip-plus.js', 'vip-plus.css', 'apply_vip_integration.py'))
    assert all(image.name in sources for image in images if not image.name.startswith('00_'))


def test_server_models_and_owner_gates():
    content = (ROOT / 'server' / 'vip_plus.py').read_text()
    tree = ast.parse(content)
    routes = {d.value for node in ast.walk(tree) if isinstance(node, ast.Call)
              for d in node.args[:1] if isinstance(d, ast.Constant) and isinstance(d.value, str)
              if d.value.startswith('/api/')}
    assert '/api/vip/benefits' in routes
    assert '/api/owner/vip/grants' in routes
    assert '/api/owner/vip/shop-cashback' in routes
    assert '/api/integrations/nyan-shop/cashback' in routes
    assert 'hmac.compare_digest' in content
    assert 'with_for_update()' in content


def test_frontend_syntax():
    if shutil.which('node'):
        subprocess.run(['node', '--check', str(ROOT / 'vip-plus.js')], check=True)


def test_install_script_syntax():
    ast.parse((ROOT / 'apply_vip_integration.py').read_text())


def test_cashback_rounding():
    tree = ast.parse((ROOT / 'server' / 'vip_plus.py').read_text())
    func = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'cashback_lapcoins')
    namespace = {}
    exec(compile(ast.Module(body=[func], type_ignores=[]), '<isolated cashback>', 'exec'), namespace)
    calculate = namespace['cashback_lapcoins']
    assert calculate(25110, vip=False) == 12
    assert calculate(25110, vip=True) == 20
    assert calculate(10000, vip=False) == 5
    assert calculate(10000, vip=True) == 8
    assert calculate(1, vip=True) == 0
