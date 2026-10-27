#!/usr/bin/env python3
"""Install the curator application on FirstVDS without overwriting local modules.

Requires a prior `git fetch origin main`. Does not touch balances, existing
recruitment tables, Telegram relay worker, or maintenance settings.
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


REVISION = "cddacf32cca024ebdc4c350e2f6ed0e6bfd3b115"
IMPORT_ANCHOR = "from .fortune import register_fortune"
CALL_ANCHOR = "    register_fortune(backend_app.app)"
IMPORT_LINE = "from .curator_recruitment import register_curator_recruitment"
CALL_LINE = "    register_curator_recruitment(backend_app.app)"


def get_source(root: Path) -> bytes:
    proc = subprocess.run(
        ["git", "show", f"{REVISION}:server/curator_recruitment.py"],
        cwd=root, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
    )
    if proc.returncode:
        raise RuntimeError("Ревизия анкеты не найдена. Выполни: git fetch origin main")
    compile(proc.stdout.decode("utf-8"), "server/curator_recruitment.py", "exec")
    return proc.stdout


def patch_init(original: str) -> str:
    result = original
    for anchor, line in ((IMPORT_ANCHOR, IMPORT_LINE), (CALL_ANCHOR, CALL_LINE)):
        if result.count(line) > 1:
            raise RuntimeError(f"Строка дублируется: {line}")
        if line in result:
            continue
        if result.count(anchor) != 1:
            raise RuntimeError(f"Не могу безопасно найти место подключения: {anchor}")
        result = result.replace(anchor + "\n", anchor + "\n" + line + "\n", 1)
    compile(result, "server/__init__.py", "exec")
    return result


def atomic_write(path: Path, content: bytes) -> None:
    temp = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".nyan-curator-", delete=False) as stream:
            temp = Path(stream.name)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        if path.exists():
            os.chmod(temp, path.stat().st_mode & 0o777)
        os.replace(temp, path)
    finally:
        if temp is not None and temp.exists():
            temp.unlink()


def run(root: Path, *, check_only: bool) -> None:
    init = root / "server" / "__init__.py"
    module = root / "server" / "curator_recruitment.py"
    if not (root / "server" / "backend_app.py").is_file() or not init.is_file():
        raise RuntimeError("Запусти из /opt/nyan-wallet")

    source = get_source(root)
    old_init = init.read_text(encoding="utf-8")
    patched_init = patch_init(old_init)
    old_module = module.read_bytes() if module.exists() else None
    if old_module is not None and old_module != source:
        raise RuntimeError("server/curator_recruitment.py уже изменён локально, не перезаписываю")

    needs_init = patched_init != old_init
    needs_module = old_module is None
    print(f"Модуль анкеты: {'установить' if needs_module else 'уже существует'}")
    print(f"Подключение: {'добавить' if needs_init else 'уже выполнено'}")
    print("Балансы, Telegram relay и другие серверные файлы не изменяются")
    if check_only:
        print("OK: сухая проверка, изменений нет")
        return
    if os.geteuid() != 0:
        raise RuntimeError("Нужен запуск от root")
    if not needs_init and not needs_module:
        print("OK: анкета уже установлена")
        return

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
    backup = root / ".nyan-curator-backups" / timestamp
    backup.mkdir(parents=True, exist_ok=False)
    shutil.copy2(init, backup / "__init__.py")
    if old_module is not None:
        shutil.copy2(module, backup / "curator_recruitment.py")
    try:
        if needs_module:
            atomic_write(module, source)
        if needs_init:
            atomic_write(init, patched_init.encode("utf-8"))
        subprocess.run([sys.executable, "-m", "py_compile", str(init), str(module)], check=True)
        subprocess.run(["systemctl", "restart", "nyan-wallet"], check=True)
        subprocess.run(["systemctl", "is-active", "--quiet", "nyan-wallet"], check=True)
    except Exception:
        shutil.copy2(backup / "__init__.py", init)
        if needs_module:
            module.unlink(missing_ok=True)
        elif (backup / "curator_recruitment.py").exists():
            shutil.copy2(backup / "curator_recruitment.py", module)
        subprocess.run(["systemctl", "restart", "nyan-wallet"], check=False)
        print("Ошибка, старые файлы восстановлены", file=sys.stderr)
        raise
    print(f"OK: сервис nyan-wallet работает. Копия: {backup}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Безопасная установка анкеты Nyan Shop")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--check", action="store_true")
    group.add_argument("--install", action="store_true")
    args = parser.parse_args()
    try:
        run(Path.cwd(), check_only=args.check)
    except Exception as exc:
        print(f"ОШИБКА: {exc}", file=sys.stderr)
        sys.exit(1)
