#!/usr/bin/env python3
"""Safely guarantee NYAN MAFIA owner receives the mafia role next round.

Only server/nyan_mafia.py is replaced. Existing wallet database, game rounds,
balances, bot configuration and Telegram messages remain untouched.
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
import urllib.request
from pathlib import Path

ROOT = Path("/opt/nyan-wallet")
TARGET = ROOT / "server/nyan_mafia.py"
SERVICE = "nyan-wallet"
SOURCE = "https://raw.githubusercontent.com/qwertsyik0/nyan-wallet/main/server/nyan_mafia.py"
ALLOWED_OLD_BLOBS = {
    "314df9c8c530a79ff9b8271dd6d31af8f76b017e",  # original Mafia API
    "1c71a73da86759c14477769ca8b575979648cdb5",  # post-test fixes
}
NEW_BLOB = "b02df7bc7893bf903465cbf61b4fb7143817ae2a"
NEEDED = (
    "def _eliminated_announcement(",
    'result["revealed_roles"]',
    'result["last_elimination"]',
    '"message": saved_response',
    '"/api/internal/nyan-mafia/open"',
    'owner_id = core.OWNER_TELEGRAM_ID',
    'roles[owner_idx], roles[mafia_idx] = roles[mafia_idx], roles[owner_idx]',
)


def git_blob(data: bytes) -> str:
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()


def run(*args: str) -> str:
    result = subprocess.run(args, capture_output=True, text=True, timeout=50)
    if result.returncode:
        raise RuntimeError((result.stderr or result.stdout or str(args))[-1200:])
    return result.stdout.strip()


def download() -> bytes:
    request = urllib.request.Request(SOURCE, headers={"User-Agent": "NYAN-MAFIA-Feedback-Updater"})
    with urllib.request.urlopen(request, timeout=22) as resp:
        data = resp.read(120001)
    if not (25000 <= len(data) <= 120000):
        raise RuntimeError("Получен некорректный размер модуля")
    if git_blob(data) != NEW_BLOB:
        raise RuntimeError("Контрольная сумма нового модуля не совпала. Установка отменена.")
    source = data.decode("utf-8")
    ast.parse(source, filename="server/nyan_mafia.py")
    if not all(item in source for item in NEEDED):
        raise RuntimeError("Не найдены необходимые исправления в новой версии")
    return data


def atomic_write(path: Path, content: bytes) -> None:
    fd, temp = tempfile.mkstemp(prefix=".nyan-mafia-feedback-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temp, path.stat().st_mode & 0o777)
        os.replace(temp, path)
    finally:
        Path(temp).unlink(missing_ok=True)


def healthy() -> None:
    last = "ожидание запуска"
    for attempt in range(16):
        try:
            if run("systemctl", "is-active", SERVICE) != "active":
                raise RuntimeError("systemd ещё не active")
            with urllib.request.urlopen("http://127.0.0.1:8000/openapi.json", timeout=4) as resp:
                spec = json.loads(resp.read(1024 * 1024))
            paths = spec.get("paths", {})
            for key in (
                "/api/nyan-mafia/status",
                "/api/nyan-mafia/messages",
                "/api/internal/nyan-mafia/open",
            ):
                if key not in paths:
                    raise RuntimeError("маршрут API отсутствует: " + key)
            return
        except Exception as exc:
            last = str(exc)
            time.sleep(1)
    raise RuntimeError("после перезапуска API не восстановился: " + last)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="проверить обновление без установки")
    parser.add_argument("--apply", action="store_true", help="установить с резервной копией")
    args = parser.parse_args()
    if args.check == args.apply:
        parser.error("выбери --check или --apply")
    if os.geteuid() != 0:
        raise RuntimeError("Нужен root на FirstVDS")
    if not TARGET.is_file():
        raise RuntimeError("Модуль NYAN MAFIA не установлен: " + str(TARGET))
    old = TARGET.read_bytes()
    old_blob = git_blob(old)
    new = download()
    if old_blob == NEW_BLOB:
        healthy()
        print("OK: постоянная роль мафии для владельца уже настроена.")
        return
    if old_blob not in ALLOWED_OLD_BLOBS:
        raise RuntimeError(
            "Серверный модуль отличается от проверенной версии. "
            "Чтобы не потерять локальные изменения, установка остановлена. "
            f"Текущий git blob: {old_blob}"
        )
    if args.check:
        print("OK: настройка роли владельца совместима с сервером.")
        print("Режим проверки: файлов и настроек не изменяли.")
        return
    backup_dir = ROOT / ".nyan-mafia-backups" / (
        "feedback-" + dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
    )
    backup_dir.mkdir(parents=True, exist_ok=False)
    shutil.copy2(TARGET, backup_dir / "nyan_mafia.py")
    try:
        atomic_write(TARGET, new)
        run("systemctl", "restart", SERVICE)
        healthy()
    except Exception as exc:
        atomic_write(TARGET, old)
        try:
            run("systemctl", "restart", SERVICE)
            healthy()
        except Exception as rollback:
            raise RuntimeError(
                f"Обновление не удалось: {exc}. Откат также потребовал внимания: {rollback}. "
                f"Бэкап: {backup_dir}"
            ) from exc
        raise RuntimeError(f"Установка отменена, старая версия восстановлена: {exc}") from exc
    print("OK: владелец при участии гарантированно получит роль мафии со следующего раунда.")
    print("Резервная копия:", backup_dir)
    print("Регистрация не открывалась. В Telegram ничего не отправлялось.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        raise SystemExit("ОШИБКА: " + str(exc)) from exc
