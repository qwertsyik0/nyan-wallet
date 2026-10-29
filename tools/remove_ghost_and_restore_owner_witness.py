#!/usr/bin/env python3
"""Hide the obsolete ghost badge and award First Witness to owner + first regular solver.

Run --check before --apply on the existing Nyan Wallet server as root.
Only exact code fragments change; historical badge rows and wallet data remain.
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
EVENT = SERVER / "halloween_2026.py"
ACH = SERVER / "achievements.py"
SERVICE = "nyan-wallet"


EVENT_PATCHES = (
    (
        '("Комната без номера", "Няник оставил последнюю запись. Она откроется ночью."),',
        '("Комната без номера", "Няник оставил последнюю запись. Открой её после пяти комнат."),',
    ),
    (
        'raise HTTPException(status_code=409, detail="Последняя дверь откроется в 23:00 МСК")',
        'raise HTTPException(status_code=409, detail="Последняя дверь откроется вместе с событием")',
    ),
    (
        'def first_witness_id(session) -> int | None:\n'
        '    """The earliest persisted sixth-room completion wins, including past solves."""\n'
        '    return session.scalar(\n'
        '        select(HalloweenRoom.telegram_id)\n'
        '        .where(HalloweenRoom.room == 6, HalloweenRoom.solved_at.is_not(None))\n'
        '        .order_by(HalloweenRoom.solved_at.asc(), HalloweenRoom.telegram_id.asc())\n'
        '        .limit(1)\n'
        '    )',
        'def first_witness_id(session) -> int | None:\n'
        '    """Earliest regular participant to finish room 6. Owner previews do not compete."""\n'
        '    completions = session.scalars(\n'
        '        select(HalloweenRoom.telegram_id)\n'
        '        .where(HalloweenRoom.room == 6, HalloweenRoom.solved_at.is_not(None))\n'
        '        .order_by(HalloweenRoom.solved_at.asc(), HalloweenRoom.telegram_id.asc())\n'
        '    )\n'
        '    return next((uid for uid in completions if not core.is_owner(uid)), None)',
    ),
    (
        '        badge = session.get(HalloweenBadge, uid) is not None\n'
        '        final_completed = 6 in solved\n'
        '        first_witness = final_completed and first_witness_id(session) == uid',
        '        final_completed = 6 in solved\n'
        '        first_witness = final_completed and (core.is_owner(uid) or first_witness_id(session) == uid)',
    ),
    (
        '            "badge": badge, "final_badge": final_completed, "first_witness": first_witness,',
        '            "final_badge": final_completed, "first_witness": first_witness,',
    ),
    (
        '                if payload.room == 5 and session.get(HalloweenBadge, uid) is None:\n'
        '                    session.add(HalloweenBadge(telegram_id=uid, awarded_at=now))\n'
        '                    from .advanced_features import WalletNotification\n'
        '                    session.add(WalletNotification(telegram_id=uid, kind="halloween_reward",\n'
        '                                                   title="Ночь Няника · пройдено",\n'
        '                                                   body="Все пять комнат пройдены. Значок «Призрак Няника» получен!",\n'
        '                                                   is_read=False, created_at=now))\n'
        '                result = {"correct": True, "already_completed": False, "reward": amount}',
        '                result = {"correct": True, "already_completed": False, "reward": amount}',
    ),
)

ACH_PATCHES = (
    (
        '    from .halloween_2026 import HalloweenBadge, HalloweenRoom, first_witness_id\n'
        '    halloween_badge = session.get(HalloweenBadge, telegram_id)\n'
        '    sixth_room = session.get(HalloweenRoom, (telegram_id, 6))\n'
        '    finale_completed = bool(sixth_room and sixth_room.solved_at)\n'
        '    first_witness = finale_completed and first_witness_id(session) == telegram_id',
        '    from .halloween_2026 import HalloweenRoom, first_witness_id\n'
        '    sixth_room = session.get(HalloweenRoom, (telegram_id, 6))\n'
        '    finale_completed = bool(sixth_room and sixth_room.solved_at)\n'
        '    first_witness = finale_completed and (core.is_owner(telegram_id) or first_witness_id(session) == telegram_id)',
    ),
    (
        '        "halloween_badge": (\n'
        '            {"title": "Призрак Няника", "symbol": "◈", "awarded_at": halloween_badge.awarded_at.isoformat()}\n'
        '            if halloween_badge else None\n'
        '        ),\n'
        '        "halloween_rewards": halloween_rewards,',
        '        "halloween_rewards": halloween_rewards,',
    ),
)


def rewrite(source: bytes, patches: tuple, module: str) -> tuple[bytes, bool]:
    changed = False
    for before, after in patches:
        old, new = before.encode("utf-8"), after.encode("utf-8")
        old_count, new_count = source.count(old), source.count(new)
        if old_count > 1 or (old_count == 0 and new_count != 1):
            raise RuntimeError(f"{module}: неожиданные локальные отличия. Ничего не изменено.")
        if old_count:
            source = source.replace(old, new, 1)
            changed = True
    return source, changed


def rewrite_event(source: bytes) -> tuple[bytes, bool]:
    possible = (
        b'SECRET_AT = datetime(2026, 10, 31, 20, 0, tzinfo=UTC)  # Oct 31, 23:00 MSK',
        b'SECRET_AT = datetime(2026, 10, 29, 20, 0, tzinfo=UTC)  # Oct 29, 23:00 MSK',
        b'SECRET_AT = START_AT  # Last room opens with the event; five rooms and key are still required.',
    )
    counts = [source.count(line) for line in possible]
    if sum(counts) != 1:
        raise RuntimeError("Время открытия последней комнаты отличается от ожидаемого. Остановлено.")
    timing_changed = counts[2] == 0
    if timing_changed:
        source = source.replace(possible[counts.index(1)], possible[2], 1)
    updated, code_changed = rewrite(source, EVENT_PATCHES, "halloween_2026.py")
    return updated, timing_changed or code_changed


def run(*argv: str) -> str:
    result = subprocess.run(argv, capture_output=True, text=True, check=False)
    if result.returncode:
        raise RuntimeError(f"Ошибка {argv[0]}: {(result.stderr or result.stdout)[-1200:]}")
    return result.stdout.strip()


def check_api() -> None:
    problem = "нет ответа"
    for _ in range(12):
        try:
            with urllib.request.urlopen("http://127.0.0.1:8000/openapi.json", timeout=3) as response:
                paths = response.read()
                if response.status == 200 and b'"/api/halloween-2026/status"' in paths and b'"/api/achievements"' in paths:
                    return
                problem = "не найдены маршруты Halloween или достижений"
        except Exception as exc:
            problem = str(exc)
        time.sleep(2)
    raise RuntimeError("После перезапуска API не подтвердился: " + problem)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--check", action="store_true")
    action.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    if os.geteuid() != 0:
        raise RuntimeError("Запусти от root через Termius")
    if any(path.is_symlink() or not path.is_file() for path in (EVENT, ACH)):
        raise RuntimeError("Модуль Halloween или достижений отсутствует либо является ссылкой")
    if run("systemctl", "is-active", SERVICE) != "active":
        raise RuntimeError("Сервис nyan-wallet неактивен. Остановлено.")

    planned = []
    for path, patches in ((EVENT, EVENT_PATCHES), (ACH, ACH_PATCHES)):
        original = path.read_bytes()
        updated, changed = rewrite_event(original) if path == EVENT else rewrite(original, patches, path.name)
        planned.append((path, updated, changed))

    with tempfile.TemporaryDirectory(prefix="nyan-ghost-update-") as directory:
        for path, updated, _ in planned:
            candidate = Path(directory) / path.name
            candidate.write_bytes(updated)
            run(sys.executable, "-m", "py_compile", str(candidate))

    for path, _, changed in planned:
        print(path.name + ":", "требуется обновление" if changed else "уже обновлён")
    if args.check:
        print("Проверка ОК. Система и данные не изменены.")
        return

    updates = [(path, updated) for path, updated, changed in planned if changed]
    if not updates:
        check_api()
        print("Уже применено. API отвечает.")
        return

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backups = []
    try:
        for path, updated in updates:
            backup = path.with_name(path.name + f".before-no-ghost-{stamp}")
            if backup.exists():
                raise RuntimeError("Резервная копия уже существует: " + str(backup))
            shutil.copy2(path, backup)
            backups.append((path, backup))
            path.write_bytes(updated)
            print("Резервная копия:", backup)
        run("systemctl", "restart", SERVICE)
        check_api()
    except Exception:
        for path, backup in reversed(backups):
            shutil.copy2(backup, path)
        if backups:
            try:
                run("systemctl", "restart", SERVICE)
            except Exception as exc:
                print("Не удалось восстановить сервис:", exc, file=sys.stderr)
        print("Обновление отменено, резервные копии сохранены.", file=sys.stderr)
        raise
    print("Готово. Последняя комната открыта для игроков с пятью решёнными комнатами и ключом.")
    print("Призрак Няника скрыт. Первый свидетель: владелец и первый обычный участник.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("ОШИБКА:", exc, file=sys.stderr)
        sys.exit(1)
