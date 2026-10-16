"""Regression checks for Elections button in broadcasts and both channel publishers."""

import ast
from pathlib import Path
import os
import re
import urllib.parse

ROOT=Path(__file__).resolve().parents[1]
app_url="https://qwertsyik0.github.io/nyan-wallet/elections.html"

def load(name):
    return (ROOT/"bot_addons"/name).read_text(encoding="utf-8")

def one_func(source,name):
    tree=ast.parse(source)
    functions=[n for n in tree.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name==name]
    assert len(functions)==1, "Missing function "+name
    return functions[0]

broadcast=load("broadcast_bot.py")
legacy=load("channel_publish_bot.py")
newer=load("channel_publish_bot_v2.py")
for src,marker,callback in (
    (broadcast,"bc:add_elections","def _add_elections_button"),
    (legacy,"ch:add_elections","def _add_elections_button"),
    (newer,"cp2:add_elections","def _add_elections_button"),
):
    ast.parse(src)
    assert marker in src, marker+" is absent from editor"
    assert callback in src, "One-click Elections preset not defined"
    assert src.count('ELECTIONS_MINI_APP_URL = "')==1
    assert app_url in src, "Invalid Elections page destination"
    assert 'text="🗳 Выборы"' in src
    assert 'kind="web_app"' in src
    assert 'elif action == "add_elections"' in src or 'if action == "add_elections"' in src

# Run only two small pure helpers, without importing or booting a Telegram bot.
common={"os":os,"urllib":urllib,"re":re,
        "PROMO_SLUG_PATTERN":re.compile(r"^[a-z0-9_-]{2,48}$",re.I)}
for source,helper_name,extra in (
    (legacy,"_start_param_for_url",None),
    (newer,"_wallet_start_param",None),
):
    namespace=dict(common)
    helper=one_func(source,helper_name)
    exec(compile(ast.Module(body=[helper],type_ignores=[]),"<button routes>","exec"),namespace)
    assert namespace[helper_name](app_url)=="elections", "Wrong Elections start parameter"
    if helper_name=="_start_param_for_url":
        assert namespace[helper_name](app_url+"?startapp=elections")=="elections"
    else:
        assert namespace[helper_name](app_url+"?startapp=elections")=="elections"

legacy_ns=dict(common)
for name in ("_start_param_for_url","_mini_app_deep_link"):
    exec(compile(ast.Module(body=[one_func(legacy,name)],type_ignores=[]),"<legacy>","exec"),legacy_ns)
new_ns=dict(common)
for name in ("_wallet_start_param","_mini_app_deep_link"):
    exec(compile(ast.Module(body=[one_func(newer,name)],type_ignores=[]),"<v2>","exec"),new_ns)
for ns in (legacy_ns,new_ns):
    actual=ns["_mini_app_deep_link"](app_url,"nyancash_bot")
    assert actual=="https://t.me/nyancash_bot?startapp=elections", actual

index=(ROOT/"index.html").read_text(encoding="utf-8")
page=(ROOT/"elections.html").read_text(encoding="utf-8")
js=(ROOT/"elections.js").read_text(encoding="utf-8")
assert 'startParam === "elections"' in index
assert 'new URL("./elections.html", window.location.href)' in index
assert 'target.hash = current.hash' in index, "Telegram launch hash is not preserved"
assert 'elections.js?' in page and 'elections.css?' in page
assert 'X-Telegram-Init-Data' in js and 'if(!tg?.initData)' in js
assert "/api/elections" in js
assert "startapp=elections" not in js, "Avoid nested Mini App loops"
home_script=(ROOT/"home_v2.js").read_text(encoding="utf-8")
home_style=(ROOT/"home_v2.css").read_text(encoding="utf-8")
assert 'id="nyan-home-elections"' in home_script, "Elections button missing from main wallet screen"
assert 'data-nyan-elections-link' in home_script
assert 'new URL("./elections.html", current.href)' in home_script, "Home link does not navigate to Elections"
assert 'destination.search = current.search' in home_script
assert 'destination.hash = current.hash' in home_script, "Telegram launch hash lost from wallet navigation"
assert ".nyan-home-elections{" in home_style
assert "home_v2.js?v=20261016-elections-home1" in index
assert "home_v2.css?v=20261016-elections-home1" in index
assert 'class="nyan-home-primary"' not in home_script, "Large action tiles recreated"

print("OK: private broadcast Mini App, channel URL deep links, and Elections page all agree.")
