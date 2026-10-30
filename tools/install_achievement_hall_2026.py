#!/usr/bin/env python3
"""Install the unified achievement badge selector on FirstVDS without changing data.

Run --check first, then --apply. If the live file differs from the known
GitHub baseline, stop instead of overwriting somebody's server edits.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path


TARGET = Path("/opt/nyan-wallet/server/achievements.py")
SERVICE = "nyan-wallet"
BASE = "36c6bcb58bda08dc86bdabd30a4dd037ffd49430"
RAW = "https://raw.githubusercontent.com/qwertsyik0/nyan-wallet"


def fetch(revision: str) -> bytes:
    url = f"{RAW}/{revision}/server/achievements.py"
    with urllib.request.urlopen(url, timeout=25) as response:
        if response.status != 200:
            raise RuntimeError(f"Не удалось загрузить achievements.py: HTTP {response.status}")
        content = response.read(512 * 1024 + 1)
    if not content or len(content) > 512 * 1024:
        raise RuntimeError("Неправильный размер серверного файла")
    return content


def command(*args: str) -> str:
    result = subprocess.run(args, capture_output=True, text=True, check=False)
    if result.returncode:
        raise RuntimeError(f"Ошибка {args[0]}: {(result.stderr or result.stdout)[-800:]}")
    return result.stdout.strip()


def publish(content: bytes, *, mode: int) -> None:
    fd, temp_path = tempfile.mkstemp(prefix=".nyan-achievements-", dir=TARGET.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp_path, mode)
        os.replace(temp_path, TARGET)
    finally:
        if os.path.exists(temp_path):
            os.unlink(temp_path)


def health() -> None:
    error = "API не отвечает"
    for _ in range(15):
        try:
            with urllib.request.urlopen("http://127.0.0.1:8000/openapi.json", timeout=3) as response:
                data = response.read()
                if response.status == 200 and all(
                    path in data for path in (b'"/api/achievements"', b'"/api/achievements/badge"')
                ):
                    return
                error = "Маршруты достижений отсутствуют"
        except Exception as exc:
            error = str(exc)
        time.sleep(1.5)
    raise RuntimeError("После перезапуска не пройдена проверка: " + error)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--revision", required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if not re.fullmatch(r"[0-9a-f]{40}", args.revision):
        raise RuntimeError("Укажи полный SHA нового коммита GitHub")
    if os.geteuid() != 0:
        raise RuntimeError("Открой Termius под root")
    if TARGET.is_symlink() or not TARGET.is_file():
        raise RuntimeError("Не найден обычный /opt/nyan-wallet/server/achievements.py")
    if command("systemctl", "is-active", SERVICE) != "active":
        raise RuntimeError("Сервис Nyan Wallet сейчас неактивен")

    previous = fetch(BASE)
    updated = fetch(args.revision)
    if b"def _owned_event_badges(" not in updated or b'"special_badges": special' not in updated:
        raise RuntimeError("В новом файле не найдена система выбора наград")
    current = TARGET.read_bytes()
    if current not in (previous, updated):
        digest = hashlib.sha256(current).hexdigest()
        raise RuntimeError(
            "Серверный achievements.py отличается от проверенной версии. "
            f"Сначала нужна ручная проверка (SHA256: {digest}). Ничего не изменено."
        )
    with tempfile.TemporaryDirectory(prefix="nyan-achievements-compile-") as folder:
        candidate = Path(folder) / "achievements.py"
        candidate.write_bytes(updated)
        command(sys.executable, "-m", "py_compile", str(candidate))

    print("Зал достижений:", "уже установлен" if current == updated else "готов к обновлению")
    print("База данных, балансы, награды и старые значки не изменяются")
    if args.check:
        print("Проверка ОК. Сервер не изменён.")
        return
    if current == updated:
        health()
        print("Уже установлено. API работает.")
        return

    backup = TARGET.with_name("achievements.py.before-hall-" + datetime.datetime.now().strftime("%Y%m%d-%H%M%S"))
    if backup.exists():
        raise RuntimeError("Резервная копия уже существует: " + str(backup))
    shutil.copy2(TARGET, backup)
    print("Резервная копия:", backup)
    try:
        publish(updated, mode=os.stat(TARGET).st_mode & 0o777)
        command("systemctl", "restart", SERVICE)
        health()
    except Exception:
        shutil.copy2(backup, TARGET)
        try:
            command("systemctl", "restart", SERVICE)
        except Exception as exc:
            print("Не удалось восстановить службу:", exc, file=sys.stderr)
        print("Изменения отменены, резервная копия сохранена", file=sys.stderr)
        raise
    print("Готово. Значки теперь можно надевать и снимать вручную.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("ОШИБКА:", exc, file=sys.stderr)
        sys.exit(1)
