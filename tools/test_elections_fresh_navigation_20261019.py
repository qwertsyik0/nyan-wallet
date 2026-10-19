"""Regression guard: opening Elections must bypass a stale Telegram WebView HTML cache."""
from pathlib import Path

root = Path(__file__).resolve().parents[1]
home = (root / "home_v2.js").read_text(encoding="utf-8")
index = (root / "index.html").read_text(encoding="utf-8")
vote = (root / "elections-vote.js").read_text(encoding="utf-8")
ballot = (root / "elections-vote.html").read_text(encoding="utf-8")
elections = (root / "elections.html").read_text(encoding="utf-8")

assert 'target.searchParams.set("snapshot", String(Date.now()))' in index
assert 'destination.searchParams.set("snapshot", String(Date.now()))' in home
assert 'url.searchParams.set("snapshot",String(Date.now()))' in vote
assert 'home_v2.js?v=20261019-elections-fresh-snapshot1' in index
assert 'elections-vote.js?v=20261019-election-snapshot-fresh1' in ballot

# Query cache-busters must not strip the Telegram launch hash or signed context.
assert 'target.hash = current.hash;' in index
assert 'destination.hash = current.hash;' in home
assert 'url.hash=location.hash;' in vote

assert '74 голоса' in elections
assert '36 голосов' in elections and '38 голосов' in elections
assert '48,65%' in elections and '51,35%' in elections
assert '10:10 19.10.2026' in elections
print("PASS: fresh Elections navigation, signed Telegram context and 10:10 snapshot")
