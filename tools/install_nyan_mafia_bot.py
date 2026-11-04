#!/usr/bin/env python3
"""Prepare the existing Telegram bot to accept /mafia from its owner.

Run on the BOT host (where bot.py and python-telegram-bot are installed):
  python3 install_nyan_mafia_bot.py --root /path/to/bot --check
  python3 install_nyan_mafia_bot.py --root /path/to/bot --apply

Never sends a message or starts a round. Does not restart the bot service.
"""

from __future__ import annotations

import argparse
import ast
import datetime
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

RAW = ("https://raw.githubusercontent.com/qwertsyik0/nyan-wallet/"
       "4e04979a5cc3e1420da44613eac9045955dcb691/bot_addons/nyan_mafia_bot.py")
IMPORT = "from nyan_mafia_bot import register_nyan_mafia_bot_handlers"
REG = "register_nyan_mafia_bot_handlers"
REG_CALL = REG + "("

def fetch() -> bytes:
    with urllib.request.urlopen(
        urllib.request.Request(RAW, headers={"User-Agent": "NyanMafiaBotInstaller"}),
        timeout=20,
    ) as response:
        data = response.read(80001)
    if not 1000 <= len(data) <= 80000:
        raise RuntimeError("получен неверный модуль бота")
    ast.parse(data.decode("utf-8"), filename="nyan_mafia_bot.py")
    if 'CommandHandler("mafia"' not in data.decode("utf-8"):
        raise RuntimeError("команда /mafia не найдена")
    return data

def patch(source: bytes) -> bytes:
    body = source.decode("utf-8")
    tree = ast.parse(body, filename="bot.py")
    polling = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "run_polling":
            if not isinstance(node.func.value, ast.Name):
                raise RuntimeError("не удалось определить экземпляр Application")
            polling.append((node.lineno, node.func.value.id))
    if len(polling) != 1:
        raise RuntimeError("ожидался один запуск run_polling, найдено: " + str(len(polling)))
    if REG_CALL in body and IMPORT not in body:
        raise RuntimeError("обнаружено частичное подключение Mafia")
    if IMPORT in body and REG_CALL not in body:
        raise RuntimeError("обнаружено частичное подключение Mafia")
    if IMPORT in body:
        return source
    # Import lives at module scope; registration immediately before run_polling.
    lines = body.splitlines(keepends=True)
    insert_at = 0
    nodes = tree.body
    if nodes and isinstance(nodes[0], ast.Expr) and isinstance(nodes[0].value, ast.Constant):
        if isinstance(nodes[0].value.value, str):
            insert_at = nodes[0].end_lineno
    for node in nodes:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            insert_at = max(insert_at, node.end_lineno)
    lines[insert_at:insert_at] = [IMPORT + "\n"]
    newer = "".join(lines)
    newer_lines = newer.splitlines(keepends=True)
    newer_tree = ast.parse(newer, filename="bot.py")
    calls = []
    for node in ast.walk(newer_tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "run_polling":
            calls.append((node.lineno, node.func.value.id))
    line_no, app_name = calls[0]
    line = newer_lines[line_no - 1]
    indent = line[:len(line) - len(line.lstrip())]
    newer_lines[line_no - 1:line_no - 1] = [f"{indent}{REG}({app_name})\n"]
    result = "".join(newer_lines)
    ast.parse(result, filename="bot.py")
    return result.encode("utf-8")

def atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=".mafia-bot-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp, path.stat().st_mode & 0o777 if path.exists() else 0o644)
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)

def restart_existing_bot(root: Path) -> None:
    """Reuse the existing single-process nohup restart mechanism."""
    helper = Path("/home/nyanteam/nyan-wallet/tools/nyan_bot_autodeploy.py")
    if not helper.is_file():
        raise RuntimeError("не найден проверенный помощник запуска бота: " + str(helper))
    sys.path.insert(0, str(helper.parent))
    from nyan_bot_autodeploy import BOT, restart_nohup
    if BOT.resolve() != root.resolve():
        raise RuntimeError("путь бота отличается от настроенного auto-deploy: " + str(BOT))
    restart_nohup()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--apply", action="store_true")
    parser.add_argument("--root", type=Path, default=Path("/home/nyanteam/new_bot"))
    parser.add_argument("--restart", action="store_true", help="Перезапустить единственный существующий процесс бота после установки")
    args = parser.parse_args()
    root = args.root.resolve()
    bot = root / "bot.py"
    addon = root / "nyan_mafia_bot.py"
    if not bot.is_file() or bot.is_symlink() or addon.is_symlink():
        raise RuntimeError("бот не найден или файлы являются символическими ссылками")
    module = fetch()
    updated_bot = patch(bot.read_bytes())
    changes = [
        (bot, updated_bot),
        (addon, module),
    ]
    changed = [(path, content) for path, content in changes
               if not path.exists() or path.read_bytes() != content]
    for path, _ in changed:
        print("изменить:", path)
    if args.check:
        print("проверено, ничего не изменено")
        return
    if not changed:
        print("обработчик команды уже установлен")
        if args.restart:
            restart_existing_bot(root)
        return
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d-%H%M%S")
    backup = root / (".nyan-mafia-bot-backup-" + stamp)
    backup.mkdir(parents=True, exist_ok=False)
    for path, _ in changed:
        if path.is_file():
            shutil.copy2(path, backup / path.name)
    original = [(p, p.read_bytes() if p.is_file() else None) for p, _ in changed]
    try:
        for path, data in changed:
            atomic_write(path, data)
        preferred = root / "venv/bin/python"
        if not preferred.is_file():
            preferred = root / ".venv/bin/python"
        interpreter = str(preferred) if preferred.is_file() else sys.executable
        test = subprocess.run([interpreter, "-m", "py_compile", str(bot), str(addon)],
                              text=True, capture_output=True)
        if test.returncode:
            raise RuntimeError(test.stderr[-1000:])
        if args.restart:
            restart_existing_bot(root)
    except Exception:
        for path, prior in reversed(original):
            if prior is None:
                path.unlink(missing_ok=True)
            else:
                atomic_write(path, prior)
        if args.restart:
            try:
                restart_existing_bot(root)
                print("восстановлен прежний бот", file=sys.stderr)
            except Exception as rollback_error:
                print("ОШИБКА восстановления прежнего бота:", rollback_error, file=sys.stderr)
        raise
    print("обработчик /mafia подготовлен")
    print("резервная копия:", backup)
    print("бот перезапущен" if args.restart else "бот не перезапускался")
    print("регистрация не открывалась, никаких сообщений не отправлено")

if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        raise SystemExit("ОШИБКА: " + str(exc)) from exc
