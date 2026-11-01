#!/usr/bin/env python3
"""Install only the NYAN FUTURE poll API on the FirstVDS wallet backend.

  sudo python3 install_nyan_future_vote_firstvds.py --check
  sudo python3 install_nyan_future_vote_firstvds.py --apply

The installer does not publish to Telegram, alter existing balances, or change
other wallet features. The API itself credits a verified user on their vote.
"""

from __future__ import annotations

import argparse
import ast
import datetime as dt
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path


RAW = "https://raw.githubusercontent.com/qwertsyik0/nyan-wallet/main/server/nyan_future_vote.py"
ROOT = Path("/opt/nyan-wallet")
SERVICE = "nyan-wallet"
IMPORT = "from .nyan_future_vote import register_nyan_future_vote"
REGISTER = "    register_nyan_future_vote(backend_app.app)"


def command(*args: str) -> str:
    result = subprocess.run(args, capture_output=True, text=True, timeout=55)
    if result.returncode:
        raise RuntimeError((result.stderr or result.stdout or "Команда завершилась с ошибкой").strip()[-1200:])
    return result.stdout.strip()


def fetch_module() -> bytes:
    request = urllib.request.Request(RAW, headers={"User-Agent": "Nyan-Future-Vote-Installer/1"})
    with urllib.request.urlopen(request, timeout=20) as response:
        body = response.read(90_001)
    if not body or len(body) > 90_000:
        raise RuntimeError("Некорректный размер модуля голосования")
    text = body.decode("utf-8")
    ast.parse(text, filename="server/nyan_future_vote.py")
    if '"/api/nyan-future-vote/submit"' not in text:
        raise RuntimeError("Не найден ожидаемый маршрут голосования")
    return body


def patch_registry(source: bytes) -> bytes:
    text = source.decode("utf-8")
    has_import = IMPORT in text
    has_register = REGISTER in text
    if has_import != has_register:
        raise RuntimeError("Обнаружена частичная регистрация: требуется ручная проверка")
    if has_import:
        return source

    import_anchor = "from .wallet_survey import register_wallet_survey\n"
    register_anchor = "    register_quote_reflection(backend_app.app)\n"
    if text.count(import_anchor) != 1 or text.count(register_anchor) != 1:
        raise RuntimeError("Не найдены безопасные места для подключения голосования")
    text = text.replace(import_anchor, import_anchor + IMPORT + "\n", 1)
    text = text.replace(register_anchor, register_anchor + REGISTER + "\n", 1)
    ast.parse(text, filename="server/__init__.py")
    return text.encode("utf-8")


def write_atomic(target: Path, body: bytes) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, path = tempfile.mkstemp(prefix=".nyan-future-", dir=target.parent)
    try:
        with os.fdopen(fd, "wb") as file:
            file.write(body)
            file.flush()
            os.fsync(file.fileno())
        os.chmod(path, target.stat().st_mode & 0o777 if target.exists() else 0o644)
        os.replace(path, target)
    finally:
        if os.path.exists(path):
            os.unlink(path)


def health_check() -> None:
    path = '"/api/nyan-future-vote/submit"'
    error = ""
    for _ in range(12):
        try:
            if command("systemctl", "is-active", SERVICE) != "active":
                raise RuntimeError("Сервис не active")
            with urllib.request.urlopen("http://127.0.0.1:8000/openapi.json", timeout=3) as response:
                if path in response.read().decode("utf-8"):
                    return
            error = "Новый маршрут ещё не появился"
        except Exception as exc:
            error = str(exc)
        time.sleep(2)
    raise RuntimeError("API не подтвердил установку: " + error)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--apply", action="store_true")
    parser.add_argument("--root", default=str(ROOT))
    args = parser.parse_args()

    if os.geteuid() != 0:
        raise RuntimeError("Запусти с sudo")
    root = Path(args.root).resolve()
    registry = root / "server/__init__.py"
    module = root / "server/nyan_future_vote.py"
    if not registry.is_file() or not (root / "server/backend_app.py").is_file():
        raise RuntimeError("Не найден Nyan Wallet в указанной папке")
    if command("systemctl", "is-active", SERVICE) != "active":
        raise RuntimeError("Сервис не запущен. Установка остановлена")
    if registry.is_symlink() or module.is_symlink():
        raise RuntimeError("Не изменяю символические ссылки")

    body = fetch_module()
    old_module = module.read_bytes() if module.exists() else None
    if old_module is not None and old_module != body:
        raise RuntimeError("Модуль уже есть, но отличается. Нужна ручная проверка")
    old_registry = registry.read_bytes()
    new_registry = patch_registry(old_registry)
    changes = [
        (path, before, after)
        for path, before, after in (
            (module, old_module, body),
            (registry, old_registry, new_registry),
        )
        if before != after
    ]
    print("Готово к установке:", *[str(path.relative_to(root)) for path, _, _ in changes], sep="\n  ")
    if args.check:
        print("Проверка пройдена. Изменений нет.")
        return
    if not changes:
        health_check()
        print("Уже установлено; API работает.")
        return

    backup = root / ".nyan-future-vote-backups" / dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
    backup.mkdir(parents=True, exist_ok=False)
    written = []
    try:
        for path, old, new in changes:
            if old is not None:
                copy = backup / path.relative_to(root)
                copy.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, copy)
            write_atomic(path, new)
            written.append((path, old))
        command("systemctl", "restart", SERVICE)
        health_check()
    except BaseException:
        print("Ошибка. Возвращаю прежние файлы.", file=sys.stderr)
        for path, old in reversed(written):
            if old is None:
                path.unlink(missing_ok=True)
            else:
                write_atomic(path, old)
        try:
            command("systemctl", "restart", SERVICE)
        except Exception as exc:
            print("Не удалось перезапустить прежний сервер:", exc, file=sys.stderr)
        raise
    print("Опрос включён. Никакие сообщения в Telegram не отправлялись.")
    print("Резервная копия:", backup)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("ОШИБКА:", exc, file=sys.stderr)
        sys.exit(1)
