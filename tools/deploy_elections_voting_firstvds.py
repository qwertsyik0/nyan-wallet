#!/usr/bin/env python3
"""Safely install *only* Nyan Elections voting on FirstVDS.

Run as root on the FirstVDS machine, not on SprintHost:
  python3 tools/deploy_elections_voting_firstvds.py --check
  python3 tools/deploy_elections_voting_firstvds.py --apply

No bot token is read; the script never starts voting, changes ballots,
touches balances, or changes maintenance-mode state.
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

SERVICE = "nyan-wallet"
PINNED_CODE_COMMIT = "a3a112e111942423c198065c5cf34e5ddcf2a33b"
REMOTE_MODULE_URL = (
    "https://raw.githubusercontent.com/qwertsyik0/nyan-wallet/"
    + PINNED_CODE_COMMIT + "/server/elections_voting.py"
)
OLD_IMPORT = "from .elections import register_elections"
ADD_IMPORT = "from .elections_voting import register_elections_voting"
OLD_CALL = "    register_elections(backend_app.app)"
ADD_CALL = "    register_elections_voting(backend_app.app)"
REQUIRED_ROUTES = (
    "/api/elections/voting/status",
    "/api/elections/voting/cast",
    "/api/elections/owner/voting/open",
    "/api/elections/owner/voting/close",
    "/api/elections/owner/voting/archive",
)


def command(*parts: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(parts, text=True, capture_output=True, check=check)


def find_project(explicit: str | None) -> Path:
    if explicit:
        candidates = [Path(explicit)]
    else:
        result = command("systemctl", "show", SERVICE,
                         "-p", "WorkingDirectory", "--value")
        working_directory = result.stdout.strip()
        candidates = [Path(working_directory)] if working_directory and working_directory != "/" else []
        candidates.extend([
            Path("/root/nyan-wallet"),
            Path("/opt/nyan-wallet"),
            Path("/srv/nyan-wallet"),
            Path("/home/nyanteam/nyan-wallet"),
        ])
    for item in candidates:
        path = item.expanduser().resolve()
        if (path / "server/elections.py").is_file() and (path / "server/__init__.py").is_file():
            return path
    raise RuntimeError(
        "Не нашёл установленный backend. Запусти с --root /полный/путь/к/проекту. "
        "Проверь путь: systemctl show nyan-wallet -p WorkingDirectory --value"
    )


def patch_initializer(current: str) -> str:
    if ADD_IMPORT not in current:
        if current.count(OLD_IMPORT + "\n") != 1:
            raise RuntimeError("Невозможно безопасно добавить импорт выборов")
        current = current.replace(OLD_IMPORT + "\n", OLD_IMPORT + "\n" + ADD_IMPORT + "\n", 1)
    if ADD_CALL not in current:
        if current.count(OLD_CALL + "\n") != 1:
            raise RuntimeError("Невозможно безопасно добавить регистрацию выборов")
        current = current.replace(OLD_CALL + "\n", OLD_CALL + "\n" + ADD_CALL + "\n", 1)
    ast.parse(current, filename="server/__init__.py")
    return current


def download_module() -> str:
    request = urllib.request.Request(
        REMOTE_MODULE_URL, headers={"User-Agent": "Nyan-Elections-Safe-Deploy/1.0"}
    )
    with urllib.request.urlopen(request, timeout=25) as response:
        code = response.read(128_001)
    if len(code) > 128_000:
        raise RuntimeError("Файл голосования превышает допустимый размер")
    content = code.decode("utf-8")
    ast.parse(content, filename="server/elections_voting.py")
    if "def register_elections_voting(" not in content:
        raise RuntimeError("В скачанном коде нет функции регистрации")
    if '"/owner/voting/archive"' not in content:
        raise RuntimeError("В скачанном коде нет функции архивирования")
    return content


def write_atomic(target: Path, content: bytes) -> None:
    fd, name = tempfile.mkstemp(prefix=".nyan-election-", dir=str(target.parent))
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        if target.exists():
            os.chmod(name, target.stat().st_mode & 0o777)
        else:
            os.chmod(name, 0o644)
        os.replace(name, target)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def validate_service() -> None:
    active = command("systemctl", "is-active", SERVICE, check=False)
    if active.stdout.strip() != "active":
        raise RuntimeError("Сервис nyan-wallet не active: " + active.stdout.strip())
    last = ""
    for _ in range(15):
        try:
            with urllib.request.urlopen("http://127.0.0.1:8000/api/health", timeout=3) as result:
                health = json.load(result)
            with urllib.request.urlopen("http://127.0.0.1:8000/openapi.json", timeout=3) as result:
                paths = json.load(result).get("paths", {})
            if health.get("ok") is True and all(p in paths for p in REQUIRED_ROUTES):
                print("OK: health + 5 маршрутов голосования в OpenAPI")
                return
            last = "Маршруты голосования ещё не зарегистрированы"
        except (urllib.error.URLError, OSError, ValueError) as exc:
            last = str(exc)
        time.sleep(2)
    raise RuntimeError("API не прошёл проверку после обновления: " + last)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    options = parser.add_mutually_exclusive_group(required=True)
    options.add_argument("--check", action="store_true", help="Проверить без изменений")
    options.add_argument("--apply", action="store_true", help="Установить и проверить")
    parser.add_argument("--root", help="Полный путь проекта FastAPI, если автоопределение не удалось")
    args = parser.parse_args()

    project = find_project(args.root)
    init_path = project / "server/__init__.py"
    module_path = project / "server/elections_voting.py"
    current_init = init_path.read_text(encoding="utf-8")
    next_init = patch_initializer(current_init)
    remote_module = download_module()
    old_module = module_path.read_bytes() if module_path.exists() else None
    new_module = remote_module.encode("utf-8")
    changes = [
        name for name, different in (
            ("server/__init__.py", next_init != current_init),
            ("server/elections_voting.py", old_module != new_module),
        ) if different
    ]
    print("Проект:", project)
    print("Режим:", "ПРОВЕРКА" if args.check else "УСТАНОВКА")
    print("Файлы к изменению:", ", ".join(changes) if changes else "нет")

    if args.check:
        print("OK: безопасная проверка завершена. Сервис не перезапускался.")
        return 0
    if os.geteuid() != 0:
        raise RuntimeError("Для установки требуется root на FirstVDS")

    # Always check service is currently healthy enough before touching it.
    if command("systemctl", "is-active", SERVICE, check=False).stdout.strip() != "active":
        raise RuntimeError("Сервис сейчас не active. Установка отменена.")

    if not changes:
        validate_service()
        print("Уже установлено, изменений нет.")
        return 0

    backup = project / ".nyan-election-backups" / time.strftime("%Y%m%d-%H%M%S")
    backup.mkdir(parents=True, exist_ok=False)
    shutil.copy2(init_path, backup / "__init__.py")
    if old_module is not None:
        shutil.copy2(module_path, backup / "elections_voting.py")
    print("Резервная копия:", backup)

    try:
        write_atomic(module_path, new_module)
        write_atomic(init_path, next_init.encode("utf-8"))
        command("systemctl", "restart", SERVICE)
        validate_service()
    except BaseException:
        print("ОШИБКА: возвращаю исходные файлы и перезапускаю старый сервис.", file=sys.stderr)
        write_atomic(init_path, (backup / "__init__.py").read_bytes())
        if old_module is None:
            module_path.unlink(missing_ok=True)
        else:
            write_atomic(module_path, (backup / "elections_voting.py").read_bytes())
        recovery = command("systemctl", "restart", SERVICE, check=False)
        if recovery.returncode != 0:
            print("ВНИМАНИЕ: откат файлов выполнен, но старый сервис не запустился!",
                  file=sys.stderr)
            print(recovery.stderr[-1200:], file=sys.stderr)
        raise
    print("УСПЕХ: модуль голосования установлен; голосование НЕ открывалось.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as error:
        print("ОШИБКА:", error, file=sys.stderr)
        sys.exit(1)
