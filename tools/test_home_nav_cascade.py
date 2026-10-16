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


# Compact home keeps just one visible action area; every operation lives under "Ещё".
import ast

actions_match = re.search(r"const MORE_ACTIONS\s*=\s*\[(.*?)\];", client, re.S)
assert actions_match, "Single compact More menu definition missing"
menu = ast.literal_eval("[" + actions_match.group(1) + "]")
targets = [row[3] for row in menu]
assert targets == [
    "earn-button",
    "spend-button",
    "transfer-button",
    "wallet-qr-button",
    "adv-profile-button",
    "adv-notifications-button",
    "nyg-my-button",
    "nyg-my-purchases-button",
    "appeals-button",
], "An action is missing, duplicated or improperly routed in the More menu"
assert len(set(targets)) == len(targets), "Duplicate actions in More"
assert 'class="nyan-home-primary"' not in client, "Old big action tiles were recreated"
assert 'MORE_ACTIONS.map(' in client and 'class="nyan-home-more-button"' in client
assert '<section class="actions" hidden aria-hidden="true">' in html, "Original large action grid is visible in the document"
assert 'legacyActions.style.setProperty("display", "none", "important");' in client, "Old cached CSS can resurrect original grid"
assert '#nyan-home-v2>.nyan-home-primary' in home, "Outdated JS might recreate large action tiles"
assert 'id="nyan-home-owner"' in client and 'ownerProxy.disabled' in client, "Owner menu access must remain conditional"
assert '"nyan-home-badge"' in client, "Notification badge must remain available"
print("OK: all nine actions are compact More entries; original large buttons cannot appear")

print("OK: old action grid stays hidden; new home navigation keeps original click handlers")
