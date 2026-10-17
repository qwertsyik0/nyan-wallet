"""Guard the separate Nyan Elections games signup launch route and UI contract."""

from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
index = (ROOT / "index.html").read_text(encoding="utf-8")
elections = (ROOT / "elections.html").read_text(encoding="utf-8")
page = (ROOT / "election-games.html").read_text(encoding="utf-8")
script = (ROOT / "election-games.js").read_text(encoding="utf-8")
styles = (ROOT / "election-games.css").read_text(encoding="utf-8")
backend = (ROOT / "server" / "elections.py").read_text(encoding="utf-8")

assert '["electiongames", "election_games", "nyan_games"].includes(startParam)' in index
assert 'new URL("./election-games.html", window.location.href)' in index
assert 'if (current.hash) target.hash = current.hash' in index
assert "startapp=electiongames" in elections
assert "startapp=electiongames" in page or "election-games.js" in page
assert 'src="./election-games.js?v=' in page
assert 'href="./election-games.css?v=' in page
for item in [
    "eg-confirm-button", "eg-parties", "eg-existing", "eg-new", "eg-confirmed",
    "eg-owner", "eg-loading", "eg-message"
]:
    assert f'id="{item}"' in page, item
assert 'tg.initData' in script and '"X-Telegram-Init-Data"' in script
assert 'act("/games/confirm", {})' in script
assert 'act("/games/join", {party_id: id})' in script
assert 'api("/games/status")' in script
assert 'api("/owner/games/signups")' in script
assert '.textContent =' in script and "innerHTML" not in script
assert '500 🐾' in page and "после проверки участия" in page
assert '.eg-party' in styles and 'var(--ink)' in styles
for route in ('"/games/status"', '"/games/join"', '"/games/confirm"', '"/owner/games/signups"'):
    assert f"@router." in backend and route in backend, route
assert '"election_game_signups"' in backend
assert 'ElectionGameSignup.__table__.create(bind=core.engine, checkfirst=True)' in backend
print("OK: games page route, signed Telegram actions, buttons, reward conditions and owner roster")
