#!/usr/bin/env python3
"""Install only the Nyan lottery backend after --check and a verified pg_dump.

The existing wallet, giveaway tables, transactions and balances are untouched.
On failure, restore the original Python files, restart, retain the DB backup.
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
MODULE = ROOT / "server/lottery.py"
RAW = "https://raw.githubusercontent.com/qwertsyik0/nyan-wallet"
IMPORT_ANCHOR = "from .giveaways import register_giveaways\n"
IMPORT_LINE = "from .lottery import register_lottery\n"
REGISTER_ANCHOR = "    register_giveaways(backend_app.app)\n"
REGISTER_LINE = "    register_lottery(backend_app.app)\n"


def command(*argv, check=True):
    return subprocess.run(argv, text=True, capture_output=True, check=check)


def prepare_init(code):
    for anchor, line in ((IMPORT_ANCHOR, IMPORT_LINE), (REGISTER_ANCHOR, REGISTER_LINE)):
        if line not in code:
            if code.count(anchor) != 1:
                raise RuntimeError("Нет точки подключения лотереи в server/__init__.py. Остановлено")
            code = code.replace(anchor, anchor + line, 1)
    ast.parse(code)
    return code.encode("utf-8")


def download(rev):
    request = urllib.request.Request(f"{RAW}/{rev}/server/lottery.py",
                                     headers={"User-Agent": "NyanLotteryInstaller/1.0"})
    with urllib.request.urlopen(request, timeout=25) as response:
        content = response.read(130001)
    if len(content) > 130000:
        raise RuntimeError("Размер серверного модуля превышает лимит")
    ast.parse(content.decode("utf-8"), filename="lottery.py")
    return content


def atomic_replace(path, data, mode):
    fd, candidate = tempfile.mkstemp(dir=path.parent, prefix=".nyan-lottery-")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(candidate, mode)
        os.replace(candidate, path)
    finally:
        if os.path.exists(candidate):
            os.unlink(candidate)


def postgres_dump(target):
    old = os.umask(0o077)
    try:
        with target.open("xb") as output:
            result = subprocess.run(["runuser", "-u", "postgres", "--", "pg_dump", "-Fc",
                                     "-d", "nyan_wallet_db"], stdout=output, stderr=subprocess.PIPE)
    finally:
        os.umask(old)
    if result.returncode:
        raise RuntimeError("PostgreSQL: " + result.stderr.decode("utf-8", "replace")[:170])
    if not target.stat().st_size:
        raise RuntimeError("Резервная копия PostgreSQL пуста")
    command("pg_restore", "--list", str(target))
    print("PostgreSQL: дамп проверен, размер", target.stat().st_size, "байт")


def verify():
    expected = {
        "/api/lottery", "/api/lottery/{round_id}", "/api/lottery/{round_id}/purchase",
        "/api/owner/lottery/rounds", "/api/owner/lottery/rounds/{round_id}/assign",
    }
    last_error = "API не ответил"
    for _ in range(14):
        try:
            if command("systemctl", "is-active", "nyan-wallet", check=False).stdout.strip() != "active":
                raise RuntimeError("Сервис nyan-wallet не активен")
            with urllib.request.urlopen("http://127.0.0.1:8000/api/health", timeout=4) as response:
                if not json.load(response).get("ok"):
                    raise RuntimeError("Не прошла проверка /api/health")
            with urllib.request.urlopen("http://127.0.0.1:8000/openapi.json", timeout=4) as response:
                paths = set(json.load(response)["paths"])
            if not expected.issubset(paths):
                raise RuntimeError("Маршруты лотереи не подключены")
            try:
                urllib.request.urlopen("http://127.0.0.1:8000/api/lottery", timeout=4)
            except urllib.error.HTTPError as err:
                if err.code == 401:
                    pass
                elif err.code == 503:
                    try:
                        body = json.load(err)
                    except (ValueError, OSError):
                        body = {}
                    if body.get("detail") != "maintenance":
                        raise RuntimeError("Непредвиденный ответ HTTP 503") from err
                    print("Сейчас включены техработы, режим не изменялся")
                else:
                    raise RuntimeError(f"Проверка авторизации: HTTP {err.code}") from err
            else:
                raise RuntimeError("Публичный запрос прошёл без Telegram-авторизации")
            result = command("runuser", "-u", "postgres", "--", "psql", "-d", "nyan_wallet_db",
                             "-At", "-c", "SELECT to_regclass('public.lottery_rounds');")
            if result.stdout.strip() != "lottery_rounds":
                raise RuntimeError("Таблицы лотереи не созданы")
            print("OK: сервис работает, маршруты закрыты авторизацией, таблицы лотереи доступны")
            return
        except Exception as exc:
            last_error = str(exc)[:180]
            time.sleep(2)
    raise RuntimeError("После установки не прошла проверка: " + last_error)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--check", action="store_true")
    action.add_argument("--apply", action="store_true")
    parser.add_argument("--rev", required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"[0-9a-f]{40}", args.rev):
        raise RuntimeError("Нужен полный SHA коммита GitHub, 40 символов")
    if not INIT.is_file():
        raise RuntimeError("Не найден сервер /opt/nyan-wallet")
    desired = {MODULE: download(args.rev), INIT: prepare_init(INIT.read_text(encoding="utf-8"))}
    changes = {p: data for p, data in desired.items() if not p.is_file() or p.read_bytes() != data}
    print("Будут изменены:", ", ".join(str(path.relative_to(ROOT)) for path in changes) or "ничего")
    if args.check:
        print("OK: сухая проверка, сервис и база не изменены")
        return
    if os.geteuid() != 0:
        raise RuntimeError("Для --apply нужны права root")
    if command("systemctl", "is-active", "nyan-wallet", check=False).stdout.strip() != "active":
        raise RuntimeError("Сервис не работает, остановлено")
    if not changes:
        verify()
        return
    originals = {p: p.read_bytes() if p.is_file() else None for p in changes}
    backup = ROOT / ".nyan-lottery-backups" / time.strftime("%Y%m%d-%H%M%S")
    backup.mkdir(parents=True, mode=0o700, exist_ok=False)
    os.chmod(backup, 0o700)
    print("Резервная копия:", backup)
    postgres_dump(backup / "nyan_wallet_db.dump")
    for path, previous in originals.items():
        if previous is not None:
            saved = backup / path.relative_to(ROOT)
            saved.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, saved)
    try:
        for path, content in changes.items():
            atomic_replace(path, content, path.stat().st_mode & 0o777 if path.exists() else 0o644)
        command("systemctl", "restart", "nyan-wallet")
        verify()
    except BaseException:
        for path, previous in originals.items():
            if previous is None:
                path.unlink(missing_ok=True)
            else:
                atomic_replace(path, previous, 0o644)
        command("systemctl", "restart", "nyan-wallet", check=False)
        print("Исходные файлы восстановлены. Дамп БД сохранён:", backup, file=sys.stderr)
        raise
    print("УСТАНОВКА УСПЕШНА. Старые балансы, заявки и розыгрыши не изменены")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print("ОШИБКА:", error, file=sys.stderr)
        sys.exit(1)
