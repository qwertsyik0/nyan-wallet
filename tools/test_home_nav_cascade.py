"""Regression test for the wallet's two coexisting navigation implementations.

The original .actions buttons remain as JavaScript click targets; home_v2.js
renders the *visible* navigation. A more specific rule in interface_shell.css
used to override home_v2.css and show the entire old grid again.
"""

from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
shell = (ROOT / "interface_shell.css").read_text(encoding="utf-8")
home = (ROOT / "home_v2.css").read_text(encoding="utf-8")
client = (ROOT / "home_v2.js").read_text(encoding="utf-8")
html = (ROOT / "index.html").read_text(encoding="utf-8")

# Extract the exact shell rule rather than searching for a stray text comment.
match = re.search(r"#wallet-view\s+\.actions\.nyan-actions-grid\s*\{([^}]*)\}", shell)
assert match, "Legacy navigation shell selector missing"
assert re.search(r"\bdisplay\s*:\s*none\s*!important\b", match.group(1), re.I), (
    "Legacy shell must not force its menu visible above home_v2"
)

assert re.search(r"#wallet-view\s*>\s*\.actions\s*,", home), "Home v2 must hide original buttons"
assert re.search(r"\bdisplay\s*:\s*none\s*!important", home), "Home v2 legacy hiding rule missing"
assert "id = \"nyan-home-v2\"" in client, "New home UI not generated"
assert 'if (target) proxyClick(target);' in client, "Legacy click target delegation removed"
assert '<link rel="stylesheet" href="./home_v2.css?' in html
assert '<link rel="stylesheet" href="./interface_shell.css?' in html
assert html.index('home_v2.css?v=') < html.index('interface_shell.css?v='), "Unexpected stylesheet order"

print("OK: old action grid stays hidden; new home navigation keeps original click handlers")
