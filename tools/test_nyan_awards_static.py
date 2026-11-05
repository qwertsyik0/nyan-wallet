"""Dependency-free asset, route and contract checks for NYAN AWARDS 2026.

Run with: python3 tools/test_nyan_awards_static.py
This is not a substitute for live Telegram/PostgreSQL end-to-end tests.
"""

from __future__ import annotations

import ast
import re
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class Assets(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids: set[str] = set()
        self.assets: list[str] = []

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if "id" in values:
            assert values["id"] not in self.ids, f"Duplicate HTML id {values['id']}"
            self.ids.add(values["id"])
        source = values.get("src") or values.get("href")
        if source and source.startswith("./"):
            self.assets.append(source.split("?", 1)[0])


def main():
    html = (ROOT / "nyan-awards.html").read_text(encoding="utf-8")
    js = (ROOT / "nyan-awards.js").read_text(encoding="utf-8")
    py = (ROOT / "server" / "nyan_awards_2026.py").read_text(encoding="utf-8")

    tree = ast.parse(py)
    category_rows = next(node.value for node in tree.body
                         if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "CATEGORIES" for t in node.targets))
    categories = ast.literal_eval(category_rows)
    ids = {row[0] for row in categories}
    assert len(categories) == len(ids) == 11
    assert {"legend_nyan", "face_nyan", "flood_legend", "mafia_master"}.issubset(ids)
    stars = sum(int(amount) for row in categories for amount in re.findall(r"(\d+) ⭐", row[3]))
    lapcoins = sum(int(amount) for row in categories for amount in re.findall(r"(\d+) 🐾", row[3]))
    accounts = sum("физ." in row[3] for row in categories)
    assert (stars, accounts, lapcoins) == (425, 3, 2800)
    assert stars + 50 == 475, "50 Stars are drawn separately among unique voters"
    assert "475 ⭐" in html and "50 ⭐" in html

    parser = Assets()
    parser.feed(html)
    missing = [path for path in parser.assets if not (ROOT / path).is_file()]
    assert not missing, f"Missing HTML assets: {missing}"
    for selector in re.findall(r"\$\('#([A-Za-z0-9_-]+)'\)", js):
        assert selector in parser.ids, f"JS reference lacks HTML node #{selector}"
    assert set(re.findall(r"(?:^|,)\s*([a-z_]+): '\d{2}_[a-z_]+\.webp'", js, re.M)) == ids
    for asset in re.findall(r"'([0-9]{2}_[a-z_]+\.webp)'", js):
        path = ROOT / "assets" / "nyan-awards" / asset
        assert path.is_file() and path.stat().st_size > 500, f"Missing or empty badge: {asset}"
    assert 'register_nyan_awards_2026(backend_app.app)' in (ROOT / "server" / "__init__.py").read_text(encoding="utf-8")
    assert '"./nyan-awards.html"' in (ROOT / "index.html").read_text(encoding="utf-8")
    assert 'nyan-awards-link' in (ROOT / "home_v2.js").read_text(encoding="utf-8")
    assert '/api/nyan-awards/vote' in py and '/api/nyan-awards/nominate' in py
    assert 'FLOOD_CATEGORY' in py and '_check_partner_member' in py
    assert 'EVIDENCE_CATEGORIES' in py
    assert '/api/owner/nyan-awards/random-voter/draw' in py
    print("OK: 11 categories, 11 icons, assets, DOM references, deep link, registration, vote/auth hooks")


if __name__ == "__main__":
    main()
