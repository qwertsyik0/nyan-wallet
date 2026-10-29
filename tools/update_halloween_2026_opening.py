#!/usr/bin/env python3
"""Move the installed Halloween event opening to October 29, 17:00 MSK.

This changes two exact lines in the already-installed event module, keeping any
other production customizations. No user balances or database rows are changed.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from datetime import datetime
from pathlib import Path


MODULE = Path("/opt/nyan-wallet/server/halloween_2026.py")
SERVICE = "nyan-wallet"
CHANGES = (
    (
        b"START_AT = datetime(2026, 10, 30, 21, 0, tzinfo=UTC)  # Oct 31, 00:00 MSK",
        b"START_AT = datetime(2026, 10, 29, 14, 0, tzinfo=UTC)  # Oct 29, 17:00 MSK",
    ),
    (
        "Событие доступно только 31 октября по Москве".encode(),
        "Событие доступно с 29 октября, 17:00, до конца 31 октября по Москве".encode(),
    ),
)


def run(*cmd: str) -> str:
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode:
        raise RuntimeError(f"Команда {cmd[0]}: {(result.stderr or result.stdout)[-1200:]}")
    return result.stdout.strip()


def rewrite(source: bytes) -> tuple[bytes, bool]:
    changed = False
    for old, new in CHANGES:
        old_found = source.count(old)
        new_found = source.count(new)
        if old_found + new_found != 1:
            raise RuntimeError("Серверный модуль отличается от ожидаемого. Ничего не изменено.")
        if old_found:
            source = source.replace(old, new, 1)
            changed = True
    return source, changed


def check_api() -> None:
    last_error = "сервер не отвечает"
    for _ in range(12):
        try:
            with urllib.request.urlopen("http://127.0.0.1:8000/openapi.json", timeout=3) as response:
                if response.status == 200 and b'"/api/halloween-2026/status"' in response.read():
                    return
                last_error = "маршрут Halloween отсутствует в OpenAPI"
        except Exception as exc:
            last_error = str(exc)
        time.sleep(2)
    raise RuntimeError("После перезапуска API не подтвердился: " + last_error)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    command = parser.add_mutually_exclusive_group(required=True)
    command.add_argument("--check", action="store_true")
    command.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    if os.geteuid() != 0:
        raise RuntimeError("Запусти от root в Termius")
    if MODULE.is_symlink() or not MODULE.is_file():
        raise RuntimeError("Модуль Halloween не найден или является ссылкой. Остановлено.")
    if run("systemctl", "is-active", SERVICE) != "active":
        raise RuntimeError("Сервис nyan-wallet неактивен. Остановлено.")

    original = MODULE.read_bytes()
    updated, changed = rewrite(original)
    with tempfile.TemporaryDirectory(prefix="nyan-halloween-opening-") as folder:
        candidate = Path(folder) / "halloween_2026.py"
        candidate.write_bytes(updated)
        run(sys.executable, "-m", "py_compile", str(candidate))

    print("Открытие: 29.10.2026, 17:00 МСК")
    print("Тайная комната: 31.10.2026, 23:00 МСК")
    print("Окончание: 01.11.2026, 00:00 МСК")
    print("Сервер:", "нужно обновление" if changed else "уже обновлён")
    if args.check:
        print("Проверка ОК. Данные и сервер не изменены.")
        return
    if not changed:
        check_api()
        print("Уже применено. API работает.")
        return

    backup = MODULE.with_name(f"halloween_2026.py.before-opening-{datetime.now():%Y%m%d-%H%M%S}")
    if backup.exists():
        raise RuntimeError("Резервная копия с таким именем уже существует")
    shutil.copy2(MODULE, backup)
    print("Резервная копия:", backup)
    try:
        MODULE.write_bytes(updated)
        run("systemctl", "restart", SERVICE)
        check_api()
    except Exception:
        shutil.copy2(backup, MODULE)
        try:
            run("systemctl", "restart", SERVICE)
        except Exception as exc:
            print("Не удалось перезапустить сервис после отката:", exc, file=sys.stderr)
        print("Изменения отменены, резервная копия сохранена", file=sys.stderr)
        raise
    print("Готово. Сервер разрешает участие с 29 октября, 17:00 МСК.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("ОШИБКА:", exc, file=sys.stderr)
        sys.exit(1)
