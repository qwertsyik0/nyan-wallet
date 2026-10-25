#!/usr/bin/env python3
"""Targeted and reversible FirstVDS installer for Nyan Studio + profile.

Preserves existing production server additions; never runs git pull.
--check is read-only; --apply backs up modified source files, restarts once,
checks routes/auth, and restores source files automatically on failure.
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
RAW = "https://raw.githubusercontent.com/qwertsyik0/nyan-wallet"
MODULES = ("server/interactive_builder.py", "server/profile_overview.py")
IMPORT_ANCHOR = "from .interactive_ideas import register_interactive_ideas\n"
IMPORT_LINES = (
    "from .interactive_builder import register_interactive_builder\n"
    "from .profile_overview import register_profile_overview\n"
)
REGISTER_ANCHOR = "    register_interactive_ideas(backend_app.app)\n"
REGISTER_LINES = (
    "    register_interactive_builder(backend_app.app)\n"
    "    register_profile_overview(backend_app.app)\n"
)


def command(*parts, check=True):
    return subprocess.run(parts, capture_output=True, text=True, check=check)


def patch_init(code):
    if IMPORT_LINES not in code:
        if code.count(IMPORT_ANCHOR) != 1:
            raise RuntimeError("Точка импорта interactive_ideas не найдена. Файлы не изменены.")
        code = code.replace(IMPORT_ANCHOR, IMPORT_ANCHOR + IMPORT_LINES, 1)
    if REGISTER_LINES not in code:
        if code.count(REGISTER_ANCHOR) != 1:
            raise RuntimeError("Точка регистрации interactive_ideas не найдена. Файлы не изменены.")
        code = code.replace(REGISTER_ANCHOR, REGISTER_ANCHOR + REGISTER_LINES, 1)
    ast.parse(code, filename="server/__init__.py")
    return code.encode("utf-8")


def download(ref, filename):
    request = urllib.request.Request(
        f"{RAW}/{ref}/{filename}", headers={"User-Agent": "NyanStudioSafeInstall/1.0"},
    )
    with urllib.request.urlopen(request, timeout=25) as response:
        data = response.read(150001)
    if len(data) > 150000:
        raise RuntimeError(f"Файл {filename} неожиданно большой")
    ast.parse(data.decode("utf-8"), filename=filename)
    return data


def write_atomic(target, value, mode):
    fd, candidate = tempfile.mkstemp(prefix=".nyan-studio-", dir=target.parent)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(value)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(candidate, mode)
        os.replace(candidate, target)
    finally:
        if os.path.exists(candidate):
            os.unlink(candidate)


def verify():
    last_error = "API не ответил"
    paths_expected = {
        "/api/profile/overview",
        "/api/activities",
        "/api/activities/{activity_id}",
        "/api/activities/{activity_id}/answer",
        "/api/owner/activities",
        "/api/owner/activities/{activity_id}/edit",
        "/api/owner/activities/{activity_id}/status",
        "/api/owner/activities/{activity_id}/answers",
        "/api/owner/activities/{activity_id}/answers/{answer_id}/review",
    }
    for _ in range(15):
        try:
            if command("systemctl", "is-active", "nyan-wallet", check=False).stdout.strip() != "active":
                raise RuntimeError("Сервис не active")
            with urllib.request.urlopen("http://127.0.0.1:8000/api/health", timeout=4) as response:
                if not json.load(response).get("ok"):
                    raise RuntimeError("Health API не готов")
            with urllib.request.urlopen("http://127.0.0.1:8000/openapi.json", timeout=4) as response:
                paths = set(json.load(response)["paths"])
            if not paths_expected.issubset(paths):
                raise RuntimeError("Не все новые API зарегистрированы")
            under_maintenance = False
            for path in ("/api/profile/overview", "/api/activities", "/api/owner/activities"):
                try:
                    urllib.request.urlopen(f"http://127.0.0.1:8000{path}", timeout=3)
                except urllib.error.HTTPError as error:
                    if error.code == 401:
                        continue
                    # The existing maintenance middleware intentionally
                    # blocks user routes with HTTP 503 before they reach auth.
                    # Keep maintenance enabled; route presence was checked
                    # through OpenAPI, and auth is also covered by API tests.
                    if error.code == 503:
                        try:
                            payload = json.load(error)
                        except (ValueError, OSError):
                            payload = {}
                        if payload.get("detail") == "maintenance":
                            under_maintenance = True
                            continue
                    raise RuntimeError(f"{path}: неожиданный HTTP {error.code}") from error
                else:
                    raise RuntimeError(f"{path}: авторизация не требуется")
            if under_maintenance:
                print("OK: новые маршруты зарегистрированы. Режим техработ сохранён.")
                print("Защиту живого API повторно проверим после снятия техработ.")
            else:
                print("OK: обе функции доступны, подпись Telegram обязательна")
            return
        except Exception as error:
            last_error = str(error)[:150]
            time.sleep(2)
    raise RuntimeError("После запуска API не прошёл проверку: " + last_error)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--check", action="store_true")
    group.add_argument("--apply", action="store_true")
    parser.add_argument("--rev", required=True, help="Полный SHA коммита GitHub")
    args = parser.parse_args()
    if not re.fullmatch("[0-9a-f]{40}", args.rev):
        raise RuntimeError("Нужен полный SHA коммита (40 символов)")
    if not INIT.is_file() or not (ROOT / "server/backend_app.py").is_file():
        raise RuntimeError("Не найден /opt/nyan-wallet")
    desired = {ROOT / name: download(args.rev, name) for name in MODULES}
    desired[INIT] = patch_init(INIT.read_text(encoding="utf-8"))
    changes = {path: value for path, value in desired.items()
               if not path.exists() or path.read_bytes() != value}
    print("Проверены модули:", ", ".join(MODULES))
    print("Изменятся только:", ", ".join(str(path.relative_to(ROOT)) for path in changes) or "ничего")
    print("Все другие локальные изменения на сервере сохраняются")
    if args.check:
        print("OK: сухая проверка. Сервис, база и файлы не изменены.")
        return
    if os.geteuid() != 0:
        raise RuntimeError("Для --apply нужен root")
    if command("systemctl", "is-active", "nyan-wallet", check=False).stdout.strip() != "active":
        raise RuntimeError("Сервис не active. Установка остановлена.")
    if not changes:
        verify()
        return
    originals = {path: path.read_bytes() if path.exists() else None for path in changes}
    backup = ROOT / ".nyan-studio-backups" / time.strftime("%Y%m%d-%H%M%S")
    backup.mkdir(mode=0o700, parents=True, exist_ok=False)
    os.chmod(backup, 0o700)
    for path, value in originals.items():
        if value is not None:
            dest = backup / path.relative_to(ROOT)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, dest)
    print("Резервные копии:", backup)
    try:
        for path, value in changes.items():
            write_atomic(path, value, (path.stat().st_mode & 0o777) if path.exists() else 0o644)
        command("systemctl", "restart", "nyan-wallet")
        verify()
    except BaseException:
        for path, original in originals.items():
            if original is None:
                path.unlink(missing_ok=True)
            else:
                write_atomic(path, original, 0o644)
        command("systemctl", "restart", "nyan-wallet", check=False)
        print("ОШИБКА: восстановлены исходные файлы и выполнен откат", file=sys.stderr)
        raise
    print("УСТАНОВКА ГОТОВА: существующие балансы и заявки не изменялись")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print("ОШИБКА:", error, file=sys.stderr)
        sys.exit(1)
