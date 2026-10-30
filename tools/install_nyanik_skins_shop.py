#!/usr/bin/env python3
"""Install four limited Nyanik skins and their purchase API on FirstVDS.

Run as root from Termius:
  python3 install_nyanik_skins_shop.py --revision <git-sha> --check
  python3 install_nyanik_skins_shop.py --revision <git-sha> --apply

The check stage changes nothing. Existing wallet files are preserved or backed
up; purchase/stock data is never reset on repeat installation.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path


ROOT = Path("/opt/nyan-wallet")
SERVER = ROOT / "server"
REGISTRY = SERVER / "__init__.py"
MODULE = SERVER / "nyanik_skins_shop.py"
ASSETS = ROOT / "assets" / "wallet-skins"
SERVICE = "nyan-wallet"
RAW = "https://raw.githubusercontent.com/qwertsyik0/nyan-wallet"
IMPORT = b"from .nyanik_skins_shop import register_nyanik_skins_shop\n"
CALL = b"    register_nyanik_skins_shop(backend_app.app)\n"
IMPORT_ANCHOR = b"from .appeals import register_appeals\n"
CALL_ANCHOR = b"    register_appeals(backend_app.app)\n"
ARTWORK = {
    "nyanik-moon-sail.webp": "74bc91faf07ca2d23bd55953edd8265b124f89405778d398429fcf082d6a3b92",
    "nyanik-lighthouse.webp": "7925ec26069fb4636007d031d7d7c3bf74fe5623d07f5ff02afff9811301b26a",
    "nyanik-balloon.webp": "ff994c442895fcec2d5c8c7a2b49b2e30b51d7119b88146a3da2b2afe7806a64",
    "nyanik-arch.webp": "da1df04ffa5e9a6e9840d1953b3020ef0b1f9a7ac113823a0e76f2a9c2be500c",
}


def command(*args: str) -> str:
    result = subprocess.run(args, capture_output=True, text=True, check=False)
    if result.returncode:
        raise RuntimeError(f"Команда {args[0]}: {(result.stderr or result.stdout)[-900:]}")
    return result.stdout.strip()


def download(revision: str, relative_path: str, limit: int) -> bytes:
    url = f"{RAW}/{revision}/{relative_path}"
    with urllib.request.urlopen(url, timeout=25) as response:
        if response.status != 200:
            raise RuntimeError(f"HTTP {response.status}: {relative_path}")
        content = response.read(limit + 1)
    if not content or len(content) > limit:
        raise RuntimeError(f"Файл отсутствует или слишком велик: {relative_path}")
    return content


def patch_registry(content: bytes) -> bytes:
    has_import, has_call = IMPORT in content, CALL in content
    if has_import != has_call:
        raise RuntimeError("Неполная регистрация лавки в server/__init__.py")
    if has_import:
        return content
    if content.count(IMPORT_ANCHOR) != 1 or content.count(CALL_ANCHOR) != 1:
        raise RuntimeError("Серверная регистрация отличается от ожидаемой: нужно проверить вручную")
    return content.replace(IMPORT_ANCHOR, IMPORT_ANCHOR + IMPORT, 1).replace(
        CALL_ANCHOR, CALL_ANCHOR + CALL, 1
    )


def safe_write(path: Path, content: bytes) -> None:
    fd, tmp = tempfile.mkstemp(prefix=".nyan-skins-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp, 0o644)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def healthcheck() -> None:
    error = "Маршрут не появился"
    for _ in range(16):
        try:
            with urllib.request.urlopen("http://127.0.0.1:8000/openapi.json", timeout=3) as response:
                paths = json.load(response).get("paths", {})
            if "/api/nyanik-skins/buy" not in paths:
                error = "Маршрут покупки не зарегистрирован"
                time.sleep(1.5)
                continue
            with urllib.request.urlopen("http://127.0.0.1:8000/api/nyanik-skins/catalog", timeout=3) as response:
                data = json.load(response)
            if not data.get("ready") or len(data.get("items", [])) != 4:
                raise RuntimeError("Не все фоны готовы на сервере")
            if any(item.get("total") != 6 or not (0 <= item.get("remaining", -1) <= 6) for item in data["items"]):
                raise RuntimeError("Неожиданные остатки или лимиты продажи")
            return
        except Exception as exc:
            error = str(exc)
            time.sleep(1.5)
    raise RuntimeError("Сервер после установки не подтвердил готовность лавки: " + error)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--revision", required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if not re.fullmatch(r"[a-f0-9]{40}", args.revision):
        raise RuntimeError("Требуется точный SHA коммита из GitHub")
    if os.geteuid() != 0:
        raise RuntimeError("Установку нужно выполнять под root")
    if not SERVER.is_dir() or not REGISTRY.is_file():
        raise RuntimeError("Не найден сервер Nyan Wallet: /opt/nyan-wallet/server")
    if command("systemctl", "is-active", SERVICE) != "active":
        raise RuntimeError("nyan-wallet не запущен; сначала нужно разобраться с сервисом")
    if not (SERVER / "appeals.py").is_file():
        raise RuntimeError("Не найден модуль пользовательских фонов server/appeals.py")

    registry_before = REGISTRY.read_bytes()
    registry_after = patch_registry(registry_before)
    files: list[tuple[Path, bytes | None, bytes]] = []
    remote_module = download(args.revision, "server/nyanik_skins_shop.py", 200_000)
    for path, content in [(MODULE, remote_module), (REGISTRY, registry_after)]:
        if path.is_symlink():
            raise RuntimeError(f"Символическая ссылка: {path}")
        before = path.read_bytes() if path.is_file() else None
        if path == MODULE and before is not None and before != content:
            raise RuntimeError("Модуль лавки уже существует и отличается. Нужна ручная проверка")
        files.append((path, before, content))

    for filename, digest in ARTWORK.items():
        path = ASSETS / filename
        if path.is_symlink():
            raise RuntimeError(f"Символическая ссылка: {path}")
        content = download(args.revision, f"assets/wallet-skins/{filename}", 2_000_000)
        if hashlib.sha256(content).hexdigest() != digest or content[:4] != b"RIFF" or content[8:12] != b"WEBP":
            raise RuntimeError(f"Не совпадает хеш файла {filename}")
        before = path.read_bytes() if path.is_file() else None
        if before is not None and before != content:
            raise RuntimeError(f"Фон {filename} уже существует с другим содержимым")
        files.append((path, before, content))

    with tempfile.TemporaryDirectory(prefix="nyan-skins-check-") as directory:
        module_path, registry_path = Path(directory) / "nyanik_skins_shop.py", Path(directory) / "__init__.py"
        module_path.write_bytes(remote_module)
        registry_path.write_bytes(registry_after)
        command(sys.executable, "-m", "py_compile", str(module_path), str(registry_path))

    print("Лавка: 4 фона × 6 экземпляров × 500 🐾")
    print("Серверные файлы:", sum(old != new for _, old, new in files), "будут установлены или обновлены")
    if args.check:
        print("Проверка пройдена. Никаких изменений не внесено.")
        return

    if not ASSETS.is_dir():
        raise RuntimeError("Не найдена папка /opt/nyan-wallet/assets/wallet-skins")
    backups: list[tuple[Path, Path | None]] = []
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    try:
        # Assets, then module, then registry: never expose an import before its data.
        for path, before, after in sorted(files, key=lambda item: 0 if item[0].parent == ASSETS else (1 if item[0] == MODULE else 2)):
            if before == after:
                continue
            backup = None
            if before is not None:
                backup = path.with_name(path.name + f".before-nyanik-shop-{stamp}")
                if backup.exists():
                    raise RuntimeError(f"Уже есть резервная копия: {backup}")
                shutil.copy2(path, backup)
            backups.append((path, backup))
            safe_write(path, after)
        command("systemctl", "restart", SERVICE)
        healthcheck()
    except Exception:
        for path, backup in reversed(backups):
            if backup is None:
                path.unlink(missing_ok=True)
            else:
                shutil.copy2(backup, path)
        try:
            command("systemctl", "restart", SERVICE)
        except Exception as error:
            print("Не удалось перезапустить восстановленный сервис:", error, file=sys.stderr)
        raise
    print("Лавка установлена. Остатки и списания хранятся в PostgreSQL.")
    print("Ссылка: https://t.me/nyancash_bot?startapp=nyanik_skins")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("ОШИБКА:", exc, file=sys.stderr)
        sys.exit(1)
