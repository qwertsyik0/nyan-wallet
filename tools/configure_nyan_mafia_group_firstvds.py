#!/usr/bin/env python3
"""Configure Nyan Games as the NYAN MAFIA announcement group via systemd.

Works even if /opt/nyan-wallet/.env does not exist.

  python3 /tmp/configure_nyan_mafia_group.py --check
  python3 /tmp/configure_nyan_mafia_group.py --apply

Does not send any Telegram message or open registration.
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import shutil
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path("/opt/nyan-wallet")
SERVICE = "nyan-wallet"
GROUP_ID = "-1004368587366"
CONFIG_DIR = Path("/etc/nyan-wallet")
ENV_FILE = CONFIG_DIR / "nyan-mafia-group.env"
DROPIN_DIR = Path("/etc/systemd/system/nyan-wallet.service.d")
DROPIN_FILE = DROPIN_DIR / "90-nyan-mafia-group.conf"
ENV_CONTENT = f"NYAN_MAFIA_GROUP_ID={GROUP_ID}\n".encode("utf-8")
DROPIN_CONTENT = (
    "[Service]\n"
    f"EnvironmentFile={ENV_FILE}\n"
).encode("utf-8")


def command(*argv: str) -> str:
    result = subprocess.run(argv, capture_output=True, text=True, timeout=70, check=False)
    if result.returncode:
        raise RuntimeError((result.stderr or result.stdout or "команда завершилась с ошибкой")[-900:])
    return result.stdout.strip()


def read_original(path: Path) -> bytes | None:
    if path.is_symlink():
        raise RuntimeError("Безопасность: символическая ссылка: " + str(path))
    if not path.exists():
        return None
    if not path.is_file():
        raise RuntimeError("Ожидался обычный файл: " + str(path))
    return path.read_bytes()


def atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=".nyan-mafia-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp, 0o644)
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def check_running() -> None:
    if command("systemctl", "is-active", SERVICE) != "active":
        raise RuntimeError("Сервис nyan-wallet не активен")


def health() -> None:
    last_error = "нет ответа"
    for _ in range(14):
        try:
            check_running()
            for route in ("status", "messages"):
                req = urllib.request.Request("http://127.0.0.1:8000/api/nyan-mafia/" + route)
                try:
                    urllib.request.urlopen(req, timeout=4)
                    raise RuntimeError("API Mafia разрешает запрос без Telegram")
                except urllib.error.HTTPError as error:
                    if error.code != 401:
                        raise RuntimeError(f"API {route}: HTTP {error.code}") from error
            return
        except Exception as error:
            last_error = str(error)
            time.sleep(2)
    raise RuntimeError("после перезапуска API не прошёл проверку: " + last_error)


def verify_environment() -> None:
    pid_text = command("systemctl", "show", SERVICE, "--property=MainPID", "--value")
    pid = int(pid_text)
    if pid <= 0:
        raise RuntimeError("у службы нет MainPID")
    env_path = Path(f"/proc/{pid}/environ")
    values = env_path.read_bytes().split(b"\x00")
    target = ENV_CONTENT.strip()
    if target not in values:
        raise RuntimeError("NYAN_MAFIA_GROUP_ID не попал в окружение процесса сервера")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    check_running()
    current_env = read_original(ENV_FILE)
    current_dropin = read_original(DROPIN_FILE)
    changes = [
        (ENV_FILE, current_env, ENV_CONTENT),
        (DROPIN_FILE, current_dropin, DROPIN_CONTENT),
    ]
    changes = [(p, before, after) for p, before, after in changes if before != after]

    print("NYAN MAFIA: группа Nyan Games", GROUP_ID)
    if changes:
        for path, _, _ in changes:
            print("подготовить:", path)
    else:
        print("файлы конфигурации уже подготовлены")
    if args.check:
        print("проверка завершена: ничего не изменено, сообщений нет")
        return
    if os.geteuid() != 0:
        raise RuntimeError("для --apply нужны права root")

    if not changes:
        try:
            verify_environment()
            health()
            print("готово: группа уже настроена и API защищён")
            return
        except Exception:
            print("проверяю применение готовых параметров после перезапуска")

    backup = ROOT / ".nyan-mafia-backups" / (
        "group-systemd-" + dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
    )
    backup.mkdir(mode=0o700, parents=True, exist_ok=False)
    for path, prior, _ in changes:
        if prior is not None:
            shutil.copy2(path, backup / path.name)

    try:
        for path, _, after in changes:
            atomic_write(path, after)
        command("systemctl", "daemon-reload")
        command("systemctl", "restart", SERVICE)
        health()
        verify_environment()
    except Exception:
        for path, prior, _ in reversed(changes):
            if prior is None:
                path.unlink(missing_ok=True)
            else:
                atomic_write(path, prior)
        command("systemctl", "daemon-reload")
        command("systemctl", "restart", SERVICE)
        raise

    print("OK: NYAN MAFIA направлена в Nyan Games")
    print("резервная копия:", backup)
    print("регистрация не открывалась, сообщений Telegram не отправлялось")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        raise SystemExit("ОШИБКА: " + str(error)) from error
