#!/usr/bin/env python3
"""Configure NYAN MAFIA announcement group, without sending any messages.

    python3 /tmp/configure_nyan_mafia_group.py --check
    python3 /tmp/configure_nyan_mafia_group.py --apply
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path("/opt/nyan-wallet")
ENV = ROOT / ".env"
GROUP_ID = "-1004368587366"
NAME = "NYAN_MAFIA_GROUP_ID"
PATTERN = re.compile(r"^\s*(?:export\s+)?NYAN_MAFIA_GROUP_ID\s*=", re.MULTILINE)


def patched(before: str) -> str:
    lines = before.splitlines(keepends=True)
    indices = [i for i, line in enumerate(lines) if PATTERN.match(line)]
    if len(indices) > 1:
        raise RuntimeError("В .env несколько записей NYAN_MAFIA_GROUP_ID: сначала исправь вручную")
    if indices:
        i = indices[0]
        lines[i] = f"{NAME}={GROUP_ID}\n"
    else:
        if lines and not lines[-1].endswith("\n"):
            lines[-1] += "\n"
        lines.append(f"{NAME}={GROUP_ID}\n")
    return "".join(lines)


def active() -> bool:
    return subprocess.run(
        ["systemctl", "is-active", "--quiet", "nyan-wallet"], check=False
    ).returncode == 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    if not ENV.is_file() or ENV.is_symlink():
        raise RuntimeError("Не найден обычный файл /opt/nyan-wallet/.env")
    original = ENV.read_bytes()
    try:
        before = original.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise RuntimeError("Файл .env не в UTF-8") from exc
    after = patched(before).encode("utf-8")
    if not active():
        raise RuntimeError("Сначала проверь работающий сервис nyan-wallet")
    print("NYAN MAFIA → Nyan Games")
    print(f"{NAME}={GROUP_ID}")
    print("Изменений:", "нет" if original == after else "одна настройка группы")
    if args.check:
        print("Проверка завершена. Ничего не изменено и не отправлено.")
        return
    if os.geteuid() != 0:
        raise RuntimeError("Нужны права root")
    if original == after:
        print("ID группы уже сохранён. Сообщений не отправляли.")
        return
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
    backup = ROOT / ".nyan-mafia-backups" / ("env-before-group-" + stamp)
    backup.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ENV, backup)
    fd, temp = tempfile.mkstemp(prefix=".nyan-mafia-env-", dir=ENV.parent)
    try:
        with os.fdopen(fd, "wb") as out:
            out.write(after)
            out.flush()
            os.fsync(out.fileno())
        os.chmod(temp, ENV.stat().st_mode & 0o777)
        os.replace(temp, ENV)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)
    print("Группа сохранена в .env, без перезапуска сервера.")
    print("После следующего restart nyan-wallet настройка вступит в силу.")
    print("Резервная копия:", backup)
    print("Регистрация не открывалась. Сообщения не отправлялись.")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        raise SystemExit("ОШИБКА: " + str(error)) from error
