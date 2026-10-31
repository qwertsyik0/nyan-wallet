#!/usr/bin/env python3
"""Safely install the Halloween choice API on the running Nyan Wallet FirstVDS.

Run as root with --revision <full GitHub commit SHA> and --check, then --apply.
Never modifies balances or transactions during installation.
"""

from __future__ import annotations

import argparse
import datetime
import json
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
MODULE = SERVER / "halloween_boot_choice_2026.py"
SERVICE = "nyan-wallet"
RAW = "https://raw.githubusercontent.com/qwertsyik0/nyan-wallet"
IMPORT = b"from .halloween_boot_choice_2026 import register_halloween_boot_choice_2026\n"
CALL = b"    register_halloween_boot_choice_2026(backend_app.app)\n"
IMPORT_ANCHOR = b"from .halloween_2026 import register_halloween_2026\n"
CALL_ANCHOR = b"    register_halloween_2026(backend_app.app)\n"


def command(*args: str) -> str:
    process = subprocess.run(args, capture_output=True, text=True, check=False)
    if process.returncode:
        raise RuntimeError(f"Команда {args[0]}: {(process.stderr or process.stdout)[-900:]}")
    return process.stdout.strip()


def fetch(revision: str) -> bytes:
    url = f"{RAW}/{revision}/server/halloween_boot_choice_2026.py"
    with urllib.request.urlopen(url, timeout=25) as response:
        data = response.read(200_001)
        if response.status != 200 or len(data) > 200_000 or not data:
            raise RuntimeError("Не удалось скачать модуль мероприятия")
    return data


def patch_registry(current: bytes) -> bytes:
    has_import, has_call = IMPORT in current, CALL in current
    if has_import != has_call:
        raise RuntimeError("Неполная регистрация Halloween-экрана, остановлено")
    if has_import:
        return current
    if current.count(IMPORT_ANCHOR) != 1 or current.count(CALL_ANCHOR) != 1:
        raise RuntimeError("Не удалось найти безопасную точку подключения модуля")
    return current.replace(IMPORT_ANCHOR, IMPORT_ANCHOR + IMPORT, 1).replace(
        CALL_ANCHOR, CALL_ANCHOR + CALL, 1
    )


def atomic_write(path: Path, content: bytes) -> None:
    fd, temporary = tempfile.mkstemp(prefix=".nyan-halloween-choice-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o644)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def healthcheck() -> None:
    last_error = "Маршрут отсутствует"
    for _ in range(18):
        try:
            with urllib.request.urlopen("http://127.0.0.1:8000/openapi.json", timeout=3) as response:
                paths = json.load(response).get("paths", {})
            if "/api/halloween-boot-2026/status" in paths and "/api/halloween-boot-2026/choose" in paths:
                return
        except Exception as error:
            last_error = str(error)
        time.sleep(1.5)
    raise RuntimeError("Не удалось подтвердить API Halloween: " + last_error)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--revision", required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if not re.fullmatch(r"[a-f0-9]{40}", args.revision):
        raise RuntimeError("Укажи полный SHA коммита GitHub")
    if os.geteuid() != 0:
        raise RuntimeError("Нужен Termius под root")
    if not SERVER.is_dir() or not REGISTRY.is_file() or not (SERVER / "halloween_2026.py").is_file():
        raise RuntimeError("Не найдена ожидаемая структура сервера Nyan Wallet")
    if any(path.is_symlink() for path in (REGISTRY, MODULE)):
        raise RuntimeError("Обнаружена символическая ссылка, установка остановлена")
    if command("systemctl", "is-active", SERVICE) != "active":
        raise RuntimeError("Сервис nyan-wallet не запущен")

    new_module = fetch(args.revision)
    old_module = MODULE.read_bytes() if MODULE.exists() else None
    if old_module is not None and old_module != new_module:
        raise RuntimeError("Серверный модуль изменён. Не перезаписываем без ручной проверки")
    old_registry = REGISTRY.read_bytes()
    new_registry = patch_registry(old_registry)

    with tempfile.TemporaryDirectory(prefix="nyan-halloween-choice-check-") as dirname:
        script = Path(dirname) / "halloween_boot_choice_2026.py"
        registry = Path(dirname) / "__init__.py"
        script.write_bytes(new_module)
        registry.write_bytes(new_registry)
        command(sys.executable, "-m", "py_compile", str(script), str(registry))

    print("Модуль:", "уже установлен" if old_module == new_module else "готов к установке")
    print("Регистрация:", "уже есть" if old_registry == new_registry else "будет добавлена")
    if args.check:
        print("Проверка OK. Балансы и файлы не изменены.")
        return

    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    backups: list[tuple[Path, Path | None]] = []
    try:
        for path, before, after in (
            (MODULE, old_module, new_module),
            (REGISTRY, old_registry, new_registry),
        ):
            if before == after:
                continue
            backup = None
            if before is not None:
                backup = path.with_name(path.name + f".before-halloween-choice-{stamp}")
                if backup.exists():
                    raise RuntimeError("Резервная копия уже существует")
                shutil.copy2(path, backup)
            backups.append((path, backup))
            atomic_write(path, after)
        command("systemctl", "restart", SERVICE)
        healthcheck()
    except Exception:
        for path, backup in reversed(backups):
            if backup is None:
                path.unlink(missing_ok=True)
            else:
                shutil.copy2(backup, path)
        try:
            command("systemctl", "restart", SERVICE)
        except Exception as error:
            print("Не удалось запустить восстановленный сервис:", error, file=sys.stderr)
        raise

    print("Экран Halloween готов. Каждый пользователь может сделать выбор только один раз.")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print("ОШИБКА:", error, file=sys.stderr)
        sys.exit(1)
