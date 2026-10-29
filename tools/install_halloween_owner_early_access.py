#!/usr/bin/env python3
"""Grant only the configured owner early entry to Halloween room six.

Surgical, idempotent server hotfix. Use --check, then --apply from Termius.
No user balances, database rows, other modules or event prizes are modified.
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
PATCHES = (
    (
        "def _can_enter(room: int, solved: dict, player: HalloweenPlayer, now: datetime) -> bool:\n"
        "    if room == 1:\n"
        "        return True\n"
        "    if room <= 5:\n"
        "        return room - 1 in solved\n"
        "    return all(i in solved for i in range(1, 6)) and player.secret_unlocked and now >= SECRET_AT",
        "def _can_enter(room: int, solved: dict, player: HalloweenPlayer | None, now: datetime, uid: int) -> bool:\n"
        "    if room == 1:\n"
        "        return True\n"
        "    if room <= 5:\n"
        "        return room - 1 in solved\n"
        "    if core.is_owner(uid):\n"
        "        return True\n"
        "    if player is None:\n"
        "        return False\n"
        "    return all(i in solved for i in range(1, 6)) and player.secret_unlocked and now >= SECRET_AT",
    ),
    (
        "        accessible = _can_enter(room, solved, player, now) if player else room == 1",
        "        accessible = _can_enter(room, solved, player, now, uid)",
    ),
    (
        "        open_now = START_AT <= now < END_AT and accessible",
        "        open_now = (START_AT <= now < END_AT or (room == 6 and core.is_owner(uid) and now < END_AT)) and accessible",
    ),
    (
        '            "secret_unlocked": bool(player and player.secret_unlocked),\n'
        '            "badge": badge,',
        '            "secret_unlocked": bool(player and player.secret_unlocked),\n'
        '            "owner_early_access": core.is_owner(uid) and now < END_AT,\n'
        '            "badge": badge,',
    ),
    (
        "    if not _can_enter(room, _solved(session, uid), player, now):",
        "    if not _can_enter(room, _solved(session, uid), player, now, uid):",
    ),
    (
        "    if not KEY_RE.fullmatch(payload.request_key):\n"
        '        raise HTTPException(status_code=422, detail="Некорректный ключ запроса")\n'
        "    now = core.now_utc()\n"
        "    _require_live(now)\n"
        '    uid = int(tg_user["id"])',
        "    if not KEY_RE.fullmatch(payload.request_key):\n"
        '        raise HTTPException(status_code=422, detail="Некорректный ключ запроса")\n'
        "    now = core.now_utc()\n"
        '    uid = int(tg_user["id"])\n'
        "    if payload.room != 6 or not (core.is_owner(uid) and now < END_AT):\n"
        "        _require_live(now)",
    ),
    (
        "def halloween_unlock(x_telegram_init_data: str | None = Header(default=None, alias=\"X-Telegram-Init-Data\")):\n"
        "    tg_user = _identity(x_telegram_init_data)\n"
        "    now = core.now_utc()\n"
        "    _require_live(now)\n"
        "    if now < SECRET_AT:",
        "def halloween_unlock(x_telegram_init_data: str | None = Header(default=None, alias=\"X-Telegram-Init-Data\")):\n"
        "    tg_user = _identity(x_telegram_init_data)\n"
        "    now = core.now_utc()\n"
        "    if not (core.is_owner(int(tg_user[\"id\"])) and now < END_AT):\n"
        "        _require_live(now)\n"
        "    if now < SECRET_AT and not core.is_owner(int(tg_user[\"id\"])):",
    ),
    (
        '            if not all(i in _solved(session, uid) for i in range(1, 6)):\n'
        '                raise HTTPException(status_code=409, detail="Сначала пройди пять комнат")\n'
        '            key = session.get(HalloweenInventory, (uid, "key"))\n'
        '            if key is None or key.quantity <= 0:\n'
        '                raise HTTPException(status_code=409, detail="Нужен ржавый ключ из лавки")\n'
        '            key.quantity -= 1',
        '            if not core.is_owner(uid):\n'
        '                if not all(i in _solved(session, uid) for i in range(1, 6)):\n'
        '                    raise HTTPException(status_code=409, detail="Сначала пройди пять комнат")\n'
        '                key = session.get(HalloweenInventory, (uid, "key"))\n'
        '                if key is None or key.quantity <= 0:\n'
        '                    raise HTTPException(status_code=409, detail="Нужен ржавый ключ из лавки")\n'
        '                key.quantity -= 1',
    ),
)


def rewrite(source: bytes) -> tuple[bytes, bool]:
    variants = []
    for old_text, new_text in PATCHES:
        old, new = old_text.encode(), new_text.encode()
        old_count, new_count = source.count(old), source.count(new)
        if old_count + new_count != 1:
            raise RuntimeError("Версия Halloween на сервере отличается; изменения остановлены")
        variants.append(bool(old_count))
    if any(variants) and not all(variants):
        raise RuntimeError("Обнаружено частичное обновление; изменения остановлены")
    if not any(variants):
        return source, False
    for old_text, new_text in PATCHES:
        source = source.replace(old_text.encode(), new_text.encode(), 1)
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
                if response.status == 200 and b'"/api/halloween-2026/status"' in response.read():
                    return
                error = "Маршрут Halloween отсутствует"
        except Exception as exc:
            error = str(exc)
        time.sleep(2)
    raise RuntimeError("Не пройдена проверка API после перезапуска: " + error)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if os.geteuid() != 0:
        raise RuntimeError("Запусти от root в Termius")
    if MODULE.is_symlink() or not MODULE.is_file():
        raise RuntimeError("Halloween ещё не установлен на сервер. Сначала установи модуль события.")
    if run("systemctl", "is-active", SERVICE) != "active":
        raise RuntimeError("Сервис nyan-wallet неактивен")

    previous = MODULE.read_bytes()
    updated, changed = rewrite(previous)
    with tempfile.TemporaryDirectory(prefix="nyan-halloween-owner-check-") as folder:
        candidate = Path(folder) / "halloween_2026.py"
        candidate.write_bytes(updated)
        run(sys.executable, "-m", "py_compile", str(candidate))

    print("Вход в последнюю комнату для владельца:", "готов к установке" if changed else "уже открыт")
    print("Обычные участники, загадки и награды: без изменений")
    if args.check:
        print("Проверка ОК. Сервер и данные не изменены.")
        return
    if not changed:
        health()
        print("Уже применено. API работает.")
        return

    backup = MODULE.with_name(f"halloween_2026.py.before-owner-{datetime.now():%Y%m%d-%H%M%S}")
    if backup.exists():
        raise RuntimeError("Резервная копия с таким именем уже существует")
    shutil.copy2(MODULE, backup)
    print("Резервная копия:", backup)
    try:
        MODULE.write_bytes(updated)
        run("systemctl", "restart", SERVICE)
        health()
    except Exception:
        shutil.copy2(backup, MODULE)
        try:
            run("systemctl", "restart", SERVICE)
        except Exception as exc:
            print("Ошибка восстановления сервиса:", exc, file=sys.stderr)
        print("Изменения отменены, резервная копия сохранена", file=sys.stderr)
        raise
    print("Готово. Последняя комната доступна владельцу прямо сейчас.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("ОШИБКА:", exc, file=sys.stderr)
        sys.exit(1)
