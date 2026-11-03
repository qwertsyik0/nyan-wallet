#!/usr/bin/env python3
"""Update only NYAN MAFIA API for owner /mafia command, with rollback.

  python3 /tmp/install_nyan_mafia_command_firstvds.py --check
  python3 /tmp/install_nyan_mafia_command_firstvds.py --apply

Never starts a game or sends Telegram messages.
"""

from __future__ import annotations

import argparse
import ast
import datetime
import os
import shutil
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path("/opt/nyan-wallet")
PATH = ROOT / "server/nyan_mafia.py"
SERVICE = "nyan-wallet"
RAW = ("https://raw.githubusercontent.com/qwertsyik0/nyan-wallet/"
       "4e04979a5cc3e1420da44613eac9045955dcb691/server/nyan_mafia.py")
NEEDED = (
    '"/api/owner/nyan-mafia/open"',
    '"/api/internal/nyan-mafia/open"',
    "NYAN_MAFIA_GROUP_ID",
    "NYAN_MAFIA_INVITE_URL",
)

def command(*args: str) -> str:
    p = subprocess.run(args, text=True, capture_output=True, timeout=50, check=False)
    if p.returncode:
        raise RuntimeError((p.stderr or p.stdout or "ошибка команды")[-1200:])
    return p.stdout.strip()

def fetch() -> bytes:
    with urllib.request.urlopen(
        urllib.request.Request(RAW, headers={"User-Agent": "NYAN-MAFIA-Safe-Installer"}),
        timeout=20,
    ) as response:
        data = response.read(160001)
    if not 5000 <= len(data) <= 160000:
        raise RuntimeError("неожиданный размер серверного модуля")
    body = data.decode("utf-8")
    ast.parse(body, filename="server/nyan_mafia.py")
    if any(item not in body for item in NEEDED):
        raise RuntimeError("загружен неверный модуль")
    return data

def atomic_write(path: Path, data: bytes) -> None:
    fd, tmp = tempfile.mkstemp(prefix=".nyan-mafia-command-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, path.stat().st_mode & 0o777)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)

def health() -> None:
    last = "нет ответа"
    for _ in range(14):
        try:
            if command("systemctl", "is-active", SERVICE) != "active":
                raise RuntimeError("служба запускается")
            with urllib.request.urlopen("http://127.0.0.1:8000/openapi.json", timeout=4) as r:
                schema = r.read(200000).decode()
            if '"/api/internal/nyan-mafia/open"' not in schema:
                raise RuntimeError("новый маршрут не появился")
            try:
                urllib.request.urlopen(
                    urllib.request.Request(
                        "http://127.0.0.1:8000/api/internal/nyan-mafia/open",
                        data=b"{}", method="POST",
                    ), timeout=4,
                )
            except urllib.error.HTTPError as error:
                if error.code == 401:
                    return
                raise RuntimeError("неверный код авторизации " + str(error.code))
            raise RuntimeError("маршрут открыт без авторизации!")
        except Exception as e:
            last = str(e)
        time.sleep(2)
    raise RuntimeError("проверка API не прошла: " + last)

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--check", action="store_true")
    group.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    if not PATH.is_file() or PATH.is_symlink():
        raise RuntimeError("не найден действующий файл серверного модуля")
    if command("systemctl", "is-active", SERVICE) != "active":
        raise RuntimeError("nyan-wallet не запущен")
    updated = fetch()
    previous = PATH.read_bytes()
    ast.parse(previous.decode("utf-8"), filename=str(PATH))
    if b"def register_nyan_mafia" not in previous:
        raise RuntimeError("на сервере установлен другой модуль мафии")
    if args.check:
        print("NYAN MAFIA: проверено, обновить только server/nyan_mafia.py")
        print("изменения:", "нет" if previous == updated else "есть")
        print("регистрация не открыта, сообщения не отправлены")
        return
    if os.geteuid() != 0:
        raise RuntimeError("для установки нужны права root")
    if previous == updated:
        health()
        print("модуль уже обновлён и защищён")
        return
    backup = ROOT / ".nyan-mafia-backups" / datetime.datetime.now(
        datetime.timezone.utc
    ).strftime("%Y%m%d-%H%M%S-%f")
    backup.mkdir(parents=True, exist_ok=False)
    shutil.copy2(PATH, backup / "nyan_mafia.py")
    try:
        atomic_write(PATH, updated)
        command("systemctl", "restart", SERVICE)
        health()
    except Exception:
        atomic_write(PATH, previous)
        command("systemctl", "restart", SERVICE)
        raise
    print("NYAN MAFIA: безопасное обновление установлено")
    print("резервная копия:", backup)
    print("регистрация не открыта, сообщения не отправлены")

if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        raise SystemExit("ОШИБКА: " + str(error)) from error
