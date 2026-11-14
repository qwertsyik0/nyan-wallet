#!/usr/bin/env python3
"""Safely enable a clearly labelled 24-hour zero-only Fortune event.

--check: inspect the exact server module, pause flag, new code and API.
--start: install the patch if necessary, save backups, restart once when needed,
         remove an existing pause and start the zero-only 24-hour event.
--status: report the current event time and pause state.
--stop: immediately restore normal random spins; no restart needed.

The event config remains on disk after expiry so the owner can query participants
later for the separately planned 500-paw thank-you grant.
"""

from __future__ import annotations

import argparse
import ast
import datetime as dt
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path("/opt/nyan-wallet")
MODULE = ROOT / "server/fortune.py"
PAUSE_FILE = ROOT / ".fortune_disabled"
EVENT_FILE = ROOT / ".fortune_zero_day.json"
SERVICE = "nyan-wallet"
SOURCE_URL = (
    "https://raw.githubusercontent.com/qwertsyik0/nyan-wallet/"
    "main/server/fortune.py"
)
KNOWN_MODULE_BLOBS = {
    "eac4a4dc6fd18192e72b209a34a78215cf5a9d2e": "original",
    "a3e07f4b305623e01bca5117beeda83d5e20d9f7": "paused-mode",
    "fd78dde8b118724243859edf35a71d9b83b2e0a1": "zero-day-ready",
}
NEW_BLOB = "fd78dde8b118724243859edf35a71d9b83b2e0a1"
DURATION_SECONDS = 86_400
URL_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def git_blob(content: bytes) -> str:
    prefix = b"blob " + str(len(content)).encode("ascii") + b"\0"
    return hashlib.sha1(prefix + content).hexdigest()


def get_new_source() -> bytes:
    request = urllib.request.Request(
        SOURCE_URL, headers={"User-Agent": "NyanFortuneZeroDay/1.0"}
    )
    with URL_OPENER.open(request, timeout=30) as response:
        content = response.read(120_000)
    if git_blob(content) != NEW_BLOB:
        raise RuntimeError(
            "GitHub source content changed. No files were modified. "
            "Please obtain the current validated installer."
        )
    source = content.decode("utf-8")
    ast.parse(source, filename="server/fortune.py")
    for snippet in (
        'ZERO_DAY_FILE = Path(__file__).resolve().parents[1] / ".fortune_zero_day.json"',
        'ZERO_SECTOR_INDEX = SECTORS.index(0)',
        '"zero_day": zero_day_ends is not None,',
        'if _zero_day_ends_at(timestamp) is not None',
    ):
        if snippet not in source:
            raise RuntimeError("New module lacks expected zero-day logic")
    return content


def atomic_bytes(filename: Path, content: bytes) -> None:
    fd, temporary = tempfile.mkstemp(
        prefix=".nyan-fortune-event-", dir=filename.parent
    )
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, filename.stat().st_mode & 0o777
                 if filename.exists() else 0o600)
        os.replace(temporary, filename)
    finally:
        Path(temporary).unlink(missing_ok=True)


def call(*args: str) -> str:
    completed = subprocess.run(
        args, capture_output=True, text=True, timeout=90
    )
    if completed.returncode:
        raise RuntimeError(
            "Не выполнено: " + " ".join(args[:3])
            + "\n" + (completed.stderr or completed.stdout)[-900:]
        )
    return completed.stdout.strip()


def ready(*, attempts: int = 45) -> None:
    last = "no response"
    for n in range(attempts):
        try:
            if call("systemctl", "is-active", SERVICE) != "active":
                raise RuntimeError("nyan-wallet service not active")
            with URL_OPENER.open(
                "http://127.0.0.1:8000/openapi.json", timeout=5
            ) as response:
                paths = json.load(response).get("paths", {})
            if "/api/fortune" not in paths or "/api/fortune/spin" not in paths:
                raise RuntimeError("Fortune API routes not registered")
            return
        except Exception as exc:
            last = str(exc)
            if n + 1 < attempts:
                time.sleep(2)
    raise RuntimeError("Nyan Wallet API not ready: " + last)


def restart_api() -> None:
    call("systemctl", "restart", SERVICE)
    ready()


def event_info() -> dict | None:
    try:
        data = json.loads(EVENT_FILE.read_text(encoding="utf-8"))
        start = float(data["starts_at_unix"])
        end = float(data["ends_at_unix"])
        if end <= start or end - start > DURATION_SECONDS + 1:
            raise ValueError("Invalid event interval")
        return data
    except FileNotFoundError:
        return None


def active_event() -> bool:
    event = event_info()
    return bool(
        event
        and float(event["starts_at_unix"]) <= time.time()
        < float(event["ends_at_unix"])
    )


def print_status() -> None:
    event = event_info()
    print("Nyan Fortune Zero Day")
    print("Старое отключение:", "включено" if PAUSE_FILE.is_file() else "нет")
    if not event:
        print("Специальный режим: не настроен")
    else:
        expires = dt.datetime.fromtimestamp(
            float(event["ends_at_unix"]), tz=dt.timezone.utc
        )
        print("Специальный режим:", "АКТИВЕН" if active_event() else "завершён")
        print("Окончание по UTC:", expires.isoformat())
        print("Сохранён интервал для будущего бонуса +500 🐾 участникам")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--check", action="store_true")
    modes.add_argument("--start", action="store_true")
    modes.add_argument("--status", action="store_true")
    modes.add_argument("--stop", action="store_true")
    opt = parser.parse_args()

    if os.geteuid() != 0:
        raise RuntimeError("Run as root on FirstVDS")
    if not MODULE.is_file():
        raise RuntimeError(f"Missing {MODULE}")
    old = MODULE.read_bytes()
    old_hash = git_blob(old)
    if old_hash not in KNOWN_MODULE_BLOBS:
        raise RuntimeError(
            f"Unknown locally modified server/fortune.py: git blob {old_hash}. "
            "Won't overwrite existing customizations."
        )
    print("Server module:", KNOWN_MODULE_BLOBS[old_hash])
    if opt.status:
        print_status()
        return
    if opt.stop:
        if old_hash != NEW_BLOB:
            raise RuntimeError("The current server module has no zero-day support")
        event = event_info()
        if event and active_event():
            event["ends_at_unix"] = max(
                float(event["starts_at_unix"]) + 0.001, time.time()
            )
            event["stopped_early"] = True
            atomic_bytes(
                EVENT_FILE,
                (json.dumps(event, ensure_ascii=False) + "\n").encode("utf-8"),
            )
        PAUSE_FILE.unlink(missing_ok=True)
        print("OK: Обычные случайные вращения восстановлены.")
        print("Даты мероприятия сохранены для учёта будущего бонуса.")
        return

    new = get_new_source()
    ready(attempts=3)  # No modifications if server is already unhealthy.
    print_status()
    if opt.check:
        print("OK: проверка завершена, ничего не изменено.")
        if old_hash != NEW_BLOB:
            print("Первый запуск обновит Fortune API и перезапустит сервис один раз.")
        return

    if active_event():
        print("Специальный день уже активен. Срок не продлевается.")
        return

    backup = ROOT / ".fortune-backups" / (
        "zero-day-" + dt.datetime.now(dt.timezone.utc).strftime(
            "%Y%m%d-%H%M%S-%f"
        )
    )
    backup.mkdir(parents=True, mode=0o700, exist_ok=False)
    os.chmod(backup, 0o700)
    shutil.copy2(MODULE, backup / "fortune.py")
    old_event = EVENT_FILE.read_bytes() if EVENT_FILE.exists() else None
    if old_event is not None:
        archived = backup / "previous_zero_day.json"
        archived.write_bytes(old_event)
        os.chmod(archived, 0o600)
    was_paused = PAUSE_FILE.is_file()
    modified_source = False

    try:
        # Block ordinary spins temporarily while switching the runtime module.
        PAUSE_FILE.touch(exist_ok=True)
        if old_hash != NEW_BLOB:
            atomic_bytes(MODULE, new)
            modified_source = True
            restart_api()

        now = time.time()
        event = {
            "event": "nyan_fortune_zero_day",
            "starts_at_unix": now,
            "ends_at_unix": now + DURATION_SECONDS,
            "future_bonus_per_unique_spinner": 500,
        }
        atomic_bytes(
            EVENT_FILE,
            (json.dumps(event, ensure_ascii=False) + "\n").encode("utf-8"),
        )
        # Activation is atomic with respect to individual spin requests:
        # the pause remains until the zero-day config is on disk.
        PAUSE_FILE.unlink(missing_ok=True)
    except Exception as error:
        if old_event is None:
            EVENT_FILE.unlink(missing_ok=True)
        else:
            atomic_bytes(EVENT_FILE, old_event)
        if modified_source:
            atomic_bytes(MODULE, old)
            try:
                restart_api()
            except Exception as rollback:
                raise RuntimeError(
                    f"Installation failed: {error}. Rollback needs review: "
                    f"{rollback}. Backup {backup}"
                ) from error
        if not was_paused:
            PAUSE_FILE.unlink(missing_ok=True)
        raise RuntimeError(
            f"Installation cancelled; previous module restored. {error}. "
            f"Backup {backup}"
        ) from error

    print("OK: Колесо фортуны включено в специальном режиме 0 🐾.")
    print("У каждого нового вращения результат 0 🐾 (на 24 часа).")
    print("Обычные шансы вернутся автоматически после срока.")
    print("Повторное применение не продлевает активный режим.")
    print("Бонус +500 🐾 не начисляется этой командой — список участников сохранится.")
    print("Резервная копия:", backup)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        raise SystemExit("ОШИБКА: " + str(exc)) from exc
