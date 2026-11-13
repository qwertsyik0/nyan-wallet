#!/usr/bin/env python3
"""Owner-operated, reversible Nyan Fortune pause on FirstVDS.

--check   Verify target version, status, download and API without changes
--pause   Install only server/fortune.py if needed and create runtime pause flag
--resume  Remove pause flag (no restart); use after successfully installing patch

When paused, the wheel reports "Временно недоступно", no spins are recorded,
and the daily opportunity is not consumed. Does not touch balances or database.
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
FLAG = ROOT / ".fortune_disabled"
SERVICE = "nyan-wallet"
SOURCE_URL = "https://raw.githubusercontent.com/qwertsyik0/nyan-wallet/main/server/fortune.py"
KNOWN_OLD_BLOB = "eac4a4dc6fd18192e72b209a34a78215cf5a9d2e"
NEW_BLOB = "a3e07f4b305623e01bca5117beeda83d5e20d9f7"
REQUIRED = (
    'PAUSE_FILE = Path(__file__).resolve().parents[1] / ".fortune_disabled"',
    'raise HTTPException(status_code=503, detail="Временно недоступно")',
    '"paused": paused,',
)


def blob(data: bytes) -> str:
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()


def fetch_new_module() -> bytes:
    req = urllib.request.Request(
        SOURCE_URL, headers={"User-Agent": "NYAN-Wallet-Fortune-Pause/1.0"}
    )
    with urllib.request.urlopen(req, timeout=25) as response:
        content = response.read(150_000)
    if blob(content) != NEW_BLOB:
        raise RuntimeError("Модуль GitHub отличается от проверенной версии. Установка отменена.")
    source = content.decode("utf-8")
    ast.parse(source, filename="server/fortune.py")
    if not all(fragment in source for fragment in REQUIRED):
        raise RuntimeError("В новой версии отсутствуют ожидаемые блокировки колеса")
    return content


def atomic_replace(filename: Path, content: bytes) -> None:
    fd, tmp = tempfile.mkstemp(prefix=".fortune-pause-", dir=filename.parent)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, filename.stat().st_mode & 0o777)
        os.replace(tmp, filename)
    finally:
        Path(tmp).unlink(missing_ok=True)


def api_ready(max_checks: int = 70) -> None:
    last = "API не отвечает"
    for index in range(max_checks):
        try:
            proc = subprocess.run(
                ["systemctl", "is-active", SERVICE],
                capture_output=True, text=True, timeout=7,
            )
            if proc.stdout.strip() != "active":
                raise RuntimeError(f"Служба {SERVICE}: {proc.stdout.strip() or 'неактивна'}")
            with urllib.request.urlopen(
                "http://127.0.0.1:8000/openapi.json", timeout=5
            ) as response:
                paths = json.load(response).get("paths", {})
            if "/api/fortune" not in paths or "/api/fortune/spin" not in paths:
                raise RuntimeError("Маршруты Колеса фортуны отсутствуют")
            return
        except Exception as exc:
            last = str(exc)
            if index < max_checks - 1:
                time.sleep(2)
    raise RuntimeError(
        "Новая версия API не подтвердила готовность: " + last
        + ". Проверь systemctl status nyan-wallet."
    )


def restart() -> None:
    proc = subprocess.run(
        ["systemctl", "restart", SERVICE],
        capture_output=True, text=True, timeout=90,
    )
    if proc.returncode:
        raise RuntimeError(
            "Не удалось перезапустить nyan-wallet: "
            + (proc.stderr or proc.stdout)[-700:]
        )


def create_flag() -> None:
    fd = os.open(str(FLAG), os.O_CREAT | os.O_WRONLY, 0o644)
    os.close(fd)
    os.chmod(FLAG, 0o644)


def main() -> None:
    parser = argparse.ArgumentParser(description="Nyan Fortune pause toggle")
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--check", action="store_true")
    modes.add_argument("--pause", action="store_true")
    modes.add_argument("--resume", action="store_true")
    options = parser.parse_args()

    if os.geteuid() != 0:
        raise RuntimeError("Команда предназначена для root на FirstVDS.")
    if not MODULE.is_file():
        raise RuntimeError("Не найден серверный файл " + str(MODULE))
    old = MODULE.read_bytes()
    current_blob = blob(old)
    if current_blob not in (KNOWN_OLD_BLOB, NEW_BLOB):
        raise RuntimeError(
            "Найдено другое содержимое server/fortune.py (git blob "
            + current_blob
            + "). Не перезаписываю локальные изменения."
        )
    print("Серверный файл:", "новый" if current_blob == NEW_BLOB else "старый")
    print("Состояние переключателя:", "Временно недоступно" if FLAG.is_file() else "включено")

    if options.resume:
        if current_blob != NEW_BLOB:
            raise RuntimeError("На сервере ещё нет обновлённого API. Включение отменено.")
        api_ready(3)
        FLAG.unlink(missing_ok=True)
        print("OK: Колесо фортуны снова доступно. Перезапуск не нужен.")
        return

    new = fetch_new_module()
    api_ready(3)  # Confirm the existing service is healthy before touching it.
    if options.check:
        print("OK: проверка пройдена, сервер и файлы не изменены.")
        if current_blob == KNOWN_OLD_BLOB:
            print("Для установки потребуется перезапуск только API Nyan Wallet.")
        return

    if current_blob == NEW_BLOB:
        create_flag()
        print('OK: Колесо фортуны отключено. Сообщение: "Временно недоступно".')
        print("Сервер не перезапускался; остальные разделы не затронуты.")
        return

    backup_dir = ROOT / ".fortune-backups" / (
        "pause-" + dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
    )
    backup_dir.mkdir(mode=0o700, parents=True, exist_ok=False)
    shutil.copy2(MODULE, backup_dir / "fortune.py")
    flag_existed = FLAG.is_file()
    try:
        # Create flag first so all requests processed after restart are paused.
        create_flag()
        atomic_replace(MODULE, new)
        restart()
        api_ready()
    except Exception as exc:
        atomic_replace(MODULE, old)
        if not flag_existed:
            FLAG.unlink(missing_ok=True)
        try:
            restart()
            api_ready()
        except Exception as rollback_exc:
            raise RuntimeError(
                f"Установка не удалась: {exc}. Откат требует внимания: "
                f"{rollback_exc}. Резервная копия: {backup_dir}"
            ) from exc
        raise RuntimeError(
            f"Установка не удалась, исходный модуль восстановлен: {exc}. "
            f"Бэкап: {backup_dir}"
        ) from exc

    print('OK: Колесо фортуны отключено — "Временно недоступно".')
    print("Новые вращения и начисления через колесо заблокированы.")
    print("Пользовательские балансы, предыдущие результаты и остальные игры сохранены.")
    print("Резервная копия:", backup_dir)
    print("Для включения: python3 /root/nyan_fortune_pause.py --resume")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        raise SystemExit("ОШИБКА: " + str(exc)) from exc
