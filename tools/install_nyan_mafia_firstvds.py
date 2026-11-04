#!/usr/bin/env python3
"""Install NYAN MAFIA backend from a reviewed local ZIP, with rollback.

    sudo python3 install_nyan_mafia_firstvds.py --bundle /tmp/nyan-mafia-release.zip --check
    sudo python3 install_nyan_mafia_firstvds.py --bundle /tmp/nyan-mafia-release.zip --apply

Only the two new server modules and a small registration in server/__init__.py
are changed. The frontend lives on GitHub Pages and must be published there
separately. Neither command starts a round or sends Telegram messages.
"""

from __future__ import annotations

import argparse
import ast
import datetime
import os
import shutil
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path


DEFAULT_ROOT = Path("/opt/nyan-wallet")
SERVICE = "nyan-wallet"
MODULES = ("server/nyan_mafia.py", "server/nyan_mafia_rules.py")
IMPORT_LINE = "from .nyan_mafia import register_nyan_mafia"
REGISTER_LINE = "    register_nyan_mafia(backend_app.app)"


def run(*args: str) -> str:
    process = subprocess.run(args, capture_output=True, text=True, timeout=50, check=False)
    if process.returncode:
        raise RuntimeError((process.stderr or process.stdout or "ошибка команды").strip()[-1400:])
    return process.stdout.strip()


def registry_patch(source: bytes) -> bytes:
    content = source.decode("utf-8")
    has_import = IMPORT_LINE in content
    has_register = REGISTER_LINE in content
    if has_import != has_register:
        raise ValueError("найдено частичное подключение Mafia, проверь server/__init__.py")
    if has_import:
        return source
    anchor_imports = (
        "from .nyan_spy import register_nyan_spy\n",
        "from .telegram_relay import register_telegram_relay\n",
    )
    anchor_regs = (
        "    register_nyan_spy(backend_app.app)\n",
        "    register_telegram_relay(backend_app.app)\n",
    )
    import_anchor = next((a for a in anchor_imports if content.count(a) == 1), None)
    register_anchor = next((a for a in anchor_regs if content.count(a) == 1), None)
    if not import_anchor or not register_anchor:
        raise ValueError("безопасная точка подключения Mafia не найдена")
    content = content.replace(import_anchor, import_anchor + IMPORT_LINE + "\n", 1)
    content = content.replace(register_anchor, register_anchor + REGISTER_LINE + "\n", 1)
    ast.parse(content, filename="server/__init__.py")
    return content.encode("utf-8")


def read_bundle(bundle: Path) -> dict[str, bytes]:
    result = {}
    with zipfile.ZipFile(bundle) as archive:
        for name in MODULES:
            raw = archive.read(name)
            if len(raw) > 160_000:
                raise ValueError("файл слишком большой: " + name)
            ast.parse(raw.decode("utf-8"), filename=name)
            result[name] = raw
    if b'/api/nyan-mafia/status' not in result[MODULES[0]]:
        raise ValueError("в пакете отсутствует API NYAN MAFIA")
    return result


def atomic_write(dest: Path, payload: bytes) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp = tempfile.mkstemp(prefix=".nyan-mafia-", dir=dest.parent)
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(payload)
            output.flush()
            os.fsync(output.fileno())
        os.chmod(temp, dest.stat().st_mode & 0o777 if dest.exists() else 0o644)
        os.replace(temp, dest)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def health_check() -> None:
    error = "маршрут не появился"
    for _ in range(14):
        try:
            if run("systemctl", "is-active", SERVICE) != "active":
                raise RuntimeError("служба ещё запускается")
            with urllib.request.urlopen("http://127.0.0.1:8000/openapi.json", timeout=4) as response:
                schema = response.read().decode("utf-8")
            if '"/api/nyan-mafia/status"' not in schema or '"/api/owner/nyan-mafia/start"' not in schema:
                raise RuntimeError("пока нет маршрутов Mafia")
            try:
                urllib.request.urlopen("http://127.0.0.1:8000/api/nyan-mafia/status", timeout=3)
            except urllib.error.HTTPError as http_error:
                if http_error.code == 401:
                    return
                raise RuntimeError(f"неверный код проверки авторизации: {http_error.code}") from http_error
            raise RuntimeError("статус Mafia доступен без авторизации! установка небезопасна")
        except Exception as exc:
            error = str(exc)
        time.sleep(2)
    raise RuntimeError("не удалось подтвердить запуск Mafia API: " + error)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true", help="только проверить, ничего не меняя")
    mode.add_argument("--apply", action="store_true", help="применить с резервной копией")
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    args = parser.parse_args()
    root = args.root.resolve()
    registry = root / "server/__init__.py"
    if not registry.is_file() or not (root / "server/backend_app.py").is_file():
        raise RuntimeError("не обнаружен сервер Nyan Wallet по пути " + str(root))
    source_files = read_bundle(args.bundle.resolve())
    paths = {root / name: raw for name, raw in source_files.items()}
    paths[registry] = registry_patch(registry.read_bytes())
    changed = []
    for destination, payload in paths.items():
        if destination.is_symlink():
            raise RuntimeError("не изменяю символическую ссылку: " + str(destination))
        before = destination.read_bytes() if destination.exists() else None
        if before != payload:
            changed.append((destination, before, payload))

    print("NYAN MAFIA: готово к установке файлов:")
    for path, _, _ in changed:
        print("  ", path.relative_to(root))
    if args.check:
        print("проверка завершена, ничего не изменено")
        return
    if os.geteuid() != 0:
        raise RuntimeError("для --apply нужны права root")
    if run("systemctl", "is-active", SERVICE) != "active":
        raise RuntimeError("сначала восстанови работу nyan-wallet.service")
    if not changed:
        health_check()
        print("Mafia API уже установлен и отвечает")
        return
    backup = root / ".nyan-mafia-backups" / datetime.datetime.now(
        datetime.timezone.utc
    ).strftime("%Y%m%d-%H%M%S-%f")
    backup.mkdir(parents=True, exist_ok=False)
    for path, old, _ in changed:
        if old is not None:
            copy = backup / path.relative_to(root)
            copy.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, copy)
    try:
        for path, _, new in changed:
            atomic_write(path, new)
        run("systemctl", "restart", SERVICE)
        health_check()
    except Exception:
        for path, old, _ in reversed(changed):
            if old is None:
                path.unlink(missing_ok=True)
            else:
                atomic_write(path, old)
        run("systemctl", "restart", SERVICE)
        raise
    print("NYAN MAFIA API установлен. резервные копии:", backup)
    print("регистрация не открывалась, в Telegram ничего не отправлялось")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        raise SystemExit("ОШИБКА: " + str(exc)) from exc
