"""Regression test: public Elections snapshot is intentionally frozen at 61 votes.

This test reads only static client files; it never connects to a database or Telegram.
"""
from __future__ import annotations

import re
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
html = (ROOT / "elections.html").read_text(encoding="utf-8")
css = (ROOT / "elections.css").read_text(encoding="utf-8")
js = (ROOT / "elections.js").read_text(encoding="utf-8")

start = html.index('<section id="el-static-vote-snapshot"')
finish = html.index("</section>", start)
snapshot = html[start:finish]
assert html.count('id="el-static-vote-snapshot"') == 1
assert html.index('id="el-vote-entry"') < start < html.index('id="el-main"')
assert not re.search(r"<section[^>]*\bhidden\b", snapshot.split(">", 1)[0])

assert "Предварительные результаты" in snapshot
assert "Не обновляется" in snapshot
assert "61 голос" in snapshot
assert "Народный Союз Нян" in snapshot
assert "Independent Femboys 🐾" in snapshot
assert "32 голоса" in snapshot
assert "29 голосов" in snapshot

total = 32 + 29
assert total == 61
for votes, value, text in ((32, "52.46", "52,46%"), (29, "47.54", "47,54%")):
    actual = (Decimal(votes) * 100 / Decimal(total)).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    assert actual == Decimal(value)
    assert f'aria-valuenow="{value}"' in snapshot
    assert f'style="width:{value}%"' in snapshot
    assert text in snapshot

assert "<script" not in snapshot and "fetch(" not in snapshot
assert "el-static-vote-snapshot" not in js
assert ".el-snapshot-fill" in css
assert ".el-snapshot-party" in css
assert "elections.css?v=20261018-vote-snapshot-1" in html
assert "Окончательные итоги" not in snapshot  # The copy describes later publication in lowercase.
print("PASS: 61-vote snapshot, 32/29, percentages, CSS and no live updates")
