"""Pure safety tests for the surgical Nyan Shop curator installer."""

from install_curator_recruitment import IMPORT_LINE, CALL_LINE, patch_init


BASE = """import os
from .fortune import register_fortune
from .custom_local_module import register_local

if os.getenv("NYAN_RESTORE_SCHEMA_ONLY") == "1":
    pass
else:
    register_fortune(backend_app.app)
    register_local(backend_app.app)
"""

patched = patch_init(BASE)
assert patched.count(IMPORT_LINE) == 1
assert patched.count(CALL_LINE) == 1
assert "register_local(backend_app.app)" in patched
assert patch_init(patched) == patched
assert patched.index("register_fortune(backend_app.app)") < patched.index(CALL_LINE)

for content in ("# completely customized\n", BASE.replace("from .fortune import register_fortune", "# removed")):
    try:
        patch_init(content)
    except RuntimeError:
        pass
    else:
        raise AssertionError("An unrecognized server init file must not be overwritten")

print("PASS: curator installer preserves custom modules and is idempotent")
