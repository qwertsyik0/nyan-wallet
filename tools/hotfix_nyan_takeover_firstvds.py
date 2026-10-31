#!/usr/bin/env python3
"""Apply the tested NYAN TAKEOVER latency hotfix to an existing FirstVDS install.

    sudo python3 hotfix_nyan_takeover_firstvds.py --check
    sudo python3 hotfix_nyan_takeover_firstvds.py --apply

The installer only replaces four TAKEOVER Python modules. It never changes
wallet balances, transactions, group binding, catalog, assets or Telegram posts.
It refuses unknown local versions and restores backups if restart fails.
"""

from __future__ import annotations

import argparse
import ast
import datetime as dt
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path


REVISION = "8fe9d4cade6f4b37b70202c2c134a3e8eb7265bc"
RAW = f"https://raw.githubusercontent.com/qwertsyik0/nyan-wallet/{REVISION}/"
ROOT = Path("/opt/nyan-wallet")
SERVICE = "nyan-wallet"
# Baseline installed by install_nyan_takeover_firstvds.py on October 31.
BASE_BLOBS = {
    "server/nyan_takeover.py": "06d420699be387f1d044f22c8ac39697fa17a1ba",
    "server/nyan_takeover_group.py": "b55f7bf8e0d610c9ae169d2a47f5d65239f851cf",
    "server/nyan_takeover_auction.py": "be984dba0d34050b814a53999db1275f5589436e",
    "server/nyan_takeover_drops.py": "b288b795a86057e0a5f0913d1db05f07a3882f05",
}
TARGET_BLOBS = {
    "server/nyan_takeover.py": "27c613d66a6957801c33601313ea395c45c76b61",
    "server/nyan_takeover_group.py": "bb4a2ffdf99facb7a393b0c7eb3976af5815431a",
    "server/nyan_takeover_auction.py": "40b32947ca785c58c5b660cc512f821f070a2cf0",
    "server/nyan_takeover_drops.py": "d58b6089f4759deb7e1ee54f64eef6d8a870af5a",
}


def blob_sha(data: bytes) -> str:
    return hashlib.sha1(f"blob {len(data)}\0".encode() + data).hexdigest()


def run(*args: str) -> str:
    result = subprocess.run(args, capture_output=True, text=True, timeout=40, check=False)
    if result.returncode:
        raise RuntimeError((result.stderr or result.stdout).strip()[-1000:])
    return result.stdout.strip()


def fetch(path: str) -> bytes:
    req = urllib.request.Request(RAW + path, headers={"User-Agent": "Nyan-Takeover-Hotfix/1"})
    with urllib.request.urlopen(req, timeout=15) as response:
        data = response.read(400_001)
    if not data or len(data) > 400_000 or blob_sha(data) != TARGET_BLOBS[path]:
        raise RuntimeError(f"Некорректный файл обновления: {path}")
    ast.parse(data.decode("utf-8"), filename=path)
    return data


def replace_atomic(path: Path, payload: bytes) -> None:
    fd, temp = tempfile.mkstemp(prefix=".takeover-hotfix-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp, path.stat().st_mode & 0o777)
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def health() -> None:
    last = ""
    for _ in range(12):
        try:
            if run("systemctl", "is-active", SERVICE) != "active":
                last = "Сервис не active"
            else:
                with urllib.request.urlopen("http://127.0.0.1:8000/openapi.json", timeout=3) as response:
                    schema = response.read().decode("utf-8")
                if all(path in schema for path in (
                    '"/api/nyan-takeover/status"',
                    '"/api/nyan-takeover/auction"',
                    '"/api/nyan-takeover/drops"',
                )):
                    try:
                        urllib.request.urlopen("http://127.0.0.1:8000/api/nyan-takeover/status", timeout=3)
                    except urllib.error.HTTPError as exc:
                        if exc.code == 401:
                            return
                    last = "Проверка авторизации не вернула 401"
                else:
                    last = "Маршруты TAKEOVER отсутствуют"
        except Exception as exc:
            last = type(exc).__name__
        time.sleep(2)
    raise RuntimeError("Проверка API не прошла: " + last)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--apply", action="store_true")
    parser.add_argument("--root", default=str(ROOT))
    args = parser.parse_args()
    if os.geteuid() != 0:
        raise RuntimeError("Нужны права root")
    root = Path(args.root).resolve()
    if run("systemctl", "is-active", SERVICE) != "active":
        raise RuntimeError("Работающий сервис не найден; обновление остановлено")

    changes = []
    for rel in BASE_BLOBS:
        target = root / rel
        if not target.is_file() or target.is_symlink():
            raise RuntimeError(f"Не найден обычный файл: {target}")
        old = target.read_bytes()
        old_sha = blob_sha(old)
        if old_sha not in (BASE_BLOBS[rel], TARGET_BLOBS[rel]):
            raise RuntimeError(f"Неизвестная версия {rel}; ничего не изменено")
        new = fetch(rel)
        if old != new:
            changes.append((target, old, new))

    print("Проверено. Файлов к обновлению:", len(changes))
    for target, _, _ in changes:
        print(" ", target.relative_to(root))
    if args.check:
        print("Проверка завершена без изменений.")
        return
    if not changes:
        health()
        print("Обновление уже установлено.")
        return

    backup = root / ".nyan-takeover-hotfix-backups" / dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
    backup.mkdir(parents=True, exist_ok=False)
    written = []
    try:
        for target, old, new in changes:
            copy = backup / target.relative_to(root)
            copy.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target, copy)
            replace_atomic(target, new)
            written.append((target, old))
        run("systemctl", "restart", SERVICE)
        health()
    except BaseException:
        print("Ошибка проверки; восстанавливаю исходные файлы.", file=sys.stderr)
        for target, old in reversed(written):
            replace_atomic(target, old)
        try:
            run("systemctl", "restart", SERVICE)
        except Exception as exc:
            print("Не удалось перезапустить прежний сервис:", exc, file=sys.stderr)
        raise
    print("NYAN TAKEOVER обновлён; API отвечает, балансы не изменялись.")
    print("Резервные копии:", backup)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print("ОШИБКА:", error, file=sys.stderr)
        sys.exit(1)
