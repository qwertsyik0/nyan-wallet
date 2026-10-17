"""Regression checks for mobile owner-panel user rows.

The owner directory contains long Telegram IDs, timestamps, usernames, and
balances. Grid min-content sizing must not push the balance off the viewport.
"""

from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
css = (ROOT / "style.css").read_text(encoding="utf-8")
html = (ROOT / "index.html").read_text(encoding="utf-8")
js = (ROOT / "app.js").read_text(encoding="utf-8")


def block(selector: str) -> str:
    pattern = r"(?m)^" + re.escape(selector) + r"\s*\{([^}]*)\}"
    matches = list(re.finditer(pattern, css))
    assert matches, f"Missing owner layout rule: {selector}"
    # The selector also appears in a shared rule; inspect its final override.
    return matches[-1].group(1)


def has(style: str, property_name: str, expected_pattern: str) -> bool:
    return re.search(
        r"(?m)^\s*" + re.escape(property_name) + r"\s*:\s*" + expected_pattern + r"\s*;",
        style,
        re.I,
    ) is not None


list_css = block("#owner-view .owner-users-list")
assert has(list_css, "grid-template-columns", r"minmax\(0,\s*1fr\)")
assert has(list_css, "width", r"100%")

row_css = block(".owner-user-row")
assert has(row_css, "display", "grid"), "User cards need shrinkable grid columns"
assert has(row_css, "grid-template-columns", r"minmax\(0,\s*1fr\)\s+auto")
assert has(row_css, "width", r"100%")
assert has(row_css, "max-width", r"100%")
assert has(row_css, "min-width", r"0")

main_css = block(".owner-user-row-main")
assert has(main_css, "min-width", "0")
name_css = block(".owner-user-row-name")
assert has(name_css, "text-overflow", "ellipsis")
meta_css = block(".owner-user-row-meta")
assert has(meta_css, "overflow-wrap", "anywhere"), "Long Telegram IDs must wrap"
assert has(meta_css, "white-space", "normal"), "Dates must not stretch row"
balance_css = block(".owner-user-row-balance")
assert has(balance_css, "max-width", r"min\(120px,\s*40vw\)")
assert has(balance_css, "text-align", "right")
assert has(balance_css, "overflow-wrap", "anywhere")

assert 'id="owner-users-list"' in html
assert 'id="owner-user-search"' in html
assert "style.css?v=20261017-owner-users-mobile2" in html, "Telegram WebView could cache the old clipping CSS"
assert 'button.className = "owner-user-row"' in js
assert 'name.className = "owner-user-row-name"' in js
assert 'meta.className = "owner-user-row-meta"' in js
assert 'balance.className = "owner-user-row-balance"' in js
assert 'button.addEventListener("click", () => selectOwnerUser(user.telegram_id))' in js

print("OK: owner user cards retain clickable rows and shrink to mobile viewport without clipping balance")
