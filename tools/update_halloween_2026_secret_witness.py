#!/usr/bin/env python3
"""Open room six on October 29 at 23:00 MSK and award the first regular solver.

Run --check before --apply on the existing server. Only surgically modifies
Halloween server logic. Wallets, puzzles, solved_at records and schema stay as-is.
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

OLD_WITNESS = '''def first_witness_id(session) -> int | None:
    """The earliest persisted sixth-room completion wins, including past solves."""
    return session.scalar(
        select(HalloweenRoom.telegram_id)
        .where(HalloweenRoom.room == 6, HalloweenRoom.solved_at.is_not(None))
        .order_by(HalloweenRoom.solved_at.asc(), HalloweenRoom.telegram_id.asc())
        .limit(1)
    )
'''

NEW_WITNESS = '''def first_witness_id(session) -> int | None:
    """Earliest regular participant to finish room 6. Owner previews do not compete."""
    completions = session.scalars(
        select(HalloweenRoom.telegram_id)
        .where(HalloweenRoom.room == 6, HalloweenRoom.solved_at.is_not(None))
        .order_by(HalloweenRoom.solved_at.asc(), HalloweenRoom.telegram_id.asc())
    )
    return next((uid for uid in completions if not core.is_owner(uid)), None)
'''

PATCHES = (
    (
        "SECRET_AT = datetime(2026, 10, 31, 20, 0, tzinfo=UTC)  # Oct 31, 23:00 MSK",
        "SECRET_AT = datetime(2026, 10, 29, 20, 0, tzinfo=UTC)  # Oct 29, 23:00 MSK",
    ),
    (OLD_WITNESS, NEW_WITNESS),
)


def run(*args: str) -> str:
    result = subprocess.run(args, capture_output=True, text=True, check=False)
    if result.returncode:
        raise RuntimeError(f"Команда {args[0]}: {(result.stderr or result.stdout)[-1200:]}")
    return result.stdout.strip()


def rewrite(source: bytes) -> tuple[bytes, bool]:
    changed = False
    for before, after in PATCHES:
        old, new = before.encode("utf-8"), after.encode("utf-8")
        if source.count(old) + source.count(new) != 1:
            raise RuntimeError("Модуль Halloween отличается от ожидаемого. Ничего не изменено.")
        if source.count(old) == 1:
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
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    if os.geteuid() != 0:
        raise RuntimeError("Запусти от root через Termius")
    if MODULE.is_symlink() or not MODULE.is_file():
        raise RuntimeError("Модуль Halloween не найден или является ссылкой. Остановлено.")
    if run("systemctl", "is-active", SERVICE) != "active":
        raise RuntimeError("Сервис nyan-wallet неактивен. Остановлено.")

    original = MODULE.read_bytes()
    updated, changed = rewrite(original)
    with tempfile.TemporaryDirectory(prefix="nyan-halloween-secret-check-") as directory:
        candidate = Path(directory) / "halloween_2026.py"
        candidate.write_bytes(updated)
        run(sys.executable, "-m", "py_compile", str(candidate))

    print("Последняя комната: 29.10.2026, 23:00 МСК")
    print("Первый свидетель: первый обычный игрок, прошедший комнату №6")
    print("Владелец не участвует в гонке за звание Первого свидетеля")
    print("Состояние:", "нужно обновление" if changed else "уже обновлено")
    if args.check:
        print("Проверка ОК. Сервер и данные не изменены.")
        return
    if not changed:
        check_api()
        print("Уже применено. API отвечает.")
        return

    backup = MODULE.with_name(f"halloween_2026.py.before-secret-{datetime.now():%Y%m%d-%H%M%S}")
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
        print("Изменения отменены, резервная копия сохранена.", file=sys.stderr)
        raise
    print("Готово. Дверь открывается сегодня в 23:00 МСК, обе награды доступны обычному победителю.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("ОШИБКА:", exc, file=sys.stderr)
        sys.exit(1)
