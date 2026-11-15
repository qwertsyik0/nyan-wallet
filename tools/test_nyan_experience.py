"""Standard-library-only regression checks for shared Nyan ID progression."""
from __future__ import annotations

import ast
from pathlib import Path


SOURCE = Path("server/nyan_experience.py")
SCRIPT = Path("nyan_id.js")
STYLES = Path("nyan_id.css")


def load_level_formula():
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    definitions = [
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "level_for_xp"
    ]
    assert len(definitions) == 1
    module = ast.Module(body=definitions, type_ignores=[])
    scope: dict = {}
    exec(compile(ast.fix_missing_locations(module), str(SOURCE), "exec"), scope)
    return scope["level_for_xp"]


def test_level_boundaries():
    calculate = load_level_formula()
    cases = [
        (-10, 1, 0, 100, 100),
        (0, 1, 0, 100, 100),
        (99, 1, 99, 100, 1),
        (100, 2, 0, 125, 125),
        (224, 2, 124, 125, 1),
        (225, 3, 0, 150, 150),
        (375, 4, 0, 175, 175),
        (1000, 6, 250, 225, -25),
    ]
    # The final large-value boundary is checked independently to avoid
    # coupling the test to an assumed maximum level.
    for xp, level, within, next_goal, remaining in cases[:-1]:
        item = calculate(xp)
        assert item["level"] == level, (xp, item)
        assert item["current_level_xp"] == within, (xp, item)
        assert item["next_level_xp"] == next_goal, (xp, item)
        assert item["remaining_xp"] == remaining, (xp, item)
        assert 0 <= item["progress_percent"] <= 100
    high = calculate(100000)
    assert high["level"] > 10
    assert high["remaining_xp"] > 0
    assert 0 <= high["current_level_xp"] < high["next_level_xp"]


def test_owner_guard_and_idempotency():
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    classes = [node for node in tree.body if isinstance(node, ast.ClassDef)]
    assert any(node.name == "NyanExperienceEvent" for node in classes)
    endpoint = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "award_verified_experience"
    )
    source = ast.unparse(endpoint)
    assert "core.require_owner(owner)" in source
    assert "NyanExperienceEvent.event_key == event_key" in source
    assert "already_recorded" in source
    assert "event_key = payload.event_key.strip()" in source
    assert "payload.xp" not in source


def test_frontend_has_consistent_xp_panel():
    js = SCRIPT.read_text(encoding="utf-8")
    css = STYLES.read_text(encoding="utf-8")
    for selector in (
        "nyid-xp-level", "nyid-xp-total", "nyid-xp-track",
        "nyid-xp-fill", "nyid-xp-info", "nyid-xp-sources",
    ):
        assert selector in js, selector
    assert ".nyid-xp" in css
    assert "updateExperience(data.experience)" in js


if __name__ == "__main__":
    test_level_boundaries()
    test_owner_guard_and_idempotency()
    test_frontend_has_consistent_xp_panel()
    print("Nyan ID shared XP checks: OK")
