"""Offline checks for targeted VPS Nyan ID XP installer and rollback-safe patches."""
import ast
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "install_nyan_id_xp_firstvds",
    ROOT / "tools" / "install_nyan_id_xp_firstvds.py",
)
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


def test_registry_patch() -> None:
    current = (ROOT / "server/__init__.py").read_bytes()
    old = current.replace(
        b"from .nyan_experience import register_nyan_experience\n", b"",
    ).replace(
        b"    register_nyan_experience(backend_app.app)\n", b"",
    )
    old += b"\n# local custom code must survive\n"
    patched = installer.patch_registry(old)
    assert patched.count(b"from .nyan_experience import register_nyan_experience\n") == 1
    assert patched.count(b"    register_nyan_experience(backend_app.app)\n") == 1
    assert patched.endswith(b"# local custom code must survive\n")
    assert installer.patch_registry(patched) == patched
    ast.parse(patched.decode("utf-8"))


def test_api_patch() -> None:
    current = (ROOT / "server/nyan_id.py").read_bytes()
    old = current.replace(
        b"from .nyan_experience import experience_for_user\n", b"",
    ).replace(
        b'            "experience": experience_for_user(session, user.telegram_id),\n', b"",
    )
    old += b"\n# local Nyan ID customization retained\n"
    patched = installer.patch_api(old)
    assert patched.count(b"from .nyan_experience import experience_for_user\n") == 1
    assert patched.count(b'"experience": experience_for_user(session, user.telegram_id),') == 1
    assert patched.endswith(b"# local Nyan ID customization retained\n")
    assert installer.patch_api(patched) == patched
    ast.parse(patched.decode("utf-8"))


if __name__ == "__main__":
    test_registry_patch()
    test_api_patch()
    print("Nyan ID VPS installer patch checks: OK")
