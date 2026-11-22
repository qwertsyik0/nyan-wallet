"""Regression checks for the safe VIP installer merge fallback.

No production files, PostgreSQL, Git history or services are touched.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

root = Path(__file__).resolve().parents[1]
p = root / "tools" / "install_vip_preserving_vps.py"
spec = importlib.util.spec_from_file_location("_nyan_vip_installer", p)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

# Preserve every existing module import and registration.
local = (
    "from .advanced_features import register_advanced_features\n"
    "from .custom_project import register_custom_project\n"
    "def bootstrap():\n"
    "    register_advanced_features(backend_app.app)\n"
    "    register_custom_project(backend_app.app)\n"
).encode()
patched = module._merge_init_semantically(local).decode()
assert "from .custom_project import register_custom_project" in patched
assert "    register_custom_project(backend_app.app)" in patched
assert patched.count("from .vip import register_vip") == 1
assert patched.count("    register_vip(backend_app.app)") == 1
assert module._merge_init_semantically(patched.encode()).decode() == patched

# A changed unrelated line survives VIP insertion.
base = "def start():\n    first()\n    second()\n    third()\n"
vip = "def start():\n    first()\n    activate_vip()\n    second()\n    third()\n"
custom = "def start():\n    first()\n    second()\n    third()\n    extra_local_feature()\n"
merged = module._add_vip_delta("example.py", custom.encode(), base.encode(), vip.encode()).decode()
assert "activate_vip()" in merged
assert "extra_local_feature()" in merged
assert merged.index("activate_vip()") < merged.index("second()")

# Replacement of a uniquely identifiable line preserves unrelated local edits.
base = "def buy():\n    mark_pending()\n    return value\n"
vip = "def buy():\n    mark_fulfilled()\n    return value\n"
custom = "def buy():\n    mark_pending()\n    return value\n\n# Local unrelated note\n"
merged = module._add_vip_delta("another.py", custom.encode(), base.encode(), vip.encode()).decode()
assert "mark_fulfilled()" in merged and "mark_pending()" not in merged
assert "# Local unrelated note" in merged

# Overlapping changes must NOT be overwritten or silently repaired.
try:
    module._add_vip_delta(
        "conflict.py",
        b"def buy():\n    local_alternative()\n    return value\n",
        base.encode(), vip.encode(),
    )
except RuntimeError as error:
    assert "overlap" in str(error)
else:
    raise AssertionError("A genuine local conflict must be rejected")


# VPS index often has newer Nyan ID cache versions and extra local scripts.
local_html = (
    '<head>\n'
    '  <link rel="stylesheet" href="./nyan_id.css?v=20261115-custom">\n'
    '  <link rel="stylesheet" href="./local-only.css">\n'
    '</head>\n'
    '<body>\n'
    '<script src="./nyan_id.js?v=20261119-local"></script>\n'
    '<script src="./local-confessions.js"></script>\n'
    '</body>\n'
).encode()
merged_html = module._merge_index_semantically(local_html)
assert b"local-only.css" in merged_html and b"local-confessions.js" in merged_html
assert merged_html.count(b'vip.js?v=') == 1
assert merged_html.count(b'vip.css?v=') == 1
assert b"nyan_id.js?v=20261122-vip2" in merged_html
assert module._merge_index_semantically(merged_html) == merged_html

vip_css = (
    b".old-styles{color:red}\n"
    b"/* Paid VIP is independent from the lifetime-earned rank. */\n"
    b".nyid-card.nyid-vip-active{border:2px solid pink}\n"
)
custom_css = b".old-styles{color:blue}\n.my-local-class{color:green}\n"
merged_css = module._merge_nyan_id_css_semantically(custom_css, vip_css)
assert b".my-local-class{color:green}" in merged_css
assert b".nyid-card.nyid-vip-active" in merged_css
assert module._merge_nyan_id_css_semantically(merged_css, vip_css) == merged_css

print("VIP installer semantic merge, preservation and conflict protection: OK")
