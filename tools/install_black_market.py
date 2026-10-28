#!/usr/bin/env python3
"""Install the Nyan black-market server module on FirstVDS safely.

Files must first be downloaded from the pinned GitHub revision to /tmp.
The script preserves existing modules, creates a timestamped backup, and
rolls back its changed files if the Nyan Wallet API cannot start.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path("/opt/nyan-wallet")
SOURCE = Path("/tmp/nyan-black-market-module.py")
ASSET_NAMES = ("black-market-midnight.webp", "black-market-dark-nyanik.webp")
ASSET_SHA256 = {
    "black-market-midnight.webp": "baa88e97dada49cfb0ee577c6ee39cd8dd7122cf30fda438116652cf25e84f50",
    "black-market-dark-nyanik.webp": "7e88b0639f80f291bb541c87f79338081fdeef474a6628e4aaa04efa585aa4be",
}
IMPORT_ANCHOR = "from .fortune import register_fortune"
CALL_ANCHOR = "    register_fortune(backend_app.app)"
IMPORT_LINE = "from .black_market import register_black_market"
CALL_LINE = "    register_black_market(backend_app.app)"


def checked_init(original: str) -> str:
    output = original
    for anchor, line in ((IMPORT_ANCHOR, IMPORT_LINE), (CALL_ANCHOR, CALL_LINE)):
        if output.count(line) > 1:
            raise RuntimeError(f"Дублирование строки подключения: {line}")
        if line in output:
            continue
        if output.count(anchor) != 1:
            raise RuntimeError(f"Не найдено однозначное место подключения: {anchor}")
        output = output.replace(anchor + "\n", anchor + "\n" + line + "\n", 1)
    compile(output, "server/__init__.py", "exec")
    return output


def atomic_copy(source: Path, destination: Path) -> None:
    temp = None
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        with tempfile.NamedTemporaryFile(dir=destination.parent, prefix=".nyan-market-", delete=False) as stream:
            temp = Path(stream.name)
            with source.open("rb") as reader:
                shutil.copyfileobj(reader, stream)
            stream.flush()
            os.fsync(stream.fileno())
        # Uvicorn's service user must be able to read Python source and images.
        os.chmod(temp, 0o644)
        os.replace(temp, destination)
    finally:
        if temp is not None and temp.exists():
            temp.unlink()


def atomic_text(text: str, destination: Path) -> None:
    temp = None
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=destination.parent, prefix=".nyan-market-", delete=False) as out:
        temp = Path(out.name)
        out.write(text)
        out.flush()
        os.fsync(out.fileno())
    try:
        os.chmod(temp, destination.stat().st_mode & 0o777)
        os.replace(temp, destination)
    finally:
        if temp is not None and temp.exists():
            temp.unlink()


def check_inputs() -> tuple[str, str, list[tuple[Path, Path]]]:
    init = ROOT / "server/__init__.py"
    module = ROOT / "server/black_market.py"
    if not init.is_file() or not (ROOT / "server/backend_app.py").is_file():
        raise RuntimeError("Не найден проект /opt/nyan-wallet")
    if not SOURCE.is_file():
        raise RuntimeError(f"Не найден скачанный модуль {SOURCE}")
    data = SOURCE.read_bytes()
    compile(data, str(module), "exec")
    if module.is_file() and module.read_bytes() != data:
        raise RuntimeError(f"{module} уже отличается от скачанного модуля; отменяю перезапись")
    old_init = init.read_text(encoding="utf-8")
    patched_init = checked_init(old_init)
    entries = [(SOURCE, module)]
    for name in ASSET_NAMES:
        src = Path("/tmp") / name
        dst = ROOT / "assets/wallet-skins" / name
        if not src.is_file():
            raise RuntimeError(f"Не найден фон {src}")
        data = src.read_bytes()
        if len(data) > 2_000_000 or data[:4] != b"RIFF" or data[8:12] != b"WEBP":
            raise RuntimeError(f"Некорректный фон {src}")
        if hashlib.sha256(data).hexdigest() != ASSET_SHA256[name]:
            raise RuntimeError(f"Контрольная сумма изображения не совпадает: {src}")
        if dst.is_file() and dst.read_bytes() != data:
            raise RuntimeError(f"{dst} изменён, не перезаписываю")
        entries.append((src, dst))
    return old_init, patched_init, entries


def wait_for_api() -> bool:
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        if subprocess.run(["systemctl", "is-active", "--quiet", "nyan-wallet"], check=False).returncode == 0:
            try:
                with urllib.request.urlopen("http://127.0.0.1:8000/api/health", timeout=3) as response:
                    if response.status == 200:
                        return True
            except Exception:
                pass
        time.sleep(2)
    return False


def install() -> None:
    old_init, patched_init, entries = check_inputs()
    print("Проверка файлов: OK")
    print("Балансы и существующие модули Nyan Wallet не меняются")
    if args.check:
        print("Сухая проверка завершена. Покупки и открытие рынка не выполнялись")
        return
    if os.geteuid() != 0:
        raise RuntimeError("Для установки запусти скрипт через sudo")
    if patched_init == old_init and all(dst.is_file() for _, dst in entries):
        print("Рынок уже подключён; файлы совпадают")
        return

    backup = ROOT / ".nyan-black-market-backups" / datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
    backup.mkdir(parents=True)
    saved: list[tuple[Path, Path | None]] = []
    init = ROOT / "server/__init__.py"
    try:
        # Record the pre-install state for every file we might alter.
        for _, destination in entries:
            previous = backup / destination.relative_to(ROOT)
            if destination.is_file():
                previous.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(destination, previous)
                saved.append((destination, previous))
            else:
                saved.append((destination, None))
        old_init_path = backup / "server/__init__.py"
        old_init_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(init, old_init_path)
        for source, destination in entries:
            if not destination.is_file():
                atomic_copy(source, destination)
        if patched_init != old_init:
            atomic_text(patched_init, init)
        subprocess.run([sys.executable, "-m", "py_compile", str(init), str(ROOT / "server/black_market.py")], check=True)
        subprocess.run(["systemctl", "restart", "nyan-wallet"], check=True)
        if not wait_for_api():
            raise RuntimeError("Nyan Wallet не ответил на /api/health после перезапуска")
    except Exception:
        shutil.copy2(old_init_path, init)
        for destination, previous in reversed(saved):
            if previous is None:
                if destination.is_file():
                    destination.unlink()
            else:
                shutil.copy2(previous, destination)
        subprocess.run(["systemctl", "restart", "nyan-wallet"], check=False)
        print(f"Установка отменена, прежние файлы восстановлены: {backup}", file=sys.stderr)
        raise
    print("OK: Nyan Wallet работает. Чёрный рынок установлен и пока ЗАКРЫТ")
    print(f"Резервная копия: {backup}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Безопасная установка Чёрного рынка Няника")
    choice = parser.add_mutually_exclusive_group(required=True)
    choice.add_argument("--check", action="store_true")
    choice.add_argument("--install", action="store_true")
    args = parser.parse_args()
    try:
        install()
    except Exception as exc:
        print(f"ОШИБКА: {exc}", file=sys.stderr)
        sys.exit(1)
