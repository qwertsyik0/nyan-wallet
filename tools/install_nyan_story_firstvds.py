#!/usr/bin/env python3
"""Safely install only the NYAN GAMES horror signup backend on FirstVDS.

Run on the API VPS (without a git pull):
  sudo python3 /tmp/install_nyan_story_firstvds.py --check
  sudo python3 /tmp/install_nyan_story_firstvds.py --apply

The installer preserves other locally modified modules and never opens a round.
"""

from __future__ import annotations

import argparse
import ast
import datetime as dt
import hashlib
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


ROOT = Path("/opt/nyan-wallet")
SERVICE = "nyan-wallet"
MODULE_URL = (
    "https://raw.githubusercontent.com/qwertsyik0/nyan-wallet/"
    "77e9dc9f2c12b257ff9c8fe6d8aa187111eec9f8/server/nyan_story_signup.py"
)
MODULE_SHA256 = "9c00c185ad46541b87021ad57db666d9b18d237b7480c9516de80237238a977a"
IMPORT = "from .nyan_story_signup import register_nyan_story_signup"
REGISTER = "    register_nyan_story_signup(backend_app.app)"
ANCHORS = (
    ("from .nyan_spy import register_nyan_spy", "    register_nyan_spy(backend_app.app)"),
    ("from .telegram_relay import register_telegram_relay", "    register_telegram_relay(backend_app.app)"),
)
ROUTES = (
    "/api/nyan-story/status", "/api/nyan-story/join",
    "/api/internal/nyan-story/open", "/api/internal/nyan-story/close",
)


def command(*args: str, check: bool = True) -> str:
    result = subprocess.run(args, text=True, capture_output=True, check=False, timeout=40)
    if check and result.returncode:
        raise RuntimeError((result.stderr or result.stdout or "ошибка команды")[-1200:])
    return result.stdout.strip()


def download_module() -> bytes:
    request = urllib.request.Request(MODULE_URL, headers={"User-Agent": "Nyan-Story-Install/1"})
    with urllib.request.urlopen(request, timeout=25) as response:
        content = response.read(110_001)
    if not content or len(content) > 110_000:
        raise RuntimeError("неверный размер модуля регистрации")
    if hashlib.sha256(content).hexdigest() != MODULE_SHA256:
        raise RuntimeError("контрольная сумма модуля не совпадает; установка отменена")
    source = content.decode("utf-8")
    ast.parse(source, filename="server/nyan_story_signup.py")
    if not all(route in source for route in ROUTES):
        raise RuntimeError("в загруженном модуле отсутствуют необходимые маршруты")
    return content


def patch_registry(content: bytes) -> bytes:
    source = content.decode("utf-8")
    if source.count(IMPORT) != source.count(REGISTER):
        raise RuntimeError("регистрация NYAN STORY подключена частично; нужен ручной осмотр")
    if source.count(IMPORT) > 1:
        raise RuntimeError("обнаружено дублирование импорта NYAN STORY")
    if IMPORT in source:
        return content

    for import_anchor, call_anchor in ANCHORS:
        if source.count(import_anchor + "\n") != 1 or source.count(call_anchor + "\n") != 1:
            continue
        source = source.replace(import_anchor + "\n", import_anchor + "\n" + IMPORT + "\n", 1)
        source = source.replace(call_anchor + "\n", call_anchor + "\n" + REGISTER + "\n", 1)
        ast.parse(source, filename="server/__init__.py")
        return source.encode("utf-8")
    raise RuntimeError("безопасные точки подключения не найдены; файл __init__.py не изменён")


def atomic_write(path: Path, content: bytes) -> None:
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".nyan-story-")
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, path.stat().st_mode & 0o777 if path.exists() else 0o644)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def check_live() -> None:
    last = ""
    for _ in range(12):
        if command("systemctl", "is-active", SERVICE, check=False) != "active":
            last = "служба не активна"
            time.sleep(2)
            continue
        try:
            with urllib.request.urlopen("http://127.0.0.1:8000/openapi.json", timeout=3) as response:
                paths = json.load(response).get("paths", {})
            if all(route in paths for route in ROUTES):
                # An untrusted HTTP call must not accidentally open registration.
                request = urllib.request.Request(
                    "http://127.0.0.1:8000/api/nyan-story/status", method="GET"
                )
                try:
                    urllib.request.urlopen(request, timeout=3)
                except urllib.error.HTTPError as exc:
                    if exc.code in (401, 403):
                        return
                    raise RuntimeError(f"status endpoint вернул HTTP {exc.code}") from exc
                raise RuntimeError("API регистрации открыл данные без Telegram-подписи")
            last = "не появились все маршруты регистрации"
        except Exception as exc:
            last = str(exc)
        time.sleep(2)
    raise RuntimeError("после запуска API не прошёл проверку: " + last)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    registry = ROOT / "server/__init__.py"
    module = ROOT / "server/nyan_story_signup.py"
    relay = ROOT / "server/telegram_relay.py"
    if not all(p.is_file() for p in (registry, relay, ROOT / "server/backend_app.py")):
        raise RuntimeError("не найдены необходимые файлы API Nyan Wallet")
    if registry.is_symlink() or module.is_symlink():
        raise RuntimeError("символические ссылки не изменяю")
    if command("systemctl", "is-active", SERVICE) != "active":
        raise RuntimeError("служба nyan-wallet не активна")
    service_directory = command("systemctl", "show", SERVICE, "-p", "WorkingDirectory", "--value")
    if Path(service_directory).resolve() != ROOT.resolve():
        raise RuntimeError("рабочая папка сервиса отличается от /opt/nyan-wallet")

    fresh_module = download_module()
    old_module = module.read_bytes() if module.exists() else None
    old_registry = registry.read_bytes()
    fresh_registry = patch_registry(old_registry)
    changes = [item for item in (
        (module, old_module, fresh_module),
        (registry, old_registry, fresh_registry),
    ) if item[1] != item[2]]
    print("проект:", ROOT)
    print("изменятся только:")
    for path, _, _ in changes:
        print(" -", path.relative_to(ROOT))
    if args.check:
        print("проверено: файлы и база не изменены, бот не запускался")
        return
    if os.geteuid() != 0:
        raise RuntimeError("для установки нужен root/sudo")
    if not changes:
        check_live()
        print("модуль уже установлен, API отвечает")
        return

    backup = ROOT / ".nyan-story-backups" / dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
    backup.mkdir(parents=True, exist_ok=False)
    for path, original, _ in changes:
        if original is not None:
            saved = backup / path.relative_to(ROOT)
            saved.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, saved)
    try:
        for path, _, updated in changes:
            atomic_write(path, updated)
        command("systemctl", "restart", SERVICE)
        check_live()
    except BaseException:
        print("ошибка: возвращаю прежние файлы и перезапускаю службу", file=sys.stderr)
        for path, original, _ in reversed(changes):
            if original is None:
                path.unlink(missing_ok=True)
            else:
                atomic_write(path, original)
        result = command("systemctl", "restart", SERVICE, check=False)
        if result != "":
            print("результат перезапуска:", result, file=sys.stderr)
        raise
    print("API NYAN STORY установлен; все маршруты отвечают")
    print("резервная копия:", backup)
    print("регистрация НЕ открыта, Telegram-сообщения не отправлялись")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        raise SystemExit("ОШИБКА: " + str(error)) from error
