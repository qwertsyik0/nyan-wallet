#!/usr/bin/env python3
"""Install only the Telegram relay on a locally customized FirstVDS backend.

Does not perform git pull, touch balances, replace locally customized quote or
election modules, or print any secrets. --check is read-only. --apply preserves
all replaced files and automatically rolls them back if validation fails.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path


RAW = "https://raw.githubusercontent.com/qwertsyik0/nyan-wallet"
ROOT = Path("/opt/nyan-wallet")
ENV_FILE = Path("/etc/nyan-wallet-relay.env")
DROPIN = Path("/etc/systemd/system/nyan-wallet.service.d/telegram-relay.conf")
DROPIN_CONTENT = b"[Service]\nEnvironmentFile=/etc/nyan-wallet-relay.env\n"
MODULES = (
    "server/advanced_features.py",
    "server/extended_features.py",
    "server/instant_notifications.py",
    "server/promo_notify.py",
    "server/referral_fix.py",
    "server/telegram_relay.py",
)
IMPORT_ANCHOR = "from .advanced_features import register_advanced_features\n"
IMPORT_LINE = "from .telegram_relay import register_telegram_relay\n"
REGISTER_ANCHOR = "    register_advanced_features(backend_app.app)\n"
REGISTER_LINE = "    register_telegram_relay(backend_app.app)\n"


def command(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(args, text=True, capture_output=True, check=check)


def patch_init(text: str) -> str:
    if IMPORT_LINE not in text:
        if text.count(IMPORT_ANCHOR) != 1:
            raise RuntimeError("Не найден точный якорь импорта; установка остановлена")
        text = text.replace(IMPORT_ANCHOR, IMPORT_ANCHOR + IMPORT_LINE, 1)
    if REGISTER_LINE not in text:
        if text.count(REGISTER_ANCHOR) != 1:
            raise RuntimeError("Не найден точный якорь регистрации; установка остановлена")
        text = text.replace(REGISTER_ANCHOR, REGISTER_ANCHOR + REGISTER_LINE, 1)
    ast.parse(text, filename="server/__init__.py")
    return text


def download(ref: str, name: str) -> bytes:
    request = urllib.request.Request(
        f"{RAW}/{ref}/{name}",
        headers={"User-Agent": "NyanWalletTelegramRelaySafeInstall/1.0"},
    )
    with urllib.request.urlopen(request, timeout=25) as response:
        raw = response.read(150001)
    if len(raw) > 150000:
        raise RuntimeError(f"Файл превышает лимит: {name}")
    ast.parse(raw.decode("utf-8"), filename=name)
    return raw


def atomic_write(path: Path, data: bytes, mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=".nyan-relay-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temp, mode)
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def load_secret(contents: bytes | None) -> str:
    if contents is None:
        return secrets.token_hex(32)
    for line in contents.decode("utf-8").splitlines():
        if line.startswith("NYAN_TELEGRAM_RELAY_SECRET="):
            value = line.partition("=")[2].strip().strip('"').strip("'")
            if len(value) < 32:
                raise RuntimeError("Существующий секрет слишком короткий")
            return value
    raise RuntimeError("Файл relay.env существует без нужного ключа; не перезаписываю")


def wait_ready(secret: str) -> None:
    reason = "сервис не готов"
    for _ in range(15):
        if command("systemctl", "is-active", "nyan-wallet", check=False).stdout.strip() != "active":
            reason = "systemd сообщает не active"
            time.sleep(2)
            continue
        try:
            with urllib.request.urlopen("http://127.0.0.1:8000/api/health", timeout=3) as response:
                health = json.load(response)
            with urllib.request.urlopen("http://127.0.0.1:8000/openapi.json", timeout=3) as response:
                paths = json.load(response)["paths"]
            request = urllib.request.Request(
                "http://127.0.0.1:8000/api/internal/telegram-relay/status",
                headers={"X-Nyan-Relay-Secret": secret},
            )
            with urllib.request.urlopen(request, timeout=3) as response:
                relay = json.load(response)
            if (health.get("ok") and relay.get("ok") and
                    "/api/internal/telegram-relay/pull" in paths and
                    "/api/internal/telegram-relay/ack" in paths):
                print("OK: FastAPI, новые маршруты и очередь PostgreSQL доступны")
                return
            reason = "проверка маршрутов не пройдена"
        except Exception as exc:
            reason = type(exc).__name__
        time.sleep(2)
    raise RuntimeError("Проверка после рестарта не пройдена: " + reason)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--check", action="store_true")
    action.add_argument("--apply", action="store_true")
    parser.add_argument("--rev", required=True, help="Pinned GitHub commit SHA (40 hex chars)")
    args = parser.parse_args()

    if not re.fullmatch(r"[0-9a-f]{40}", args.rev):
        raise RuntimeError("--rev должен содержать полный SHA коммита")
    if not (ROOT / "server/backend_app.py").is_file():
        raise RuntimeError("Не найден Nyan Wallet в /opt/nyan-wallet")
    init_path = ROOT / "server/__init__.py"
    next_files: dict[Path, bytes] = {
        ROOT / name: download(args.rev, name) for name in MODULES
    }
    next_files[init_path] = patch_init(init_path.read_text(encoding="utf-8")).encode("utf-8")
    changed = [path for path, data in next_files.items()
               if not path.exists() or path.read_bytes() != data]
    print("Изменятся файлы:", ", ".join(str(p.relative_to(ROOT)) for p in changed) or "нет")
    print("server/__init__.py: локальные дополнения сохраняются")
    if args.check:
        print("OK: сухая проверка, никаких изменений")
        return
    if os.geteuid() != 0:
        raise RuntimeError("Установка требует root на FirstVDS")
    if command("systemctl", "is-active", "nyan-wallet", check=False).stdout.strip() != "active":
        raise RuntimeError("Сервис не active; не начинаю установку")
    if DROPIN.exists() and DROPIN.read_bytes() != DROPIN_CONTENT:
        raise RuntimeError("telegram-relay.conf уже существует с другим содержимым")

    tracked = changed + [ENV_FILE, DROPIN]
    original = {path: path.read_bytes() if path.exists() else None for path in tracked}
    secret = load_secret(original[ENV_FILE])
    backup = ROOT / ".nyan-telegram-relay-backups" / time.strftime("%Y%m%d-%H%M%S")
    backup.mkdir(parents=True, mode=0o700, exist_ok=False)
    os.chmod(backup, 0o700)
    for path, contents in original.items():
        if contents is not None:
            relative = (str(path.relative_to(ROOT)) if path.is_relative_to(ROOT)
                        else "systemd/" + path.name)
            destination = backup / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, destination)
    print("Резервная копия:", backup)

    try:
        for path in changed:
            current_mode = (path.stat().st_mode & 0o777) if path.exists() else 0o644
            atomic_write(path, next_files[path], current_mode)
        if original[ENV_FILE] is None:
            atomic_write(ENV_FILE, ("NYAN_TELEGRAM_RELAY_SECRET=" + secret + "\n").encode(), 0o600)
        if original[DROPIN] is None:
            atomic_write(DROPIN, DROPIN_CONTENT, 0o644)
        command("systemctl", "daemon-reload")
        command("systemctl", "restart", "nyan-wallet")
        wait_ready(secret)
    except BaseException:
        for path, contents in original.items():
            if contents is None:
                path.unlink(missing_ok=True)
            else:
                mode = (path.stat().st_mode & 0o777) if path.exists() else (0o600 if path == ENV_FILE else 0o644)
                atomic_write(path, contents, mode)
        command("systemctl", "daemon-reload", check=False)
        command("systemctl", "restart", "nyan-wallet", check=False)
        print("ОШИБКА: выполнен автоматический откат файлов и конфигурации", file=sys.stderr)
        raise

    print("УСТАНОВКА ПОДГОТОВЛЕНА: новые уведомления сохраняются в очереди")
    print("СЕКРЕТ ДЛЯ SprintHost хранится в /etc/nyan-wallet-relay.env")
    print("Не присылай его в чат. Пока отправщик SprintHost не запущен, сообщения ожидают в очереди.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("ОШИБКА:", exc, file=sys.stderr)
        sys.exit(1)
