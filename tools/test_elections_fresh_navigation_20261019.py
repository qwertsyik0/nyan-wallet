"""Regression guard: completed Elections and historical owner views are not in the Wallet UI.

Historical records remain on the backend until the owner authorizes their deletion.
"""
from pathlib import Path

root = Path(__file__).resolve().parents[1]
home = (root / "home_v2.js").read_text(encoding="utf-8")
index = (root / "index.html").read_text(encoding="utf-8")
wallet = (root / "app.js").read_text(encoding="utf-8")
elections = (root / "elections.html").read_text(encoding="utf-8")

assert 'id="nyan-home-elections"' not in home
assert 'data-nyan-elections-link' not in home
assert 'new URL("./elections.html", current.href)' not in home
assert 'startParam === "elections"' not in index
assert 'new URL("./elections.html", window.location.href)' not in index
assert 'id="owner-survey-open"' not in index
assert 'id="finance-applications-open"' not in index
assert 'id="owner-survey-view"' not in index

# Actual trainee workflows must not be affected by retiring candidate review.
assert 'id="owner-finance-workspace"' in index
assert 'finance_workspace' in index
assert "home_v2.js?v=20261019-retire-elections-owner-archive1" in index
assert "97 голосов" in elections and "15:40 19.10.2026" in elections
assert "loadWallet();" in wallet
print("PASS: completed Elections and historical owner sections absent from Wallet, finance workspace intact")
