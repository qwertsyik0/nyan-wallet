#!/usr/bin/env python3
"""Enable all achievement badges for the Nyan Wallet owner, preserving live changes.

Run as root: --check (read only), then --apply. The script does not touch the DB.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from datetime import datetime
from pathlib import Path
import os


TARGET = Path("/opt/nyan-wallet/server/achievements.py")
SERVICE = "nyan-wallet"
PATCHES = (
    (
        "    unlock_map = {row.achievement_key: row for row in unlock_rows}\n"
        "    badge = session.get(AchievementBadge, telegram_id)",
        "    unlock_map = {row.achievement_key: row for row in unlock_rows}\n"
        "    owner_access = core.is_owner(telegram_id)\n"
        "    badge = session.get(AchievementBadge, telegram_id)",
    ),
    (
        "        unlocked = row is not None\n",
        "        unlocked = owner_access or row is not None\n",
    ),
    (
        '        "unlocked_count": len(unlock_map),',
        '        "unlocked_count": len(ACHIEVEMENTS) if owner_access else len(unlock_map),',
    ),
    (
        '            unlocked = session.scalar(\n'
        '                select(AchievementUnlock.id).where(\n'
        '                    AchievementUnlock.telegram_id == tg["id"],\n'
        '                    AchievementUnlock.achievement_key == key,\n'
        '                )\n'
        '            )\n'
        '            if unlocked is None:\n'
        '                raise HTTPException(status_code=409, detail="Сначала откройте это достижение")',
        '            if not core.is_owner(int(tg["id"])):\n'
        '                unlocked = session.scalar(\n'
        '                    select(AchievementUnlock.id).where(\n'
        '                        AchievementUnlock.telegram_id == tg["id"],\n'
        '                        AchievementUnlock.achievement_key == key,\n'
        '                    )\n'
        '                )\n'
        '                if unlocked is None:\n'
        '                    raise HTTPException(status_code=409, detail="Сначала откройте это достижение")',
    ),
)


def rewrite(source: bytes) -> tuple[bytes, bool]:
    found = []
    for old_text, new_text in PATCHES:
        old = old_text.encode("utf-8")
        new = new_text.encode("utf-8")
        old_count, new_count = source.count(old), source.count(new)
        if old_count + new_count != 1:
            raise RuntimeError("Версия achievements.py отличается. Ничего не изменено.")
        found.append(old_count == 1)
    if any(found) and not all(found):
        raise RuntimeError("Найдено частичное обновление. Ничего не изменено.")
    if not any(found):
        return source, False
    for old_text, new_text in PATCHES:
        source = source.replace(old_text.encode("utf-8"), new_text.encode("utf-8"), 1)
    return source, True


def run(*cmd: str) -> str:
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode:
        raise RuntimeError(f"Ошибка {cmd[0]}: {(result.stderr or result.stdout)[-1200:]}")
    return result.stdout.strip()


def health() -> None:
    error = "Сервер не ответил"
    for _ in range(12):
        try:
            with urllib.request.urlopen("http://127.0.0.1:8000/openapi.json", timeout=3) as response:
                data = response.read()
                if response.status == 200 and b'"/api/achievements"' in data and b'"/api/achievements/badge"' in data:
                    return
                error = "Маршруты достижений отсутствуют в API"
        except Exception as exc:
            error = str(exc)
        time.sleep(2)
    raise RuntimeError("После перезапуска не пройдена проверка API: " + error)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if os.geteuid() != 0:
        raise RuntimeError("Запусти от root через Termius")
    if TARGET.is_symlink() or not TARGET.is_file():
        raise RuntimeError("Файл achievements.py отсутствует или является ссылкой")
    if run("systemctl", "is-active", SERVICE) != "active":
        raise RuntimeError("Сервис nyan-wallet неактивен")

    original = TARGET.read_bytes()
    updated, changed = rewrite(original)
    with tempfile.TemporaryDirectory(prefix="nyan-owner-achievements-check-") as folder:
        candidate = Path(folder) / "achievements.py"
        candidate.write_bytes(updated)
        run(sys.executable, "-m", "py_compile", str(candidate))

    print("Все достижения для владельца:", "требуется обновление" if changed else "уже открыты")
    print("Секретные достижения: открыты и доступны для выбора")
    print("Остальные пользователи и начисления: без изменений")
    if args.check:
        print("Проверка ОК. Данные не изменены.")
        return
    if not changed:
        health()
        print("Обновление уже установлено. API работает.")
        return

    backup = TARGET.with_name(f"achievements.py.before-owner-access-{datetime.now():%Y%m%d-%H%M%S}")
    if backup.exists():
        raise RuntimeError("Резервная копия с таким именем уже существует")
    shutil.copy2(TARGET, backup)
    print("Резервная копия:", backup)
    try:
        TARGET.write_bytes(updated)
        run("systemctl", "restart", SERVICE)
        health()
    except Exception:
        shutil.copy2(backup, TARGET)
        try:
            run("systemctl", "restart", SERVICE)
        except Exception as exc:
            print("Не удалось восстановить сервис:", exc, file=sys.stderr)
        print("Изменения отменены, резервная копия сохранена", file=sys.stderr)
        raise
    print("Готово. Владельцу доступны все достижения, в том числе секретные.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("ОШИБКА:", exc, file=sys.stderr)
        sys.exit(1)
