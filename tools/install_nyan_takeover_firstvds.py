#!/usr/bin/env python3
"""Install the private NYAN TAKEOVER modules on FirstVDS without a git pull.

Run on the wallet VPS:
  sudo python3 install_nyan_takeover_firstvds.py --check
  sudo python3 install_nyan_takeover_firstvds.py --apply

Only event modules, assets, event registration, and badge image mappings change.
No event announcement is posted and no wallet balance is touched by this script.
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
import urllib.request
from pathlib import Path


REVISION = "3c0765177d3a452419ab5f34b59a5ef0b9ad582d"
RAW = f"https://raw.githubusercontent.com/qwertsyik0/nyan-wallet/{REVISION}/"
ROOT = Path("/opt/nyan-wallet")
SERVICE = "nyan-wallet"
MODULES = (
    "server/nyan_takeover_group.py",
    "server/nyan_takeover.py",
    "server/nyan_takeover_auction.py",
    "server/nyan_takeover_drops.py",
)
IMAGES = tuple(
    "assets/nyan-takeover/" + name
    for name in (
        "badge-auction-winner.png", "badge-economist.png",
        "badge-founding-resident.png", "badge-market-pioneer.png",
        "badge-resident.png", "badge-takeover-limited.png",
        "badge-wallet-explorer.png", "hero.png",
        "skin-founding.png", "skin-resident.png",
    )
)
REGISTERS = (
    "nyan_takeover_group", "nyan_takeover", "nyan_takeover_auction",
    "nyan_takeover_drops",
)
BADGE_IMAGES = (
    ("resident", "badge-resident.png"),
    ("founding", "badge-founding-resident.png"),
    ("market_pioneer", "badge-market-pioneer.png"),
    ("takeover_limited", "badge-takeover-limited.png"),
    ("economist", "badge-economist.png"),
    ("auction_winner", "badge-auction-winner.png"),
    ("economy_founder", "badge-founding-resident.png"),
    ("wallet_explorer", "badge-wallet-explorer.png"),
)


def run(*args: str) -> str:
    result = subprocess.run(args, capture_output=True, text=True, timeout=40)
    if result.returncode:
        raise RuntimeError(f"{args[0]}: {(result.stderr or result.stdout).strip()[-1000:]}")
    return result.stdout.strip()


def fetch(path: str) -> bytes:
    request = urllib.request.Request(RAW + path, headers={"User-Agent": "Nyan-Takeover-Installer/1"})
    with urllib.request.urlopen(request, timeout=30) as response:
        data = response.read(6_000_001)
    if not data or len(data) > 6_000_000:
        raise RuntimeError(f"Недопустимый размер {path}")
    if path.endswith(".png"):
        if not data.startswith(b"\x89PNG\r\n\x1a\n"):
            raise RuntimeError(f"Не PNG: {path}")
    else:
        ast.parse(data.decode("utf-8"), filename=path)
    return data


def patch_registry(source: bytes) -> bytes:
    data = source.decode("utf-8")
    imports = [f"from .{mod} import register_{mod}" for mod in REGISTERS]
    calls = [f"    register_{mod}(backend_app.app)" for mod in REGISTERS]
    found_imports = [item in data for item in imports]
    found_calls = [item in data for item in calls]
    if any(found_imports + found_calls) and not all(found_imports + found_calls):
        raise RuntimeError("Регистрация TAKEOVER частичная: нужна ручная проверка")
    if all(found_imports + found_calls):
        return source
    import_anchor = "from .fortune import register_fortune\n"
    call_anchor = "    register_fortune(backend_app.app)\n"
    if data.count(import_anchor) != 1 or data.count(call_anchor) != 1:
        raise RuntimeError("Не удалось безопасно найти место регистрации API")
    data = data.replace(import_anchor, import_anchor + "\n".join(imports) + "\n", 1)
    data = data.replace(call_anchor, call_anchor + "\n".join(calls) + "\n", 1)
    ast.parse(data, filename="server/__init__.py")
    return data.encode("utf-8")


def patch_achievements(source: bytes) -> bytes:
    data = source.decode("utf-8")
    # Update only the image dictionary; never replace unrelated achievement logic.
    if '"takeover_2026_resident"' in data:
        if not all(f'"takeover_2026_{key}"' in data for key, _ in BADGE_IMAGES):
            raise RuntimeError("Обнаружена частичная настройка значков TAKEOVER")
        return source
    anchor = '                "nyan_game_unmasker": "./assets/badges/nyan-game-unmasker.webp",\n'
    if data.count(anchor) != 1:
        print("ПРЕДУПРЕЖДЕНИЕ: не найдена таблица изображений достижений; не меняю её.")
        return source
    mappings = "".join(
        f'                "takeover_2026_{key}": "./assets/nyan-takeover/{image}",\n'
        for key, image in BADGE_IMAGES
    )
    data = data.replace(anchor, anchor + mappings, 1)
    ast.parse(data, filename="server/achievements.py")
    return data.encode("utf-8")


def replace_atomic(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".takeover-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp, (path.stat().st_mode & 0o777) if path.exists() else 0o644)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def health() -> None:
    last = ""
    expected = (
        '"/api/nyan-takeover/status"',
        '"/api/nyan-takeover/auction"',
        '"/api/nyan-takeover/drops"',
        '"/api/nyan-takeover/owner/group"',
    )
    for _ in range(15):
        try:
            if run("systemctl", "is-active", SERVICE) != "active":
                last = "Сервис не active"
                time.sleep(2)
                continue
            with urllib.request.urlopen("http://127.0.0.1:8000/openapi.json", timeout=3) as response:
                schema = response.read().decode("utf-8")
            if all(path in schema for path in expected):
                return
            last = "Новые маршруты отсутствуют в OpenAPI"
        except Exception as exc:
            last = str(exc)
        time.sleep(2)
    raise RuntimeError("API не подтвердил установку: " + last)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    opts = parser.add_mutually_exclusive_group(required=True)
    opts.add_argument("--check", action="store_true")
    opts.add_argument("--apply", action="store_true")
    parser.add_argument("--root", default=str(ROOT), help="Путь к установленному backend")
    args = parser.parse_args()
    if os.geteuid() != 0:
        raise RuntimeError("Нужны права root на FirstVDS")
    root = Path(args.root).resolve()
    if not (root / "server/__init__.py").is_file() or not (root / "server/achievements.py").is_file():
        raise RuntimeError("Не обнаружен установленный Nyan Wallet")
    if run("systemctl", "is-active", SERVICE) != "active":
        raise RuntimeError("Сервис сейчас не запущен; установка остановлена")

    changes: list[tuple[Path, bytes | None, bytes]] = []
    for rel in (*MODULES, *IMAGES):
        path = root / rel
        if path.is_symlink():
            raise RuntimeError(f"Не изменяю символическую ссылку: {path}")
        payload = fetch(rel)
        old = path.read_bytes() if path.exists() else None
        if rel in MODULES and old is not None and old != payload:
            raise RuntimeError(f"Существующий {rel} отличается от проверенного релиза")
        if old != payload:
            changes.append((path, old, payload))
    for rel, patcher in (
        ("server/__init__.py", patch_registry),
        ("server/achievements.py", patch_achievements),
    ):
        path = root / rel
        if path.is_symlink():
            raise RuntimeError(f"Не изменяю символическую ссылку: {path}")
        old = path.read_bytes()
        updated = patcher(old)
        if updated != old:
            changes.append((path, old, updated))

    print("Проверено. Файлов к установке:", len(changes))
    for path, _, _ in changes:
        print("  ", path.relative_to(root))
    if args.check:
        print("Проверка завершена. Никаких изменений не сделано.")
        return
    if not changes:
        health()
        print("Уже установлено.")
        return

    backup = root / ".nyan-takeover-backups" / dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
    backup.mkdir(parents=True, exist_ok=False)
    written: list[tuple[Path, bytes | None]] = []
    try:
        for path, old, new in changes:
            if old is not None:
                old_path = backup / path.relative_to(root)
                old_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, old_path)
            replace_atomic(path, new)
            written.append((path, old))
        run("systemctl", "restart", SERVICE)
        health()
    except BaseException:
        print("Ошибка проверки, возвращаю исходные файлы.", file=sys.stderr)
        for path, old in reversed(written):
            if old is None:
                path.unlink(missing_ok=True)
            else:
                replace_atomic(path, old)
        try:
            run("systemctl", "restart", SERVICE)
        except Exception as exc:
            print("Не удалось автоматически перезапустить прежний сервис:", exc, file=sys.stderr)
        raise
    print("NYAN TAKEOVER установлен. API отвечает. Публикации в Telegram не отправлялись.")
    print("Резервные копии:", backup)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print("ОШИБКА:", error, file=sys.stderr)
        sys.exit(1)
