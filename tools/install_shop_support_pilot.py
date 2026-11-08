#!/usr/bin/env python3
"""Install the private shop support addon into an existing PTB polling bot.

Dry-run by default. Run with --apply on the bot server, then set the pilot
environment flag and restart the existing bot service manually.
"""
from __future__ import annotations

import argparse
import ast
import shutil
import urllib.request
from datetime import datetime
from pathlib import Path

RAW_MODULE = "https://raw.githubusercontent.com/qwertsyik0/nyan-wallet/main/bot_addons/shop_support_bot.py"


REGISTER = "register_shop_support_handlers"
IMPORT = "from shop_support_bot import register_shop_support_handlers\n"


def patch_source(source: str) -> str:
    tree = ast.parse(source)
    if any(isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == REGISTER for node in ast.walk(tree)):
        return source
    polling = [node for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "run_polling"]
    if len(polling) != 1 or not isinstance(polling[0].func.value, ast.Name):
        raise ValueError("Expected one app.run_polling() call; patch stopped")
    node = polling[0]
    lines = source.splitlines(keepends=True)
    target = lines[node.lineno - 1]
    indent = target[:len(target) - len(target.lstrip())]
    lines.insert(node.lineno - 1, f"{indent}{REGISTER}({node.func.value.id})\n")
    source = "".join(lines)
    if not any(isinstance(node, ast.ImportFrom) and node.module == "shop_support_bot" for node in ast.walk(tree)):
        parsed = ast.parse(source)
        insert_at = 0
        for i, item in enumerate(parsed.body):
            if i == 0 and isinstance(item, ast.Expr) and isinstance(item.value, ast.Constant) and isinstance(item.value.value, str):
                insert_at = item.end_lineno
            elif isinstance(item, ast.ImportFrom) and item.module == "__future__":
                insert_at = item.end_lineno
        lines = source.splitlines(keepends=True)
        lines.insert(insert_at, IMPORT)
        source = "".join(lines)
    ast.parse(source)
    return source


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="/home/nyanteam/new_bot")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    root = Path(args.root).resolve()
    bot = root / "bot.py"
    addon = root / "shop_support_bot.py"
    source = Path(__file__).resolve().parent.parent / "bot_addons" / "shop_support_bot.py"
    if not bot.is_file():
        raise SystemExit("Missing bot.py")
    module_bytes = source.read_bytes() if source.is_file() else urllib.request.urlopen(RAW_MODULE, timeout=20).read()
    patched = patch_source(bot.read_text(encoding="utf-8"))
    compile(patched, str(bot), "exec")
    compile(module_bytes, str(addon), "exec")
    if not args.apply:
        print("DRY RUN OK: bot registration and addon syntax valid; no files changed")
        return
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    shutil.copy2(bot, root / f"bot.py.bak.{stamp}")
    if addon.exists():
        shutil.copy2(addon, root / f"shop_support_bot.py.bak.{stamp}")
    # Write the addon first; only then activate its registration.
    addon.write_bytes(module_bytes)
    bot.write_text(patched, encoding="utf-8")
    print("Installed in closed pilot mode. Restart the existing bot process to activate.")
    print("No public commands or global keyboard were modified.")


if __name__ == "__main__":
    main()
