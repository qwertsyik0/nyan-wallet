"""Pure tests of the surgical fortune installer; never change systemd or wallet data."""

from pathlib import Path
import importlib.util


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("fortune_installer", ROOT / "tools/install_fortune_server.py")
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)

old = """from .lottery import register_lottery
from .interactive_builder import register_interactive_builder
if True:
    register_lottery(backend_app.app)
    register_interactive_builder(backend_app.app)
"""
new = installer.patch_init(old)
assert new.count("from .fortune import register_fortune") == 1
assert new.count("    register_fortune(backend_app.app)") == 1
assert "from .interactive_builder import register_interactive_builder" in new
assert installer.patch_init(new) == new
assert "register_lottery(backend_app.app)\n    register_fortune(backend_app.app)\n" in new

for bad in ["from .lottery import register_lottery\n", old + old]:
    try:
        installer.patch_init(bad)
    except RuntimeError:
        pass
    else:
        raise AssertionError("Expected installer to reject a missing or duplicated anchor")

print("OK: surgical import/registration patch is idempotent and preserves local modules")
