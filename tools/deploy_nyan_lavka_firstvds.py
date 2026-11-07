#!/usr/bin/env python3
"""Install only Nyanik's separate shop API on FirstVDS, with rollback.

Download and run:
  python3 deploy_nyan_lavka_firstvds.py --check
  sudo python3 deploy_nyan_lavka_firstvds.py --apply

It never opens the shop, sets stock, edits balances or purchases anything.
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
MODULE_URL = "https://raw.githubusercontent.com/qwertsyik0/nyan-wallet/main/server/nyan_lavka.py"
MODULE_SHA256 = "224bdd438a54fc8bace8042747372c368a12c43fe20f3d80c8309c05b7cb4cbb"
IMPORT_AFTER = "from .nyan_awards_2026 import register_nyan_awards_2026"
IMPORT_NEW = "from .nyan_lavka import register_nyan_lavka"
CALL_AFTER = "    register_nyan_awards_2026(backend_app.app)"
CALL_NEW = "    register_nyan_lavka(backend_app.app)"
EXPECTED_ROUTES = (
    "/api/nyan-lavka/catalog",
    "/api/nyan-lavka/status",
    "/api/nyan-lavka/buy",
    "/api/nyan-lavka/owner/stock",
    "/api/nyan-lavka/owner/open",
    "/api/nyan-lavka/owner/close",
    "/api/nyan-lavka/owner/orders",
    "/api/nyan-lavka/owner/orders/{purchase_id}/redeem",
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
    req = urllib.request.Request(MODULE_URL, headers={"User-Agent": "Nyan-Lavka-Deploy/1.0"})
    with urllib.request.urlopen(req, timeout=25) as response:
        payload = response.read(160_001)
    if len(payload) > 160_000:
        raise RuntimeError("Размер модуля превышает лимит")
    if hashlib.sha256(payload).hexdigest() != MODULE_SHA256:
        raise RuntimeError("Контрольная сумма модуля не совпадает. Установка отменена")
    source = payload.decode("utf-8")
    ast.parse(source, filename="server/nyan_lavka.py")
    if "def register_nyan_lavka(" not in source:
        raise RuntimeError("В модуле не найдена регистрация маршрутов")
    return payload


def replace_atomic(path: Path, payload: bytes) -> None:
    fd, name = tempfile.mkstemp(prefix=".nyan-lavka-", dir=str(path.parent))
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
                print("OK: сервис работает, все маршруты лавки доступны")
                return
            last = "Не все маршруты API зарегистрированы"
        except (OSError, ValueError) as exc:
            last = str(exc)
        time.sleep(2)
    raise RuntimeError("Сервис не прошёл проверку: " + last)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--check", action="store_true", help="Проверить без записи файлов")
    action.add_argument("--apply", action="store_true", help="Установить с резервной копией и откатом")
    parser.add_argument("--root", help="Путь к FastAPI-проекту")
    args = parser.parse_args()

    project = find_project(args.root)
    module_path = project / "server/nyan_lavka.py"
    init_path = project / "server/__init__.py"
    before_init = init_path.read_bytes()
    after_init = patch_initializer(before_init.decode("utf-8")).encode("utf-8")
    before_module = module_path.read_bytes() if module_path.exists() else None
    after_module = download_module()
    changes = [name for name, changed in (
        ("server/__init__.py", before_init != after_init),
        ("server/nyan_lavka.py", before_module != after_module),
    ) if changed]
    print("Проект:", project)
    print("Обновления:", ", ".join(changes) if changes else "нет")
    if args.check:
        print("OK: проверка завершена без изменений на VPS")
        return 0
    if os.geteuid() != 0:
        raise RuntimeError("Для установки нужен sudo")
    if command("systemctl", "is-active", SERVICE, check=False).stdout.strip() != "active":
        raise RuntimeError("Сервис сейчас не active, установка отменена")
    if not changes:
        validate_service()
        print("Лавка уже установлена")
        return 0

    backup = project / ".nyan-lavka-backups" / time.strftime("%Y%m%d-%H%M%S")
    backup.mkdir(parents=True, exist_ok=False)
    shutil.copy2(init_path, backup / "__init__.py")
    if before_module is not None:
        shutil.copy2(module_path, backup / "nyan_lavka.py")
    print("Резервная копия:", backup)
    try:
        replace_atomic(module_path, after_module)
        replace_atomic(init_path, after_init)
        command("systemctl", "restart", SERVICE)
        validate_service()
    except BaseException:
        print("Ошибка запуска! Восстанавливаю файлы предыдущей версии", file=sys.stderr)
        replace_atomic(init_path, before_init)
        if before_module is None:
            module_path.unlink(missing_ok=True)
        else:
            replace_atomic(module_path, before_module)
        rollback = command("systemctl", "restart", SERVICE, check=False)
        if rollback.returncode:
            print("ВНИМАНИЕ: старый сервис не перезапустился:", rollback.stderr[-1200:], file=sys.stderr)
        raise
    print("УСПЕХ: API лавки установлен. Балансы не тронуты, товары не открыты, остатки = 0")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as error:
        print("ОШИБКА:", error, file=sys.stderr)
        sys.exit(1)
