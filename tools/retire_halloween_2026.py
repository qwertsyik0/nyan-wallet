#!/usr/bin/env python3
"""Retire Halloween and Nyanik's Case Zero without deleting their rewards.

Run on FirstVDS as root: --check, then --apply. Existing server customizations
are preserved: only recognized source snippets are changed; mismatches abort.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import stat
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
CHOICE = SERVER / "halloween_boot_choice_2026.py"
ARCHIVE = SERVER / "nyan_archive_2026.py"
RETIRED_MESSAGE = '        raise HTTPException(status_code=410, detail="Хеллоуинский ивент завершён")\n'


def replace_once(source: str, old: str, new: str, name: str) -> str:
    if new in source:
        return source
    if source.count(old) != 1:
        raise RuntimeError(f"Ожидаемый участок {name} изменён; сервер не затронут")
    return source.replace(old, new, 1)


def retire_event(source: str) -> str:
    if not re.search(r"^RETIRED = True\b", source, flags=re.MULTILINE):
        source = replace_once(source, "_REGISTERED = False\n", "_REGISTERED = False\nRETIRED = True  # Event ended; preserve existing rewards and records.\n", "event flag")
    source = replace_once(
        source, "def _require_live(now: datetime) -> None:\n",
        "def _require_live(now: datetime) -> None:\n    if RETIRED:\n" + RETIRED_MESSAGE,
        "event time guard",
    )
    source = replace_once(
        source, "        open_now = (START_AT <= now < END_AT or (room == 6 and core.is_owner(uid) and now < END_AT)) and accessible\n",
        "        open_now = not RETIRED and (START_AT <= now < END_AT or (room == 6 and core.is_owner(uid) and now < END_AT)) and accessible\n",
        "event room access",
    )
    source = replace_once(
        source, '"active": START_AT <= now < END_AT,',
        '"active": not RETIRED and START_AT <= now < END_AT,', "event status",
    )
    source = replace_once(source, '"finished": now >= END_AT,', '"finished": RETIRED or now >= END_AT,', "event finished")
    source = replace_once(source, '"owner_early_access": core.is_owner(uid) and now < END_AT,',
                          '"owner_early_access": not RETIRED and core.is_owner(uid) and now < END_AT,', "owner preview")
    source = replace_once(
        source,
        '    tg_user = _identity(x_telegram_init_data)\n    if not KEY_RE.fullmatch(payload.request_key):',
        '    tg_user = _identity(x_telegram_init_data)\n    if RETIRED:\n' + RETIRED_MESSAGE + '    if not KEY_RE.fullmatch(payload.request_key):',
        "event answer",
    )
    source = replace_once(
        source,
        '    tg_user = _identity(x_telegram_init_data)\n    now = core.now_utc()\n    if not (core.is_owner(int(tg_user["id"])) and now < END_AT):',
        '    tg_user = _identity(x_telegram_init_data)\n    if RETIRED:\n' + RETIRED_MESSAGE + '    now = core.now_utc()\n    if not (core.is_owner(int(tg_user["id"])) and now < END_AT):',
        "event secret unlock",
    )
    return source


def retire_choice(source: str) -> str:
    if not re.search(r"^RETIRED = True\b", source, flags=re.MULTILINE):
        source = replace_once(source, 'AWARDS = {"sweet": 300, "trick": -400}\n',
                              'AWARDS = {"sweet": 300, "trick": -400}\nRETIRED = True  # Keep prior choices; forbid new transfers.\n', "choice flag")
    source = replace_once(source, '"eligible": user is not None and existing is None and not blocked,',
                          '"eligible": not RETIRED and user is not None and existing is None and not blocked,', "choice status")
    source = replace_once(
        source,
        '        if session.get(BlockedUser, telegram_id) is not None:\n',
        '        if RETIRED:\n' + '    ' + RETIRED_MESSAGE + '        if session.get(BlockedUser, telegram_id) is not None:\n',
        "choice transfer guard",
    )
    return source


def retire_archive(source: str) -> str:
    if not re.search(r"^RETIRED = True\b", source, flags=re.MULTILINE):
        source = replace_once(
            source, "_REGISTERED = False\n",
            "_REGISTERED = False\nRETIRED = True  # Case closed; preserve completions and rewards.\n",
            "archive flag",
        )
    source = replace_once(
        source,
        "    preview = telegram_id is not None and core.is_owner(telegram_id)\n",
        "    preview = not RETIRED and telegram_id is not None and core.is_owner(telegram_id)\n",
        "archive owner preview",
    )
    source = replace_once(
        source, '"is_open": now >= OPEN_AT,',
        '"is_open": not RETIRED and now >= OPEN_AT,', "archive status",
    )
    source = replace_once(
        source, '"records": [_record_status(record, now=now, preview=preview) for record in RECORDS],',
        '"records": [] if RETIRED else [_record_status(record, now=now, preview=preview) for record in RECORDS],',
        "archive records",
    )
    source = replace_once(
        source,
        '    uid = int(tg["id"])\n    if now < RECORDS[-1]["at"] and not core.is_owner(uid):',
        '    uid = int(tg["id"])\n    if RETIRED:\n'
        '        raise HTTPException(status_code=410, detail="Дело №0 завершено")\n'
        '    if now < RECORDS[-1]["at"] and not core.is_owner(uid):',
        "archive solve guard",
    )
    return source


def run(*args: str) -> str:
    result = subprocess.run(args, capture_output=True, text=True, check=False)
    if result.returncode:
        raise RuntimeError(f"{args[0]}: {(result.stderr or result.stdout)[-500:]}")
    return result.stdout.strip()


def write_atomically(path: Path, payload: bytes) -> None:
    fd, temp = tempfile.mkstemp(prefix=".retire-halloween-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temp, stat.S_IMODE(path.stat().st_mode))
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--check", action="store_true")
    group.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if os.geteuid() != 0:
        raise RuntimeError("Запусти в Termius от root")
    if not EVENT.is_file():
        raise RuntimeError("Модуль Halloween на сервере не найден")
    modules = [(EVENT, retire_event)]
    if CHOICE.is_file():
        modules.append((CHOICE, retire_choice))
    if ARCHIVE.is_file():
        modules.append((ARCHIVE, retire_archive))
    if any(path.is_symlink() for path, _ in modules):
        raise RuntimeError("Обнаружена символическая ссылка; установка остановлена")
    if run("systemctl", "is-active", SERVICE) != "active":
        raise RuntimeError("Сервис nyan-wallet не работает")
    changes = []
    for path, transform in modules:
        before = path.read_bytes()
        after = transform(before.decode("utf-8")).encode("utf-8")
        compile(after, str(path), "exec")
        if before != after:
            changes.append((path, before, after))
    print("На проверке:", ", ".join(p.name for p, _ in modules))
    print("Потребуют обновления:", ", ".join(p.name for p, _, _ in changes) or "нет")
    if args.check:
        print("Проверка пройдена. Данные пользователей не изменены.")
        return
    if not changes:
        print("Хеллоуинские API уже закрыты.")
        return
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backups = []
    try:
        for path, before, after in changes:
            backup = path.with_name(f"{path.name}.before-retire-{stamp}")
            if backup.exists():
                raise RuntimeError("Резервная копия уже существует")
            shutil.copy2(path, backup)
            backups.append((path, backup))
            write_atomically(path, after)
        run("systemctl", "restart", SERVICE)
        for _ in range(15):
            try:
                with urllib.request.urlopen("http://127.0.0.1:8000/openapi.json", timeout=3) as response:
                    if response.status == 200 and b"/api/achievements" in response.read():
                        break
            except Exception:
                time.sleep(1)
        else:
            raise RuntimeError("После перезапуска не ответил API достижений")
    except Exception:
        for path, backup in reversed(backups):
            shutil.copy2(backup, path)
        run("systemctl", "restart", SERVICE)
        raise
    print("Ивенты закрыты. Награды, значки, балансы и история сохранены.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("ОШИБКА:", exc, file=sys.stderr)
        sys.exit(1)
