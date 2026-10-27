#!/usr/bin/env python3
"""Deploy only Nyan Fortune onto a server with locally patched backend modules.

Intentionally does not run git pull, overwrite untracked project modules, touch
the database directly, or disable maintenance mode.
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


REVISION = "9d9c211553c82dd2ee5d073cc7c3db7b83450f7b"
IMPORT_ANCHOR = "from .lottery import register_lottery"
CALL_ANCHOR = "    register_lottery(backend_app.app)"
IMPORT_LINE = "from .fortune import register_fortune"
CALL_LINE = "    register_fortune(backend_app.app)"


def git_fortune_source(root: Path) -> bytes:
    proc = subprocess.run(
        ["git", "show", f"{REVISION}:server/fortune.py"],
        cwd=root, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
    )
    if proc.returncode:
        raise RuntimeError("Коммит фортуны не найден. Сначала выполни: git fetch origin main")
    compile(proc.stdout.decode("utf-8"), "server/fortune.py", "exec")
    return proc.stdout


def patch_init(original: str) -> str:
    result = original
    for anchor, line in [(IMPORT_ANCHOR, IMPORT_LINE), (CALL_ANCHOR, CALL_LINE)]:
        if result.count(line) > 1:
            raise RuntimeError(f"Дублируется строка: {line}")
        if line in result:
            continue
        if result.count(anchor) != 1:
            raise RuntimeError(f"Нужная точка подключения отсутствует или повторяется: {anchor}")
        result = result.replace(anchor + "\n", anchor + "\n" + line + "\n", 1)
    compile(result, "server/__init__.py", "exec")
    return result


def atomic_write(path: Path, content: bytes, *, mode: int = 0o644) -> None:
    name = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".fortune-", delete=False) as out:
            name = out.name
            out.write(content)
            out.flush()
            os.fsync(out.fileno())
        os.chmod(name, mode)
        os.replace(name, path)
    finally:
        if name and os.path.exists(name):
            os.unlink(name)


def install(root: Path, *, check_only: bool) -> None:
    init_path = root / "server" / "__init__.py"
    fortune_path = root / "server" / "fortune.py"
    if not (root / "server" / "backend_app.py").is_file() or not init_path.is_file():
        raise RuntimeError("Запусти установщик из /opt/nyan-wallet")

    fortune_source = git_fortune_source(root)
    original = init_path.read_text(encoding="utf-8")
    updated = patch_init(original)
    old_fortune = fortune_path.read_bytes() if fortune_path.exists() else None
    if old_fortune is not None and old_fortune != fortune_source:
        raise RuntimeError("server/fortune.py уже существует с другим содержимым. Не перезаписываю его.")

    needs_init = updated != original
    needs_fortune = old_fortune is None
    print(f"Ревизия: {REVISION[:12]}")
    print(f"Новый модуль: {'добавить' if needs_fortune else 'уже установлен'}")
    print(f"Подключение: {'добавить 2 строки' if needs_init else 'уже выполнено'}")
    print("Остальные файлы, база и технические работы не затрагиваются.")
    if check_only:
        print("OK: сухая проверка, ничего не изменено")
        return

    if os.geteuid() != 0:
        raise RuntimeError("Для установки требуется запуск от root")
    if not needs_init and not needs_fortune:
        print("OK: фортуна уже установлена")
        return

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    backup = root / ".nyan-fortune-backups" / timestamp
    backup.mkdir(parents=True, exist_ok=False)
    shutil.copy2(init_path, backup / "__init__.py")
    if old_fortune is not None:
        shutil.copy2(fortune_path, backup / "fortune.py")

    try:
        if needs_fortune:
            atomic_write(fortune_path, fortune_source)
        if needs_init:
            atomic_write(init_path, updated.encode("utf-8"), mode=init_path.stat().st_mode & 0o777)
        subprocess.run([sys.executable, "-m", "py_compile", str(fortune_path), str(init_path)], check=True)
        subprocess.run(["systemctl", "restart", "nyan-wallet"], check=True)
        subprocess.run(["systemctl", "is-active", "--quiet", "nyan-wallet"], check=True)
    except Exception:
        print("Установка не прошла проверку, возвращаю исходные файлы…", file=sys.stderr)
        shutil.copy2(backup / "__init__.py", init_path)
        if needs_fortune:
            fortune_path.unlink(missing_ok=True)
        elif (backup / "fortune.py").exists():
            shutil.copy2(backup / "fortune.py", fortune_path)
        subprocess.run(["systemctl", "restart", "nyan-wallet"], check=False)
        raise

    print(f"OK: сервис nyan-wallet активен. Резервная копия: {backup}")
    print("Проверь страницу /fortune.html после отключения режима техработ.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Точечная безопасная установка фортуны")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--check", action="store_true", help="сухая проверка")
    group.add_argument("--install", action="store_true", help="установить и перезапустить")
    arguments = parser.parse_args()
    try:
        install(Path.cwd(), check_only=arguments.check)
    except Exception as error:
        print(f"ОШИБКА: {error}", file=sys.stderr)
        sys.exit(1)
