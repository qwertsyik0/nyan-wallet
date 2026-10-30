#!/usr/bin/env python3
"""Safely register the 2026 Nyanik archive in the running FirstVDS backend.

Usage (as root):
  python3 install_nyan_archive_2026.py --revision <40-char-sha> --check
  python3 install_nyan_archive_2026.py --revision <40-char-sha> --apply

No balances, purchases, badges or existing event data are modified.
"""

from __future__ import annotations

import argparse
import datetime
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path


SERVER = Path("/opt/nyan-wallet/server")
REGISTRY = SERVER / "__init__.py"
MODULE = SERVER / "nyan_archive_2026.py"
SERVICE = "nyan-wallet"
RAW = "https://raw.githubusercontent.com/qwertsyik0/nyan-wallet"
IMPORT = b"from .nyan_archive_2026 import register_nyan_archive_2026\n"
CALL = b"    register_nyan_archive_2026(backend_app.app)\n"
IMPORT_ANCHOR = b"from .halloween_2026 import register_halloween_2026\n"
CALL_ANCHOR = b"    register_halloween_2026(backend_app.app)\n"


def command(*args: str) -> str:
    result = subprocess.run(args, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"Не удалось выполнить {args[0]}: {(result.stderr or result.stdout)[-900:]}")
    return result.stdout.strip()


def fetch(revision: str) -> bytes:
    with urllib.request.urlopen(f"{RAW}/{revision}/server/nyan_archive_2026.py", timeout=20) as response:
        if response.status != 200:
            raise RuntimeError(f"Не удалось загрузить модуль: HTTP {response.status}")
        data = response.read(512 * 1024 + 1)
    if not data or len(data) > 512 * 1024:
        raise RuntimeError("Пустой или слишком большой серверный модуль")
    return data


def inject_registration(data: bytes) -> bytes:
    has_import = IMPORT in data
    has_call = CALL in data
    if has_import != has_call:
        raise RuntimeError("Найдена только часть регистрации архива, нужна ручная проверка")
    if has_import:
        return data
    if data.count(IMPORT_ANCHOR) != 1 or data.count(CALL_ANCHOR) != 1:
        raise RuntimeError("Структура server/__init__.py отличается от ожидаемой, остановлено")
    return data.replace(IMPORT_ANCHOR, IMPORT_ANCHOR + IMPORT, 1).replace(
        CALL_ANCHOR, CALL_ANCHOR + CALL, 1
    )


def publish_file(path: Path, content: bytes) -> None:
    fd, temp_path = tempfile.mkstemp(prefix=".nyan-archive-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        os.chmod(temp_path, 0o644)
        os.replace(temp_path, path)
    finally:
        if os.path.exists(temp_path):
            os.unlink(temp_path)


def wait_for_api() -> None:
    last_error = "маршрут не зарегистрирован"
    for _ in range(14):
        try:
            with urllib.request.urlopen("http://127.0.0.1:8000/openapi.json", timeout=3) as response:
                if response.status == 200 and b'"/api/nyan-archive-2026/status"' in response.read():
                    return
        except Exception as exc:
            last_error = str(exc)
        time.sleep(1.5)
    raise RuntimeError("API архива не появился после перезапуска: " + last_error)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--revision", required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if not re.fullmatch(r"[0-9a-f]{40}", args.revision):
        raise RuntimeError("--revision должен быть полным SHA коммита GitHub")
    if os.geteuid() != 0:
        raise RuntimeError("Для установки открой Termius под root")
    if not SERVER.is_dir() or not REGISTRY.is_file():
        raise RuntimeError("Путь /opt/nyan-wallet/server не найден")
    if REGISTRY.is_symlink() or MODULE.is_symlink():
        raise RuntimeError("Обнаружена символическая ссылка вместо модуля, остановлено")
    if command("systemctl", "is-active", SERVICE) != "active":
        raise RuntimeError("Сервис Nyan Wallet неактивен")

    remote = fetch(args.revision)
    current_module = MODULE.read_bytes() if MODULE.exists() else None
    if current_module is not None and current_module != remote:
        raise RuntimeError("Модуль архива уже есть, но отличается от публикуемой версии")

    old_registry = REGISTRY.read_bytes()
    new_registry = inject_registration(old_registry)
    with tempfile.TemporaryDirectory(prefix="nyan-archive-check-") as directory:
        module_path = Path(directory) / "nyan_archive_2026.py"
        module_path.write_bytes(remote)
        registry_path = Path(directory) / "__init__.py"
        registry_path.write_bytes(new_registry)
        command(sys.executable, "-m", "py_compile", str(module_path), str(registry_path))

    print("Модуль:", "уже установлен" if current_module == remote else "готов к установке")
    print("Регистрация:", "уже есть" if old_registry == new_registry else "будет добавлена отдельной строкой")
    if args.check:
        print("Проверка ОК. Сервер не изменён.")
        return

    suffix = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    backups = []
    try:
        for path, before, after in (
            (MODULE, current_module, remote),
            (REGISTRY, old_registry, new_registry),
        ):
            if before == after:
                continue
            backup_path = None
            if before is not None:
                backup_path = path.with_name(path.name + f".before-archive-{suffix}")
                if backup_path.exists():
                    raise RuntimeError("Резервная копия уже существует: " + str(backup_path))
                shutil.copy2(path, backup_path)
            backups.append((path, backup_path))
            publish_file(path, after)
        command("systemctl", "restart", SERVICE)
        wait_for_api()
    except Exception:
        for path, backup in reversed(backups):
            if backup is None:
                path.unlink(missing_ok=True)
            else:
                shutil.copy2(backup, path)
        try:
            command("systemctl", "restart", SERVICE)
        except Exception as exc:
            print("Не удалось восстановить сервис:", exc, file=sys.stderr)
        raise
    print("Установка ОК. /api/nyan-archive-2026/status отвечает.")
    print("Открытие 31 октября в 17:00 МСК; материалы выходят до 23:00 МСК.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("ОШИБКА:", exc, file=sys.stderr)
        sys.exit(1)
