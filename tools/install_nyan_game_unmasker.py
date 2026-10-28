#!/usr/bin/env python3
"""Safely install and award the two NYAN GAME «Разоблачитель» badges.

On FirstVDS, as root:
    python3 install_nyan_game_unmasker.py --check
    python3 install_nyan_game_unmasker.py --apply

Nothing is awarded during --check. Both awards and both bot notices are
idempotent; SQL is one transaction and aborts if a buyer cannot be verified.
"""

from __future__ import annotations

import argparse
import datetime
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path


PROJECT = Path("/opt/nyan-wallet")
BACKEND = PROJECT / "server/achievements.py"
SERVICE = "nyan-wallet"
DATABASE = "nyan_wallet_db"
SOURCE_COMMIT = "2f15f2101dc6be2c13ce76060b8add14959e9033"
BASE_COMMIT = "bbab9dd2fc9e00eb91e11d5f6be8a71d1b084c5b"
RAW = "https://raw.githubusercontent.com/qwertsyik0/nyan-wallet"


def download(revision: str, name: str) -> bytes:
    url = f"{RAW}/{revision}/{name}"
    with urllib.request.urlopen(url, timeout=20) as response:
        if response.status != 200:
            raise RuntimeError(f"Не удалось загрузить {name}: HTTP {response.status}")
        content = response.read()
    if not content:
        raise RuntimeError(f"Пустой файл: {name}")
    return content


def command(*args: str, input_text: str | None = None) -> str:
    result = subprocess.run(
        args, input=input_text, capture_output=True, text=True, check=False
    )
    if result.returncode:
        raise RuntimeError(
            f"Ошибка команды {args[0]}: {(result.stderr or result.stdout).strip()[-1400:]}"
        )
    return result.stdout.strip()


def query(sql: str) -> str:
    return command(
        "sudo", "-u", "postgres", "psql", "-X", "-v", "ON_ERROR_STOP=1",
        "-d", DATABASE, "-At", "-F", "|", "-c", sql
    )


def verify_users() -> None:
    result = query("""
        SELECT LOWER(username), telegram_id
        FROM users
        WHERE LOWER(username) IN ('pixel_are_you_okay', 'nirvr')
        ORDER BY LOWER(username), telegram_id;
    """)
    rows = [line.split("|", 1) for line in result.splitlines() if line.strip()]
    if len(rows) != 2 or {row[0] for row in rows} != {"pixel_are_you_okay", "nirvr"}:
        raise RuntimeError(
            "Покупатели не найдены или неоднозначны. Выдача отменена. "
            "Найденные записи: " + repr(rows)
        )
    if len({row[1] for row in rows}) != 2:
        raise RuntimeError("Telegram ID покупателей совпадают. Выдача отменена.")
    for username, telegram_id in rows:
        print(f"Покупатель: @{username} · Telegram ID {telegram_id}")


def healthcheck() -> None:
    last_error = "неизвестно"
    for _ in range(12):
        try:
            with urllib.request.urlopen("http://127.0.0.1:8000/api/health", timeout=3) as r:
                if r.status == 200:
                    return
        except Exception as exc:
            last_error = str(exc)
        time.sleep(2)
    raise RuntimeError("Nyan Wallet не ответил после перезапуска: " + last_error)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--check", action="store_true")
    action.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    if os.geteuid() != 0:
        raise RuntimeError("Запускайте от root на FirstVDS")
    if not BACKEND.is_file() or BACKEND.is_symlink():
        raise RuntimeError(f"Серверный файл отсутствует или является ссылкой: {BACKEND}")

    print("Скачиваем две версии серверного модуля и SQL из зафиксированного коммита…")
    before = download(BASE_COMMIT, "server/achievements.py")
    after = download(SOURCE_COMMIT, "server/achievements.py")
    award_sql = download(SOURCE_COMMIT, "tools/award_nyan_game_unmasker.sql").decode()
    live = BACKEND.read_bytes()
    if live not in (before, after):
        raise RuntimeError(
            "Серверный achievements.py отличается от проверенной версии. "
            "Ничего не изменено; сначала нужно сравнить локальные изменения."
        )

    with tempfile.TemporaryDirectory(prefix="nyan-unmasker-") as tmp_dir:
        candidate = Path(tmp_dir) / "achievements.py"
        candidate.write_bytes(after)
        command(sys.executable, "-m", "py_compile", str(candidate))

    if command("systemctl", "is-active", SERVICE) != "active":
        raise RuntimeError("Сервис nyan-wallet не активен; установка остановлена")
    verify_users()
    print("Модуль:", "уже обновлён" if live == after else "нужно обновить")

    if args.check:
        print("Проверка ОК. Данные и значки не изменены.")
        return

    if live != after:
        suffix = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        backup = BACKEND.with_name(f"achievements.py.before-unmasker-{suffix}")
        shutil.copy2(BACKEND, backup)
        print("Резервная копия:", backup)
        try:
            BACKEND.write_bytes(after)
            command("systemctl", "restart", SERVICE)
            healthcheck()
        except Exception:
            shutil.copy2(backup, BACKEND)
            command("systemctl", "restart", SERVICE)
            print("Старая версия модуля восстановлена")
            raise
    else:
        healthcheck()

    print("Сервер работает. Выдаём значки и ставим уведомления в очередь…")
    print(command(
        "sudo", "-u", "postgres", "psql", "-X", "-v", "ON_ERROR_STOP=1",
        "-d", DATABASE, input_text=award_sql
    ))
    print("Проверка выдачи:")
    print(query("""
        SELECT u.username, b.edition, o.state, COALESCE(o.last_error, '')
        FROM limited_profile_badges b
        JOIN users u ON u.telegram_id = b.telegram_id
        LEFT JOIN telegram_relay_outbox o
          ON o.source_key = 'nyan_game_unmasker_20261028_' ||
             LPAD(b.edition::TEXT, 2, '0')
        WHERE b.badge_key = 'nyan_game_unmasker'
        ORDER BY b.edition;
    """))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print("ОШИБКА:", error, file=sys.stderr)
        sys.exit(1)
