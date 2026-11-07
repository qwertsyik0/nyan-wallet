#!/usr/bin/env python3
"""Install only the NYAN AWARDS 2026 FastAPI module on FirstVDS, with rollback.

On the VPS, download this script and run:
  python3 deploy_nyan_awards_firstvds.py --check
  sudo python3 deploy_nyan_awards_firstvds.py --apply

It does not alter balances, ballots, prize inventory, bot tokens or other modules.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

SERVICE = "nyan-wallet"
MODULE_URL = "https://raw.githubusercontent.com/qwertsyik0/nyan-wallet/main/server/nyan_awards_2026.py"
MODULE_SHA256 = "3ee7daaef3e13b29419c74cb5a9425230870d7650200cfa14fd9852aa89400fa"
IMPORT_AFTER = "from .nyan_future_vote import register_nyan_future_vote"
IMPORT_NEW = "from .nyan_awards_2026 import register_nyan_awards_2026"
CALL_AFTER = "    register_nyan_future_vote(backend_app.app)"
CALL_NEW = "    register_nyan_awards_2026(backend_app.app)"
EXPECTED_ROUTES = (
    "/api/nyan-awards/status",
    "/api/nyan-awards/nominate",
    "/api/nyan-awards/confirm",
    "/api/nyan-awards/vote",
    "/api/nyan-awards/official/status",
    "/api/nyan-awards/official/vote",
    "/api/owner/nyan-awards/official/tally",
    "/api/owner/nyan-awards/candidates",
    "/api/owner/nyan-awards/finalist",
    "/api/owner/nyan-awards/winner",
    "/api/owner/nyan-awards/random-voter/draw",
)


def command(*parts: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(parts, text=True, capture_output=True, check=check)


def find_project(root: str | None) -> Path:
    candidates = [Path(root)] if root else []
    if not root:
        cwd = command("systemctl", "show", SERVICE, "-p", "WorkingDirectory", "--value").stdout.strip()
        if cwd and cwd != "/":
            candidates.append(Path(cwd))
        candidates.extend(Path(x) for x in (
            "/opt/nyan-wallet", "/root/nyan-wallet", "/srv/nyan-wallet", "/home/nyanteam/nyan-wallet"
        ))
    for candidate in candidates:
        candidate = candidate.resolve()
        if (candidate / "server/backend_app.py").is_file() and (candidate / "server/__init__.py").is_file():
            return candidate
    raise RuntimeError("Не найден FastAPI-проект. Укажи --root /полный/путь/к/nyan-wallet")


def patch_initializer(source: str) -> str:
    for anchor, addition in ((IMPORT_AFTER, IMPORT_NEW), (CALL_AFTER, CALL_NEW)):
        if addition not in source:
            if source.count(anchor + "\n") != 1:
                raise RuntimeError(f"Не найден безопасный якорь для {addition}")
            source = source.replace(anchor + "\n", anchor + "\n" + addition + "\n", 1)
    ast.parse(source, filename="server/__init__.py")
    return source


def download_module() -> bytes:
    request = urllib.request.Request(MODULE_URL, headers={"User-Agent": "Nyan-Awards-Deploy/1.0"})
    with urllib.request.urlopen(request, timeout=25) as response:
        payload = response.read(160_001)
    if len(payload) > 160_000:
        raise RuntimeError("Размер модуля превышает лимит")
    if hashlib.sha256(payload).hexdigest() != MODULE_SHA256:
        raise RuntimeError("Контрольная сумма не совпадает. Не устанавливаю изменённую версию")
    source = payload.decode("utf-8")
    ast.parse(source, filename="server/nyan_awards_2026.py")
    if "def register_nyan_awards_2026(" not in source:
        raise RuntimeError("Модуль не содержит регистрацию маршрутов")
    return payload


def replace_atomic(path: Path, payload: bytes) -> None:
    fd, name = tempfile.mkstemp(prefix=".nyan-awards-", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(name, (path.stat().st_mode & 0o777) if path.exists() else 0o644)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def validate_service() -> None:
    last = ""
    for _ in range(12):
        active = command("systemctl", "is-active", SERVICE, check=False).stdout.strip()
        if active != "active":
            last = f"systemd: {active}"
            time.sleep(2)
            continue
        try:
            with urllib.request.urlopen("http://127.0.0.1:8000/api/health", timeout=3) as response:
                health = json.load(response)
            with urllib.request.urlopen("http://127.0.0.1:8000/openapi.json", timeout=3) as response:
                paths = json.load(response).get("paths", {})
            if health.get("ok") is True and all(route in paths for route in EXPECTED_ROUTES):
                print("OK: сервис работает, все маршруты NYAN AWARDS доступны")
                return
            last = "Не все маршруты API зарегистрированы"
        except (OSError, ValueError) as exc:
            last = str(exc)
        time.sleep(2)
    raise RuntimeError("Сервис не прошёл проверку: " + last)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--check", action="store_true", help="Только проверить установку")
    action.add_argument("--apply", action="store_true", help="Обновить и проверить с резервной копией")
    parser.add_argument("--root", help="Путь к FastAPI-проекту")
    args = parser.parse_args()

    project = find_project(args.root)
    module_path = project / "server/nyan_awards_2026.py"
    init_path = project / "server/__init__.py"
    before_init = init_path.read_bytes()
    after_init = patch_initializer(before_init.decode("utf-8")).encode("utf-8")
    before_module = module_path.read_bytes() if module_path.exists() else None
    after_module = download_module()
    changes = [name for name, changed in (
        ("server/__init__.py", before_init != after_init),
        ("server/nyan_awards_2026.py", before_module != after_module),
    ) if changed]
    print("Проект:", project)
    print("Обновления:", ", ".join(changes) if changes else "нет")
    if args.check:
        print("OK: проверка завершена без записи файлов и перезапуска")
        return 0
    if os.geteuid() != 0:
        raise RuntimeError("Для установки нужен sudo на FirstVDS")
    if command("systemctl", "is-active", SERVICE, check=False).stdout.strip() != "active":
        raise RuntimeError("Сервис сейчас не active. Установка отменена")
    if not changes:
        validate_service()
        print("Версия уже установлена")
        return 0

    backup = project / ".nyan-awards-backups" / time.strftime("%Y%m%d-%H%M%S")
    backup.mkdir(parents=True, exist_ok=False)
    shutil.copy2(init_path, backup / "__init__.py")
    if before_module is not None:
        shutil.copy2(module_path, backup / "nyan_awards_2026.py")
    print("Резервная копия:", backup)
    try:
        replace_atomic(module_path, after_module)
        replace_atomic(init_path, after_init)
        command("systemctl", "restart", SERVICE)
        validate_service()
    except BaseException:
        print("Ошибка проверки. Восстанавливаю предыдущую версию!", file=sys.stderr)
        replace_atomic(init_path, before_init)
        if before_module is None:
            module_path.unlink(missing_ok=True)
        else:
            replace_atomic(module_path, before_module)
        rollback = command("systemctl", "restart", SERVICE, check=False)
        if rollback.returncode:
            print("ВНИМАНИЕ: старый сервис не перезапустился:", rollback.stderr[-1200:], file=sys.stderr)
        raise
    print("УСПЕХ: NYAN AWARDS установлен. Балансы и призы не изменялись")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as error:
        print("ОШИБКА:", error, file=sys.stderr)
        sys.exit(1)
