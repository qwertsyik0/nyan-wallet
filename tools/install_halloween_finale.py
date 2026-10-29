#!/usr/bin/env python3
"""Install the Halloween finale without replacing unrelated production changes.

Run --check, then --apply as root. Read-only checks precede any server restart.
No database rows, prizes, or wallets are modified by this script.
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


SERVER = Path("/opt/nyan-wallet/server")
SERVICE = "nyan-wallet"
EVENT = SERVER / "halloween_2026.py"
ACH = SERVER / "achievements.py"


EVENT_PATCHES = (
    (
        'def _solved(session, uid: int) -> dict[int, HalloweenRoom]:\n'
        '    return {r.room: r for r in session.scalars(select(HalloweenRoom).where(HalloweenRoom.telegram_id == uid)) if r.solved_at is not None}\n'
        '\n\n'
        'def _can_enter(',
        'def _solved(session, uid: int) -> dict[int, HalloweenRoom]:\n'
        '    return {r.room: r for r in session.scalars(select(HalloweenRoom).where(HalloweenRoom.telegram_id == uid)) if r.solved_at is not None}\n'
        '\n\n'
        'def first_witness_id(session) -> int | None:\n'
        '    """The earliest persisted sixth-room completion wins, including past solves."""\n'
        '    return session.scalar(\n'
        '        select(HalloweenRoom.telegram_id)\n'
        '        .where(HalloweenRoom.room == 6, HalloweenRoom.solved_at.is_not(None))\n'
        '        .order_by(HalloweenRoom.solved_at.asc(), HalloweenRoom.telegram_id.asc())\n'
        '        .limit(1)\n'
        '    )\n'
        '\n\n'
        'def _can_enter(',
    ),
    (
        '        badge = session.get(HalloweenBadge, uid) is not None\n'
        '    items = []',
        '        badge = session.get(HalloweenBadge, uid) is not None\n'
        '        final_completed = 6 in solved\n'
        '        first_witness = final_completed and first_witness_id(session) == uid\n'
        '    items = []',
    ),
    (
        '            "badge": badge, "wallet_earned": sum(row.reward for row in solved.values()),',
        '            "badge": badge, "final_badge": final_completed, "first_witness": first_witness,\n'
        '            "wallet_earned": sum(row.reward for row in solved.values()),',
    ),
)

ACH_PATCHES = (
    (
        '    from .halloween_2026 import HalloweenBadge\n'
        '    halloween_badge = session.get(HalloweenBadge, telegram_id)\n'
        '    return {',
        '    from .halloween_2026 import HalloweenBadge, HalloweenRoom, first_witness_id\n'
        '    halloween_badge = session.get(HalloweenBadge, telegram_id)\n'
        '    sixth_room = session.get(HalloweenRoom, (telegram_id, 6))\n'
        '    finale_completed = bool(sixth_room and sixth_room.solved_at)\n'
        '    first_witness = finale_completed and first_witness_id(session) == telegram_id\n'
        '    halloween_rewards = []\n'
        '    if finale_completed:\n'
        '        halloween_rewards.append({\n'
        '            "key": "halloween_keeper_2026", "title": "Хранитель тайны", "symbol": "▣",\n'
        '            "description": "Раскрыть тайну последней комнаты", "rarity": "legendary",\n'
        '            "awarded_at": sixth_room.solved_at.isoformat(),\n'
        '        })\n'
        '    if first_witness:\n'
        '        halloween_rewards.append({\n'
        '            "key": "halloween_first_witness_2026", "title": "Первый свидетель", "symbol": "◉",\n'
        '            "description": "Первым раскрыть шестую комнату", "rarity": "mythic",\n'
        '            "awarded_at": sixth_room.solved_at.isoformat(),\n'
        '        })\n'
        '    return {',
    ),
    (
        '            if halloween_badge else None\n'
        '        ),\n'
        '    }\n\n\n@router.get("/api/achievements")',
        '            if halloween_badge else None\n'
        '        ),\n'
        '        "halloween_rewards": halloween_rewards,\n'
        '    }\n\n\n@router.get("/api/achievements")',
    ),
)


def rewrite(source: bytes, patches: tuple, name: str) -> tuple[bytes, bool]:
    found = []
    for old_text, new_text in patches:
        old, new = old_text.encode(), new_text.encode()
        old_count, new_count = source.count(old), source.count(new)
        if old_count + new_count != 1:
            raise RuntimeError(f"{name} отличается от проверенной структуры. Ничего не изменено.")
        found.append(bool(old_count))
    if any(found) and not all(found):
        raise RuntimeError(f"{name}: частичное обновление. Ничего не изменено.")
    if not any(found):
        return source, False
    for old_text, new_text in patches:
        source = source.replace(old_text.encode(), new_text.encode(), 1)
    return source, True


def run(*argv: str) -> str:
    proc = subprocess.run(argv, capture_output=True, text=True, check=False)
    if proc.returncode:
        raise RuntimeError(f"Ошибка {argv[0]}: {(proc.stderr or proc.stdout)[-1200:]}")
    return proc.stdout.strip()


def health() -> None:
    error = "Нет ответа"
    for _ in range(12):
        try:
            with urllib.request.urlopen("http://127.0.0.1:8000/openapi.json", timeout=3) as response:
                data = response.read()
                if response.status == 200 and b'"/api/halloween-2026/status"' in data and b'"/api/achievements"' in data:
                    return
                error = "Маршруты события или достижений не найдены"
        except Exception as exc:
            error = str(exc)
        time.sleep(2)
    raise RuntimeError("Сервер не прошёл проверку после перезапуска: " + error)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--check", action="store_true")
    action.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if os.geteuid() != 0:
        raise RuntimeError("Запусти от root через Termius")
    if any(path.is_symlink() or not path.is_file() for path in (EVENT, ACH)):
        raise RuntimeError("Не найдены модули Halloween и достижений или обнаружена ссылка")
    if run("systemctl", "is-active", SERVICE) != "active":
        raise RuntimeError("Сервис nyan-wallet неактивен")

    candidates = []
    for path, patches in ((EVENT, EVENT_PATCHES), (ACH, ACH_PATCHES)):
        original = path.read_bytes()
        updated, changed = rewrite(original, patches, path.name)
        candidates.append((path, original, updated, changed))
    with tempfile.TemporaryDirectory(prefix="nyan-halloween-finale-check-") as folder:
        for path, _, updated, _ in candidates:
            candidate = Path(folder) / path.name
            candidate.write_bytes(updated)
            run(sys.executable, "-m", "py_compile", str(candidate))

    for path, _, _, changed in candidates:
        print(path.name + ":", "требуется обновление" if changed else "уже обновлён")
    if args.check:
        print("Проверка ОК. Сервер и данные не изменены.")
        return
    changes = [row for row in candidates if row[3]]
    if not changes:
        health()
        print("Уже применено. API работает.")
        return

    suffix = datetime.now().strftime("%Y%m%d-%H%M%S")
    backups = []
    try:
        for path, _, updated, _ in changes:
            backup = path.with_name(path.name + f".before-finale-{suffix}")
            if backup.exists():
                raise RuntimeError("Резервная копия уже существует: " + str(backup))
            shutil.copy2(path, backup)
            backups.append((path, backup))
            path.write_bytes(updated)
            print("Резервная копия:", backup)
        run("systemctl", "restart", SERVICE)
        health()
    except Exception:
        for path, backup in reversed(backups):
            shutil.copy2(backup, path)
        if backups:
            try:
                run("systemctl", "restart", SERVICE)
            except Exception as exc:
                print("Ошибка восстановления сервиса:", exc, file=sys.stderr)
        print("Обновление отменено; резервные копии сохранены", file=sys.stderr)
        raise
    print("Готово. Финальная история и награды доступны ранее прошедшим и новым игрокам.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("ОШИБКА:", exc, file=sys.stderr)
        sys.exit(1)
