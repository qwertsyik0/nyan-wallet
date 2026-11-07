#!/usr/bin/env python3
"""Safely attach /story and /story_close to the existing Telegram bot.

On the bot host, directly from a downloaded copy or repo checkout:
  python3 install_nyan_story_bot.py --root /home/nyanteam/new_bot --check
  python3 install_nyan_story_bot.py --root /home/nyanteam/new_bot --apply --restart

This never opens a game round or sends a Telegram invitation.
"""

from __future__ import annotations

import argparse
import ast
import datetime
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path


SOURCE = Path(__file__).resolve().parents[1] / "bot_addons/nyan_story_bot.py"
SOURCE_URL = (
    "https://raw.githubusercontent.com/qwertsyik0/nyan-wallet/"
    "feat/nyan-story-signup-20261107/bot_addons/nyan_story_bot.py"
)
SOURCE_SHA256 = "f57f204f0ef45449dc0eea7dd1a924a7720916acaef065b5b4d7de353b066479"
IMPORT = "from nyan_story_bot import register_nyan_story_bot_handlers"
REGISTER = "register_nyan_story_bot_handlers"


def read_addon() -> bytes:
    if SOURCE.is_file():
        data = SOURCE.read_bytes()
    else:
        with urllib.request.urlopen(
            urllib.request.Request(SOURCE_URL, headers={"User-Agent": "Nyan-Story-Bot-Install/1"}),
            timeout=25,
        ) as response:
            data = response.read(100_001)
    if len(data) > 100_000 or hashlib.sha256(data).hexdigest() != SOURCE_SHA256:
        raise RuntimeError("контрольная сумма модуля бота не совпала")
    ast.parse(data, filename="nyan_story_bot.py")
    return data


def bot_supervisor(root: Path):
    script = Path("/home/nyanteam/nyan-wallet/tools/nyan_bot_autodeploy.py")
    if not script.is_file():
        raise RuntimeError("на VPS не найден действующий supervisor бота")
    spec = importlib.util.spec_from_file_location("nyan_story_existing_supervisor", script)
    supervisor = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(supervisor)
    if supervisor.BOT.resolve() != root:
        raise RuntimeError("supervisor обслуживает другой каталог бота")
    if supervisor.CONFIG.is_file():
        cfg = json.loads(supervisor.CONFIG.read_text(encoding="utf-8"))
        if Path(cfg.get("bot_root", "")).resolve() != root:
            raise RuntimeError("настройки supervisor указывают на другой каталог бота")
        if supervisor.service_command(cfg, "is-active", check=False).returncode:
            raise RuntimeError("служба бота не активна; перезапуск отменён")
        return lambda: supervisor.service_command(cfg, "restart")
    if len(supervisor.find_bot_processes()) != 1:
        raise RuntimeError("не найден единственный активный бот; перезапуск отменён")
    return supervisor.restart_nohup


def patch_bot(source: bytes) -> bytes:
    body = source.decode("utf-8")
    tree = ast.parse(body, filename="bot.py")
    if (IMPORT in body) != (REGISTER + "(" in body):
        raise RuntimeError("обнаружено частичное подключение /story")
    if IMPORT in body:
        return source

    polling = []
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "run_polling"):
            if not isinstance(node.func.value, ast.Name):
                raise RuntimeError("неизвестное имя Telegram Application")
            polling.append((node.lineno, node.func.value.id))
    if len(polling) != 1:
        raise RuntimeError(f"ожидался один run_polling, найдено {len(polling)}")

    lines = body.splitlines(keepends=True)
    insertion = 0
    if (tree.body and isinstance(tree.body[0], ast.Expr)
            and isinstance(tree.body[0].value, ast.Constant)
            and isinstance(tree.body[0].value.value, str)):
        insertion = tree.body[0].end_lineno
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            insertion = max(insertion, node.end_lineno)
    lines[insertion:insertion] = [IMPORT + "\n"]
    body = "".join(lines)
    tree = ast.parse(body, filename="bot.py")
    calls = [node for node in ast.walk(tree)
             if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
             and node.func.attr == "run_polling"]
    call = calls[0]
    lines = body.splitlines(keepends=True)
    at = call.lineno - 1
    indent = lines[at][:len(lines[at]) - len(lines[at].lstrip())]
    lines[at:at] = [f"{indent}{REGISTER}({call.func.value.id})\n"]
    result = "".join(lines).encode("utf-8")
    ast.parse(result, filename="bot.py")
    return result


def atomic_write(path: Path, payload: bytes) -> None:
    fd, name = tempfile.mkstemp(prefix=".nyan-story-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(name, path.stat().st_mode & 0o777 if path.exists() else 0o644)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--apply", action="store_true")
    parser.add_argument("--restart", action="store_true", help="Перезапустить только штатный процесс Telegram-бота")
    parser.add_argument("--root", type=Path, default=Path("/home/nyanteam/new_bot"))
    args = parser.parse_args()
    if args.restart and not args.apply:
        raise RuntimeError("--restart применим только вместе с --apply")
    root = args.root.resolve()
    bot = root / "bot.py"
    addon = root / "nyan_story_bot.py"
    if not bot.is_file() or bot.is_symlink() or addon.is_symlink():
        raise RuntimeError("файл bot.py не найден или обнаружена символическая ссылка")
    module = read_addon()
    updated = patch_bot(bot.read_bytes())
    changes = [(path, content) for path, content in ((bot, updated), (addon, module))
               if not path.exists() or path.read_bytes() != content]
    for path, _ in changes:
        print("изменить:", path)
    if args.check:
        print("проверено, файлы не изменены")
        return
    restart = bot_supervisor(root) if args.restart else None
    if not changes:
        if restart:
            restart()
        print("команда /story уже подключена, бот проверен")
        return

    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d-%H%M%S")
    backup = root / (".nyan-story-bot-backup-" + stamp)
    backup.mkdir(parents=True, exist_ok=False)
    for path, _ in changes:
        if path.exists():
            shutil.copy2(path, backup / path.name)
    before = [(path, path.read_bytes() if path.exists() else None) for path, _ in changes]
    try:
        for path, payload in changes:
            atomic_write(path, payload)
        python = root / "venv/bin/python"
        if not python.is_file():
            python = root / ".venv/bin/python"
        executable = str(python) if python.is_file() else sys.executable
        result = subprocess.run(
            [executable, "-m", "py_compile", str(bot), str(addon)],
            capture_output=True, text=True,
        )
        if result.returncode:
            raise RuntimeError(result.stderr[-1200:])
        if restart:
            restart()
    except BaseException:
        for path, payload in reversed(before):
            if payload is None:
                path.unlink(missing_ok=True)
            else:
                atomic_write(path, payload)
        if restart:
            try:
                restart()
            except Exception as error:
                print("ВНИМАНИЕ: восстановленный бот не запустился:", error, file=sys.stderr)
        raise
    print("/story подключена; резервная копия:", backup)
    print("бот перезапущен" if restart else "бот не перезапускался")
    print("приглашения и уведомления не отправлялись")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        raise SystemExit("ОШИБКА: " + str(error)) from error
