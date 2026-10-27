#!/usr/bin/env python3
"""Safely mute selected owner reward notices on a locally patched FirstVDS server.

Only changes two notification modules, not balances, transaction history,
Telegram relay worker configuration, or any of the site's other features.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path


RELAY_OLD = (
    "    if core.OWNER_TELEGRAM_ID and int(target.telegram_id) != int(core.OWNER_TELEGRAM_ID):"
)
RELAY_NEW = """    # Automatic game rewards go to the recipient, without pinging the owner.
    if (
        core.OWNER_TELEGRAM_ID
        and int(target.telegram_id) != int(core.OWNER_TELEGRAM_ID)
        and operation not in {"daily_task", "achievement", "fortune_spin"}
    ):"""
AUDIT_OLD = "    if not core.OWNER_TELEGRAM_ID:"
AUDIT_NEW = '    if not core.OWNER_TELEGRAM_ID or target.action == "task_approved":'


def patch_relay(source: str) -> str:
    # Also recognize the version already committed to GitHub.
    if (
        'operation not in {"daily_task", "achievement", "fortune_spin"}' in source
        or "operation not in OWNER_SILENT_REWARD_OPERATIONS" in source
    ):
        return source
    if source.count(RELAY_OLD) != 1 or "def _tx_notice(" not in source:
        raise RuntimeError("Не узнаю обработчик владельца в server/telegram_relay.py; не меняю файл")
    patched = source.replace(RELAY_OLD, RELAY_NEW, 1)
    compile(patched, "server/telegram_relay.py", "exec")
    return patched


def patch_audit(source: str) -> str:
    if AUDIT_NEW in source or "target.action in OWNER_SILENT_AUDIT_ACTIONS" in source:
        return source
    if source.count(AUDIT_OLD) != 1 or "def _notify_owner_after_audit_insert(" not in source:
        raise RuntimeError("Не узнаю обработчик аудита в server/instant_notifications.py; не меняю файл")
    patched = source.replace(AUDIT_OLD, AUDIT_NEW, 1)
    compile(patched, "server/instant_notifications.py", "exec")
    return patched


def atomic_write(path: Path, data: bytes) -> None:
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".nyan-notice-", delete=False) as tmp:
            temp_path = Path(tmp.name)
            tmp.write(data)
            tmp.flush()
            os.fsync(tmp.fileno())
        os.chmod(temp_path, path.stat().st_mode & 0o777)
        os.replace(temp_path, path)
    finally:
        if temp_path is not None and temp_path.exists():
            temp_path.unlink()


def run(root: Path, *, check_only: bool) -> None:
    if not (root / "server" / "backend_app.py").is_file():
        raise RuntimeError("Запусти из /opt/nyan-wallet")

    originals: dict[Path, bytes] = {}
    changes: dict[Path, bytes] = {}
    handlers = (
        (root / "server" / "telegram_relay.py", patch_relay),
        (root / "server" / "instant_notifications.py", patch_audit),
    )
    for path, patcher in handlers:
        if not path.is_file():
            raise RuntimeError(f"Нет файла {path.name}; не меняю ничего")
        original = path.read_bytes()
        originals[path] = original
        source = original.decode("utf-8")
        updated = patcher(source)
        compile(updated, str(path), "exec")
        if updated != source:
            changes[path] = updated.encode("utf-8")

    print("Только для владельца: без уведомлений о daily_task, achievement, fortune_spin, task_approved")
    print("Пользовательские сообщения и прочие операции без изменений. Базу и relay-воркер не трогаем.")
    for path, _ in handlers:
        print(f"{path.name}: {'нужен патч' if path in changes else 'уже настроен'}")
    if check_only:
        print("OK: проверка, файлы и сервис не менялись")
        return
    if os.geteuid() != 0:
        raise RuntimeError("Для установки нужен root")
    if not changes:
        print("OK: настройки уже установлены")
        return

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
    backup = root / ".nyan-notification-backups" / stamp
    backup.mkdir(parents=True, exist_ok=False)
    for path, original in originals.items():
        shutil.copy2(path, backup / path.name)
    try:
        for path, content in changes.items():
            atomic_write(path, content)
        subprocess.run([sys.executable, "-m", "py_compile", *map(str, originals)], check=True)
        subprocess.run(["systemctl", "restart", "nyan-wallet"], check=True)
        subprocess.run(["systemctl", "is-active", "--quiet", "nyan-wallet"], check=True)
    except Exception:
        for path in changes:
            shutil.copy2(backup / path.name, path)
        subprocess.run(["systemctl", "restart", "nyan-wallet"], check=False)
        print("Установка не прошла, исходные файлы восстановлены", file=sys.stderr)
        raise

    print(f"OK: бот работает; резервная копия: {backup}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Отключить владельцу мелкие наградные уведомления")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--check", action="store_true")
    group.add_argument("--install", action="store_true")
    args = parser.parse_args()
    try:
        run(Path.cwd(), check_only=args.check)
    except Exception as exc:
        print(f"ОШИБКА: {exc}", file=sys.stderr)
        sys.exit(1)
