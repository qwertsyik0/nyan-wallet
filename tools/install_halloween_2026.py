#!/usr/bin/env python3
"""Install Nyan Halloween event on FirstVDS without overwriting unrelated changes.

As root, run: python3 install_halloween_2026.py --check, then --apply.
The installer never grants lapcoins. It only registers the event API and tables.
"""

from __future__ import annotations

import argparse
import datetime
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path


REPO = "https://raw.githubusercontent.com/qwertsyik0/nyan-wallet"
REVISION = "05037b6463d7e51f4f5949ebe5e82913eb486180"
BASE_REVISION = "ec195cd37545b4f5e930fa21bb2df4f9585ee721"
SERVER = Path("/opt/nyan-wallet/server")
SERVICE = "nyan-wallet"
EVENT = SERVER / "halloween_2026.py"
REGISTRY = SERVER / "__init__.py"
ACHIEVEMENTS = SERVER / "achievements.py"


def download(rev: str, path: str) -> bytes:
    with urllib.request.urlopen(f"{REPO}/{rev}/{path}", timeout=20) as response:
        if response.status != 200:
            raise RuntimeError(f"Не удалось получить {path}: HTTP {response.status}")
        data = response.read()
    if not data:
        raise RuntimeError(f"Пустой файл {path}")
    return data


def run(*argv: str) -> str:
    proc = subprocess.run(argv, capture_output=True, text=True, check=False)
    if proc.returncode:
        raise RuntimeError(f"Ошибка {argv[0]}: {(proc.stderr or proc.stdout)[-1400:]}")
    return proc.stdout.strip()


def add_registration(original: bytes) -> bytes:
    import_line = b"from .halloween_2026 import register_halloween_2026\n"
    call_line = b"    register_halloween_2026(backend_app.app)\n"
    existing_import = import_line in original
    existing_call = call_line in original
    if existing_import != existing_call:
        raise RuntimeError("Частичная регистрация события в __init__.py, требуется ручная проверка")
    if existing_import:
        return original
    import_anchor = b"from .fortune import register_fortune\n"
    call_anchor = b"    register_fortune(backend_app.app)\n"
    if original.count(import_anchor) != 1 or original.count(call_anchor) != 1:
        raise RuntimeError("Неизвестная структура server/__init__.py, ничего не изменено")
    return original.replace(import_anchor, import_anchor + import_line, 1).replace(
        call_anchor, call_anchor + call_line, 1
    )


def health() -> None:
    error = "неизвестно"
    for _ in range(12):
        try:
            with urllib.request.urlopen("http://127.0.0.1:8000/openapi.json", timeout=3) as result:
                content = result.read()
                if result.status == 200 and b'"/api/halloween-2026/status"' in content:
                    return
                error = "в API отсутствует /api/halloween-2026/status"
        except Exception as exc:
            error = str(exc)
        time.sleep(2)
    raise RuntimeError("Сервер не подтвердил новую страницу API: " + error)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    options = parser.add_mutually_exclusive_group(required=True)
    options.add_argument("--check", action="store_true")
    options.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if os.geteuid() != 0:
        raise RuntimeError("Запусти от root через Termius")
    if not REGISTRY.is_file() or not ACHIEVEMENTS.is_file():
        raise RuntimeError("Не найдены серверные модули Nyan Wallet")
    if any(path.is_symlink() for path in (REGISTRY, ACHIEVEMENTS, EVENT)):
        raise RuntimeError("Обнаружена символическая ссылка на серверный модуль")
    if run("systemctl", "is-active", SERVICE) != "active":
        raise RuntimeError("Сервис nyan-wallet неактивен, установка остановлена")

    new_event = download(REVISION, "server/halloween_2026.py")
    new_achievements = download(REVISION, "server/achievements.py")
    baseline_achievements = download(BASE_REVISION, "server/achievements.py")
    current_event = EVENT.read_bytes() if EVENT.exists() else None
    if current_event is not None and current_event != new_event:
        raise RuntimeError("Существующий halloween_2026.py отличается; ничего не изменено")
    current_registry = REGISTRY.read_bytes()
    target_registry = add_registration(current_registry)
    current_achievements = ACHIEVEMENTS.read_bytes()
    update_achievements = current_achievements in (baseline_achievements, new_achievements)

    with tempfile.TemporaryDirectory(prefix="nyan-halloween-verify-") as tmp:
        p = Path(tmp) / "halloween_2026.py"
        p.write_bytes(new_event)
        run(sys.executable, "-m", "py_compile", str(p))
        q = Path(tmp) / "__init__.py"
        q.write_bytes(target_registry)
        run(sys.executable, "-m", "py_compile", str(q))

    print("Событие:", "уже установлено" if current_event == new_event else "готово к установке")
    print("Регистрация API:", "есть" if current_registry == target_registry else "добавится без удаления других строк")
    print("Значок в профиле:", "обновится" if update_achievements else "пока пропущен: серверная версия отличается")
    if args.check:
        print("Проверка ОК. Сервер и данные не изменены.")
        return

    changes = [(EVENT, current_event, new_event), (REGISTRY, current_registry, target_registry)]
    if update_achievements:
        changes.append((ACHIEVEMENTS, current_achievements, new_achievements))
    modified: list[tuple[Path, Path | None]] = []
    suffix = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    try:
        for path, previous, target in changes:
            if previous == target:
                continue
            backup = None
            if previous is not None:
                backup = path.with_name(path.name + f".before-halloween-{suffix}")
                if backup.exists():
                    raise RuntimeError(f"Резервная копия уже существует: {backup}")
                shutil.copy2(path, backup)
                print("Резервная копия:", backup)
            modified.append((path, backup))
            path.write_bytes(target)
        run("systemctl", "restart", SERVICE)
        health()
    except Exception:
        for path, backup in reversed(modified):
            if backup is None:
                if path.exists():
                    path.unlink()
            else:
                shutil.copy2(backup, path)
        try:
            run("systemctl", "restart", SERVICE)
        except Exception as exc:
            print("Ошибка восстановления сервиса:", exc, file=sys.stderr)
        print("Изменения модуля отменены, резервные копии сохранены", file=sys.stderr)
        raise
    print("Установка ОК. Маршрут /api/halloween-2026/status доступен.")
    print("Событие откроется 31 октября в 00:00 МСК; до этого награды не начисляются.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("ОШИБКА:", exc, file=sys.stderr)
        sys.exit(1)
