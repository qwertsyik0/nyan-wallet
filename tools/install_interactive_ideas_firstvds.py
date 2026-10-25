#!/usr/bin/env python3
"""Safely enable the independent interactive-ideas page API on FirstVDS.

This installer never calls `git pull` because the production server contains
valuable custom quote and election modules. --check makes no changes. --apply
updates only two Python files, restarts the FastAPI service once, verifies its
routes and rolls back the two files if verification fails.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path


ROOT = Path("/opt/nyan-wallet")
INIT = ROOT / "server/__init__.py"
MODULE = ROOT / "server/interactive_ideas.py"
RAW = "https://raw.githubusercontent.com/qwertsyik0/nyan-wallet"
IMPORT_ANCHOR = "from .suggestions import register_suggestions\n"
IMPORT_LINE = "from .interactive_ideas import register_interactive_ideas\n"
REGISTER_ANCHOR = "    register_suggestions(backend_app.app)\n"
REGISTER_LINE = "    register_interactive_ideas(backend_app.app)\n"


def run(*parts: str, check: bool = True):
    return subprocess.run(parts, capture_output=True, text=True, check=check)


def patch_init(content: str) -> str:
    if IMPORT_LINE not in content:
        if content.count(IMPORT_ANCHOR) != 1:
            raise RuntimeError("Точка импорта не найдена, server/__init__.py не тронут")
        content = content.replace(IMPORT_ANCHOR, IMPORT_ANCHOR + IMPORT_LINE, 1)
    if REGISTER_LINE not in content:
        if content.count(REGISTER_ANCHOR) != 1:
            raise RuntimeError("Точка регистрации не найдена, server/__init__.py не тронут")
        content = content.replace(REGISTER_ANCHOR, REGISTER_ANCHOR + REGISTER_LINE, 1)
    ast.parse(content, filename="server/__init__.py")
    return content


def download(ref: str) -> bytes:
    request = urllib.request.Request(
        f"{RAW}/{ref}/server/interactive_ideas.py",
        headers={"User-Agent": "NyanWalletInteractiveIdeasSafeInstaller/1.0"},
    )
    with urllib.request.urlopen(request, timeout=25) as response:
        data = response.read(100001)
    if len(data) > 100000:
        raise RuntimeError("Файл модуля неожиданно большой")
    ast.parse(data.decode("utf-8"), filename="server/interactive_ideas.py")
    return data


def atomic_write(target: Path, content: bytes, mode: int) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=".nyan-ideas-", dir=target.parent)
    try:
        with os.fdopen(fd, "wb") as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        os.chmod(temp, mode)
        os.replace(temp, target)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def wait_ready():
    last_error = "сервис не отвечает"
    for _ in range(15):
        if run("systemctl", "is-active", "nyan-wallet", check=False).stdout.strip() != "active":
            last_error = "systemd ещё не active"
            time.sleep(2)
            continue
        try:
            with urllib.request.urlopen("http://127.0.0.1:8000/api/health", timeout=4) as response:
                health = json.load(response)
            with urllib.request.urlopen("http://127.0.0.1:8000/openapi.json", timeout=4) as response:
                paths = json.load(response)["paths"]
            required = {
                "/api/interactive-ideas/auth/widget",
                "/api/interactive-ideas/me",
                "/api/interactive-ideas",
                "/api/interactive-ideas/moderation",
                "/api/interactive-ideas/{idea_id}/review",
            }
            if not health.get("ok") or not required.issubset(paths):
                last_error = "не все маршруты зарегистрированы"
                time.sleep(2)
                continue
            try:
                urllib.request.urlopen("http://127.0.0.1:8000/api/interactive-ideas/me", timeout=3)
            except urllib.error.HTTPError as exc:
                if exc.code != 401:
                    raise RuntimeError("Маршрут не защищён авторизацией") from exc
            else:
                raise RuntimeError("Маршрут не требует Telegram-подпись")
            print("OK: API отвечает, модерация зарегистрирована, авторизация обязательна")
            return
        except Exception as exc:
            last_error = type(exc).__name__ + ": " + str(exc)[:100]
            time.sleep(2)
    raise RuntimeError("Сервис не прошёл проверку: " + last_error)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--check", action="store_true")
    action.add_argument("--apply", action="store_true")
    parser.add_argument("--rev", required=True, help="Точный GitHub commit SHA (40 hex)")
    args = parser.parse_args()
    if not re.fullmatch(r"[0-9a-f]{40}", args.rev):
        raise RuntimeError("Нужен полный SHA коммита")
    if not INIT.is_file() or not (ROOT / "server/backend_app.py").is_file():
        raise RuntimeError("Проект Nyan Wallet не найден в /opt/nyan-wallet")
    files = {
        MODULE: download(args.rev),
        INIT: patch_init(INIT.read_text(encoding="utf-8")).encode("utf-8"),
    }
    changed = [path for path, contents in files.items()
               if not path.exists() or path.read_bytes() != contents]
    print("Изменятся только:", ", ".join(str(p.relative_to(ROOT)) for p in changed) or "ничего")
    print("Все прежние импорты и регистрации в server/__init__.py сохраняются")
    if args.check:
        print("OK: сухая проверка, файлы, сервис и баланс не изменены")
        return
    if os.geteuid() != 0:
        raise RuntimeError("--apply запускается от root")
    if run("systemctl", "is-active", "nyan-wallet", check=False).stdout.strip() != "active":
        raise RuntimeError("Сервис сейчас не active; установка остановлена")
    original = {path: path.read_bytes() if path.exists() else None for path in changed}
    backup = ROOT / ".nyan-interactive-ideas-backups" / time.strftime("%Y%m%d-%H%M%S")
    backup.mkdir(parents=True, mode=0o700, exist_ok=False)
    os.chmod(backup, 0o700)
    for path, contents in original.items():
        if contents is None:
            continue
        destination = backup / path.relative_to(ROOT)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, destination)
    print("Резервные копии:", backup)
    try:
        for path in changed:
            atomic_write(path, files[path], (path.stat().st_mode & 0o777) if path.exists() else 0o644)
        run("systemctl", "restart", "nyan-wallet")
        wait_ready()
    except BaseException:
        for path, contents in original.items():
            if contents is None:
                path.unlink(missing_ok=True)
            else:
                atomic_write(path, contents, 0o644)
        run("systemctl", "restart", "nyan-wallet", check=False)
        print("ОШИБКА: прежние файлы восстановлены, запущен автоматический откат", file=sys.stderr)
        raise
    print("УСТАНОВКА УСПЕШНА: сохранены все балансы и прежние интерактивы")
    print("Новая таблица создана отдельно: interactive_idea_submissions")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print("ОШИБКА:", error, file=sys.stderr)
        sys.exit(1)
