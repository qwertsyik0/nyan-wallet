#!/usr/bin/env python3
"""Install the standalone NYAN SPY game API on FirstVDS.

  sudo python3 /tmp/install_nyan_spy_firstvds.py --check
  sudo python3 /tmp/install_nyan_spy_firstvds.py --apply

Neither mode opens registration or sends a Telegram group message.
Only the verified owner pressing "Открыть набор" in the game Mini App
creates a round and queues the invitation for the existing Telegram relay.
"""

from __future__ import annotations

import argparse
import ast
import datetime as dt
import os
import shutil
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path


RAW = "https://raw.githubusercontent.com/qwertsyik0/nyan-wallet/main/server/nyan_spy.py"
ROOT = Path("/opt/nyan-wallet")
SERVICE = "nyan-wallet"
IMPORT = "from .nyan_spy import register_nyan_spy"
REGISTER = "    register_nyan_spy(backend_app.app)"


def command(*args: str) -> str:
    result = subprocess.run(args, capture_output=True, text=True, timeout=50, check=False)
    if result.returncode:
        raise RuntimeError((result.stderr or result.stdout or "Ошибка выполнения").strip()[-1000:])
    return result.stdout.strip()


def fetch_module() -> bytes:
    request = urllib.request.Request(RAW, headers={"User-Agent": "Nyan-Spy-Installer/1"})
    with urllib.request.urlopen(request, timeout=20) as response:
        body = response.read(110_001)
    if not body or len(body) > 110_000:
        raise RuntimeError("Некорректный размер файла NYAN SPY")
    text = body.decode("utf-8")
    ast.parse(text, filename="server/nyan_spy.py")
    for path in ('"/api/nyan-spy/status"', '"/api/owner/nyan-spy/close"'):
        if path not in text:
            raise RuntimeError("Загружен неожиданный серверный модуль")
    return body


def patch_registry(before: bytes) -> bytes:
    text = before.decode("utf-8")
    has_import = IMPORT in text
    has_register = REGISTER in text
    if has_import != has_register:
        raise RuntimeError("Частичное подключение модуля: проверь server/__init__.py вручную")
    if has_import:
        return before
    import_anchor = "from .nyan_future_vote import register_nyan_future_vote\n"
    register_anchor = "    register_nyan_future_vote(backend_app.app)\n"
    if text.count(import_anchor) != 1 or text.count(register_anchor) != 1:
        raise RuntimeError("Не найдены безопасные точки подключения NYAN SPY")
    text = text.replace(import_anchor, import_anchor + IMPORT + "\n", 1)
    text = text.replace(register_anchor, register_anchor + REGISTER + "\n", 1)
    ast.parse(text, filename="server/__init__.py")
    return text.encode("utf-8")


def write_atomic(target: Path, body: bytes) -> None:
    fd, tmp = tempfile.mkstemp(prefix=".nyan-spy-", dir=target.parent)
    try:
        with os.fdopen(fd, "wb") as output:
            output.write(body)
            output.flush()
            os.fsync(output.fileno())
        os.chmod(tmp, target.stat().st_mode & 0o777 if target.exists() else 0o644)
        os.replace(tmp, target)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def health_check() -> None:
    error = "маршруты ещё не доступны"
    for _ in range(14):
        try:
            if command("systemctl", "is-active", SERVICE) != "active":
                raise RuntimeError("служба запускается")
            with urllib.request.urlopen("http://127.0.0.1:8000/openapi.json", timeout=3) as response:
                body = response.read().decode("utf-8")
            if '"/api/nyan-spy/status"' in body and '"/api/owner/nyan-spy/close"' in body:
                return
            error = "маршруты ещё не появились"
        except Exception as exc:
            error = str(exc)
        time.sleep(2)
    raise RuntimeError("NYAN SPY API не подтвердил запуск: " + error)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if os.geteuid() != 0:
        raise RuntimeError("Запусти с sudo")
    registry = ROOT / "server/__init__.py"
    module = ROOT / "server/nyan_spy.py"
    if not registry.is_file() or not (ROOT / "server/backend_app.py").is_file():
        raise RuntimeError("Не найден Nyan Wallet на VPS")
    if registry.is_symlink() or module.is_symlink():
        raise RuntimeError("Не изменяю символические ссылки")
    if command("systemctl", "is-active", SERVICE) != "active":
        raise RuntimeError("Служба nyan-wallet не запущена")

    body = fetch_module()
    old_module = module.read_bytes() if module.exists() else None
    old_registry = registry.read_bytes()
    new_registry = patch_registry(old_registry)
    changes = [(module, old_module, body), (registry, old_registry, new_registry)]
    changes = [(p, old, new) for p, old, new in changes if old != new]
    print("Проверено. Изменений:", len(changes))
    for path, _, _ in changes:
        print(" ", path.relative_to(ROOT))
    if args.check:
        print("Проверка завершена. Ничего не изменено и не отправлено в Telegram.")
        return
    if not changes:
        health_check()
        print("NYAN SPY уже установлен, API отвечает.")
        return

    backup = ROOT / ".nyan-spy-backups" / dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
    backup.mkdir(parents=True, exist_ok=False)
    for path, old, _ in changes:
        if old is not None:
            copy = backup / path.relative_to(ROOT)
            copy.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, copy)
    try:
        for path, _, new in changes:
            write_atomic(path, new)
        command("systemctl", "restart", SERVICE)
        health_check()
    except Exception:
        for path, old, _ in reversed(changes):
            if old is None:
                path.unlink(missing_ok=True)
            else:
                write_atomic(path, old)
        command("systemctl", "restart", SERVICE)
        raise
    print("NYAN SPY установлен. API отвечает. Регистрация НЕ открыта.")
    print("Резервные копии:", backup)
    print("Публикации в Telegram не отправлялись.")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        raise SystemExit("ОШИБКА: " + str(error)) from error
