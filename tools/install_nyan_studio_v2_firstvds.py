#!/usr/bin/env python3
"""Backed-up, targeted installer for Studio 2.0 + owner finance analytics.

--check never changes production; --apply first dumps and verifies PostgreSQL,
then changes only named Python files and restarts once. Existing DB rows are
never deleted or edited by the installer.
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
MODULES = ("server/interactive_builder.py", "server/finance_analytics.py")
IMPORT_ANCHOR = "from .profile_overview import register_profile_overview\n"
IMPORT_LINE = "from .finance_analytics import register_finance_analytics\n"
REGISTER_ANCHOR = "    register_profile_overview(backend_app.app)\n"
REGISTER_LINE = "    register_finance_analytics(backend_app.app)\n"


def command(*argv, check=True):
    return subprocess.run(argv, text=True, capture_output=True, check=check)


def prepare_init(code):
    for anchor, line in ((IMPORT_ANCHOR, IMPORT_LINE), (REGISTER_ANCHOR, REGISTER_LINE)):
        if line not in code:
            if code.count(anchor) != 1:
                raise RuntimeError("Не найдена точка расширения server/__init__.py. Ничего не изменено")
            code = code.replace(anchor, anchor + line, 1)
    ast.parse(code)
    return code.encode("utf-8")


def download(ref, name):
    url = f"{RAW}/{ref}/{name}"
    req = urllib.request.Request(url, headers={"User-Agent": "NyanStudioV2Install/1.0"})
    with urllib.request.urlopen(req, timeout=25) as reply:
        content = reply.read(200001)
    if len(content) > 200000:
        raise RuntimeError("Неожиданный размер файла " + name)
    ast.parse(content.decode("utf-8"), filename=name)
    return content


def atomic_replace(path, contents, mode):
    fd, candidate = tempfile.mkstemp(dir=path.parent, prefix=".nyan-v2-")
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(contents)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(candidate, mode)
        os.replace(candidate, path)
    finally:
        if os.path.exists(candidate):
            os.unlink(candidate)


def backup_postgres(target):
    # Root owns the file descriptor; the postgres OS user only needs SELECT
    # access. Neither connection strings nor secret credentials are printed.
    old_umask = os.umask(0o077)
    try:
        with target.open("xb") as stream:
            proc = subprocess.run(
                ["runuser", "-u", "postgres", "--", "pg_dump", "-Fc", "-d", "nyan_wallet_db"],
                stdout=stream, stderr=subprocess.PIPE, text=False,
            )
    finally:
        os.umask(old_umask)
    if proc.returncode != 0:
        raise RuntimeError("Не удалось сохранить PostgreSQL: " + proc.stderr.decode("utf-8", "replace")[:180])
    if not target.stat().st_size:
        raise RuntimeError("Резервная копия PostgreSQL пуста")
    command("pg_restore", "--list", str(target))
    print("PostgreSQL: резервная копия проверена, размер:", target.stat().st_size, "байт")


def verify():
    required = {
        "/api/owner/finance-analytics",
        "/api/activities", "/api/activities/{activity_id}",
        "/api/activities/{activity_id}/answer",
    }
    last_error = "API не ответил"
    for _ in range(15):
        try:
            if command("systemctl", "is-active", "nyan-wallet", check=False).stdout.strip() != "active":
                raise RuntimeError("Сервис nyan-wallet не active")
            with urllib.request.urlopen("http://127.0.0.1:8000/api/health", timeout=4) as response:
                if not json.load(response).get("ok"):
                    raise RuntimeError("Health API не готов")
            with urllib.request.urlopen("http://127.0.0.1:8000/openapi.json", timeout=4) as response:
                paths = set(json.load(response)["paths"])
            if not required.issubset(paths):
                raise RuntimeError("Не хватает новых API-маршрутов")
            for route in ("/api/owner/finance-analytics", "/api/activities"):
                try:
                    urllib.request.urlopen("http://127.0.0.1:8000" + route, timeout=4)
                except urllib.error.HTTPError as err:
                    if err.code == 401:
                        continue
                    if err.code == 503:
                        try:
                            content = json.load(err)
                        except (ValueError, OSError):
                            content = {}
                        if content.get("detail") == "maintenance":
                            print("Режим техработ включён, оставлен без изменения")
                            continue
                    raise RuntimeError(f"{route}: HTTP {err.code}") from err
                else:
                    raise RuntimeError("Отсутствует проверка Telegram-авторизации")
            print("OK: сервер работает, маршруты зарегистрированы, публичный доступ закрыт")
            return
        except Exception as exc:
            last_error = str(exc)[:170]
            time.sleep(2)
    raise RuntimeError("Проверка после рестарта не прошла: " + last_error)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--check", action="store_true")
    action.add_argument("--apply", action="store_true")
    parser.add_argument("--rev", required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"[a-f0-9]{40}", args.rev):
        raise RuntimeError("Нужен SHA коммита GitHub из 40 символов")
    if not INIT.is_file():
        raise RuntimeError("Не найден /opt/nyan-wallet/server/__init__.py")
    desired = {ROOT / name: download(args.rev, name) for name in MODULES}
    desired[INIT] = prepare_init(INIT.read_text(encoding="utf-8"))
    changes = {p: content for p, content in desired.items() if not p.exists() or p.read_bytes() != content}
    print("Изменятся файлы:", ", ".join(str(p.relative_to(ROOT)) for p in changes) or "нет")
    if args.check:
        print("OK: сухая проверка. Сервис, база и файлы не изменены")
        return
    if os.geteuid() != 0:
        raise RuntimeError("Для --apply требуются права root")
    if command("systemctl", "is-active", "nyan-wallet", check=False).stdout.strip() != "active":
        raise RuntimeError("Сервис не активен, установка остановлена")
    if not changes:
        verify()
        return
    originals = {p: p.read_bytes() if p.exists() else None for p in changes}
    backup = ROOT / ".nyan-studio-v2-backups" / time.strftime("%Y%m%d-%H%M%S")
    backup.mkdir(parents=True, mode=0o700, exist_ok=False)
    os.chmod(backup, 0o700)
    print("Резервные копии:", backup)
    backup_postgres(backup / "nyan_wallet_db.dump")
    for p, contents in originals.items():
        if contents is not None:
            target = backup / p.relative_to(ROOT)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, target)
    try:
        for p, contents in changes.items():
            atomic_replace(p, contents, p.stat().st_mode & 0o777 if p.exists() else 0o644)
        command("systemctl", "restart", "nyan-wallet")
        verify()
    except BaseException:
        for p, previous in originals.items():
            if previous is None:
                p.unlink(missing_ok=True)
            else:
                atomic_replace(p, previous, 0o644)
        command("systemctl", "restart", "nyan-wallet", check=False)
        print("Ошибка: исходные файлы восстановлены, сервис перезапущен", file=sys.stderr)
        raise
    print("УСТАНОВКА УСПЕШНА. Старые балансы и заявки не изменены")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print("ОШИБКА:", error, file=sys.stderr)
        sys.exit(1)
