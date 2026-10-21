#!/usr/bin/env python3
"""Install Nyan Wallet quote reflection on FirstVDS without affecting elections or balances."""
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
import urllib.request
from pathlib import Path

REPO = "https://raw.githubusercontent.com/qwertsyik0/nyan-wallet"
IMPORT_ANCHOR = "from . import backend_app as backend_app\n"
IMPORT_LINE = "from .quote_reflection import register_quote_reflection\n"
REGISTER_ANCHOR = "    register_maintenance(backend_app.app)\n"
REGISTER_LINE = "    register_quote_reflection(backend_app.app)\n"
ROUTES = {"/api/quote-reflection/status", "/api/quote-reflection/submit"}


def run(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, text=True, check=check)


def root_path() -> Path:
    candidates = [Path("/opt/nyan-wallet"), Path("/root/nyan-wallet"),
                  Path("/srv/nyan-wallet")]
    for root in candidates:
        if (root / "server/__init__.py").is_file() and (root / "server/backend_app.py").is_file():
            return root
    raise RuntimeError("Не найден FastAPI Nyan Wallet (проверь /opt/nyan-wallet)")


def patch_initializer(before: str) -> str:
    after = before
    if IMPORT_LINE not in after:
        if after.count(IMPORT_ANCHOR) != 1:
            raise RuntimeError("Не удалось безопасно добавить импорт quote_reflection")
        after = after.replace(IMPORT_ANCHOR, IMPORT_ANCHOR + IMPORT_LINE, 1)
    if REGISTER_LINE not in after:
        if after.count(REGISTER_ANCHOR) != 1:
            raise RuntimeError("Не удалось безопасно зарегистрировать маршрут quote_reflection")
        after = after.replace(REGISTER_ANCHOR, REGISTER_ANCHOR + REGISTER_LINE, 1)
    ast.parse(after, filename="server/__init__.py")
    return after


def download(ref: str) -> str:
    if not re.fullmatch(r"[0-9a-f]{40}", ref):
        raise ValueError("--rev должен быть SHA коммита из 40 символов")
    url = f"{REPO}/{ref}/server/quote_reflection.py"
    req = urllib.request.Request(url, headers={"User-Agent":"NyanQuoteDeploy/1.0"})
    with urllib.request.urlopen(req, timeout=30) as response:
        raw = response.read(120001)
    if len(raw) > 120000:
        raise ValueError("Модуль слишком большой")
    source = raw.decode("utf-8")
    ast.parse(source, filename="server/quote_reflection.py")
    if '"/api/quote-reflection/submit"' not in source or "register_quote_reflection" not in source:
        raise ValueError("Нужные маршруты в модуле отсутствуют")
    return source


def atomic_write(path: Path, data: bytes) -> None:
    fd, temp = tempfile.mkstemp(prefix=".nyan-quote-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temp, (path.stat().st_mode & 0o777) if path.exists() else 0o644)
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def wait_ready() -> None:
    last_error = ""
    for _ in range(18):
        if run("systemctl", "is-active", "nyan-wallet", check=False).stdout.strip() != "active":
            last_error = "Сервис не active"
            time.sleep(2)
            continue
        try:
            with urllib.request.urlopen("http://127.0.0.1:8000/api/health", timeout=3) as response:
                status = json.load(response)
            with urllib.request.urlopen("http://127.0.0.1:8000/openapi.json", timeout=3) as response:
                paths = set(json.load(response).get("paths", {}))
            if status.get("ok") is True and ROUTES <= paths:
                print("OK: сервис работает, оба маршрута доступны")
                return
            last_error = "Маршруты ещё не появились"
        except Exception as exc:
            last_error = str(exc)
        time.sleep(2)
    raise RuntimeError("Проверка сервиса не пройдена: " + last_error)


def main() -> None:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--apply", action="store_true")
    parser.add_argument("--rev", required=True, help="Зафиксированный коммит GitHub")
    args = parser.parse_args()

    root = root_path()
    init_file = root / "server/__init__.py"
    code_file = root / "server/quote_reflection.py"
    old_init = init_file.read_bytes()
    old_code = code_file.read_bytes() if code_file.exists() else None
    new_init = patch_initializer(old_init.decode("utf-8")).encode("utf-8")
    new_code = download(args.rev).encode("utf-8")
    changed = (old_init != new_init) or (old_code != new_code)
    print("Nyan Wallet:", root)
    print("Изменения:", "нужна установка" if changed else "модуль уже установлен")

    if args.check:
        print("ПРОВЕРКА: файлы, балансы и сервис не изменены")
        return
    if os.geteuid() != 0:
        raise RuntimeError("Запусти от root на FirstVDS")
    if run("systemctl", "is-active", "nyan-wallet", check=False).stdout.strip() != "active":
        raise RuntimeError("Сервис сейчас не запущен. Установка отменена.")
    if not changed:
        wait_ready()
        return

    backup = root / ".nyan-quote-backups" / time.strftime("%Y%m%d-%H%M%S")
    backup.mkdir(parents=True, exist_ok=False)
    shutil.copy2(init_file, backup / "__init__.py")
    if code_file.exists():
        shutil.copy2(code_file, backup / "quote_reflection.py")
    print("Резервная копия:", backup)

    try:
        atomic_write(code_file, new_code)
        atomic_write(init_file, new_init)
        run("systemctl", "restart", "nyan-wallet")
        wait_ready()
    except BaseException:
        atomic_write(init_file, old_init)
        if old_code is None:
            code_file.unlink(missing_ok=True)
        else:
            atomic_write(code_file, old_code)
        run("systemctl", "restart", "nyan-wallet", check=False)
        print("Откат выполнен; проверь состояние сервиса", file=sys.stderr)
        raise

    print("УСТАНОВКА ЗАВЕРШЕНА. Награды пока никому не начислялись.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("ОШИБКА:", exc, file=sys.stderr)
        sys.exit(1)
