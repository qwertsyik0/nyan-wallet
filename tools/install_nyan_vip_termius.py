#!/usr/bin/env python3
"""Safely merge ONLY Nyan VIP into a customized VPS worktree.

Usage:
  python /root/install_nyan_vip_termius.py
  python /root/install_nyan_vip_termius.py --apply

Never resets, cleans, stashes or overwrites unrelated files.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

REPO = Path("/opt/nyan-wallet")
BASE_SHA = "409a30870c1fc6ab653c493073cf9a30b20dc691"
VIP_SHA = "4dde03fe003fa3c2af8b44fd7b0b1dfebe751a27"
MERGE_FILES = (
    "server/__init__.py",
    "server/extended_features.py",
    "server/advanced_features.py",
    "server/nyan_id.py",
    "advanced_features.js",
    "nyan_id.js",
    "nyan_id.css",
    "index.html",
)
NEW_FILES = (
    "server/vip.py",
    "vip.js",
    "vip.css",
    "tools/test_vip_membership.py",
)


def run(*command: str, check: bool = True, **kwargs) -> subprocess.CompletedProcess:
    result = subprocess.run(command, cwd=REPO, capture_output=True, **kwargs)
    if check and result.returncode != 0:
        detail = (result.stderr or b"").decode("utf-8", "replace").strip()
        raise RuntimeError(f"{' '.join(command[:3])} failed: {detail[-500:]}")
    return result


def from_git(sha: str, path: str) -> bytes:
    return run("git", "show", f"{sha}:{path}").stdout


def merge(path: str, base: bytes, newest: bytes, current: bytes) -> bytes:
    with tempfile.TemporaryDirectory(prefix="nyan-vip-merge-") as temp:
        directory = Path(temp)
        original_path = directory / "vps"
        ancestor_path = directory / "baseline"
        updated_path = directory / "vip"
        original_path.write_bytes(current)
        ancestor_path.write_bytes(base)
        updated_path.write_bytes(newest)
        result = run(
            "git", "merge-file", "-p", "--diff3",
            "-L", "VPS_LOCAL",
            "-L", "VIP_BASE",
            "-L", "NYAN_VIP",
            str(original_path), str(ancestor_path), str(updated_path),
            check=False,
        )
        if result.returncode != 0:
            count = result.returncode
            raise RuntimeError(
                f"{path}: найдено {count} конфликтов с локальными изменениями. "
                "Файлы не менялись, нужна ручная интеграция."
            )
        return result.stdout


def prepare() -> tuple[dict[str, bytes], dict[str, bytes | None]]:
    run("git", "rev-parse", "--is-inside-work-tree")
    run("git", "cat-file", "-e", f"{BASE_SHA}^{{commit}}")
    run("git", "cat-file", "-e", f"{VIP_SHA}^{{commit}}")
    replacements = {}
    original = {}
    for path in MERGE_FILES:
        disk = REPO / path
        if not disk.is_file() or disk.is_symlink():
            raise RuntimeError(f"{path}: файл отсутствует или является ссылкой")
        current = disk.read_bytes()
        new = merge(path, from_git(BASE_SHA, path), from_git(VIP_SHA, path), current)
        if path.endswith(".py"):
            compile(new.decode("utf-8"), path, "exec")
        replacements[path] = new
        original[path] = current
        print(f"OK: {path}" + (" (без изменений)" if new == current else " (совмещено)"))

    for path in NEW_FILES:
        disk = REPO / path
        if disk.exists() and (not disk.is_file() or disk.is_symlink()):
            raise RuntimeError(f"{path}: путь занят, остановка")
        current = disk.read_bytes() if disk.exists() else None
        new = from_git(VIP_SHA, path)
        if current is not None and current != new:
            raise RuntimeError(f"{path}: локальный файл уже существует и отличается")
        if path.endswith(".py"):
            compile(new.decode("utf-8"), path, "exec")
        replacements[path] = new
        original[path] = current
        print(f"OK: {path}" + (" (уже установлен)" if current else " (новый)"))

    # Refuse to install if the merged code lacks the expected VIP hooks.
    markers = {
        "server/__init__.py": ("from .vip import register_vip", "register_vip(backend_app.app)"),
        "server/extended_features.py": ("VipPurchaseToken", "activate_vip(session, item.id"),
        "server/advanced_features.py": ('"vip": vip_profile_status(', "activate_vip(session, item.id"),
        "server/nyan_id.py": ('"vip": status_for_user(',),
        "index.html": ('vip.js?v=', 'vip.css?v='),
        "advanced_features.js": ("X-VIP-Purchase-Key",),
        "nyan_id.js": ("nyid-vip-active",),
    }
    for path, expected in markers.items():
        contents = replacements[path].decode("utf-8")
        for marker in expected:
            if marker not in contents:
                raise RuntimeError(f"{path}: отсутствует обязательная интеграция: {marker}")
    return replacements, original


def write_atomic(path: Path, data: bytes, mode: int = 0o644) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        dir=path.parent, prefix=".nyan-vip-", delete=False
    ) as file:
        staged = Path(file.name)
        file.write(data)
        file.flush()
        os.fsync(file.fileno())
    try:
        os.chmod(staged, mode)
        os.replace(staged, path)
    finally:
        staged.unlink(missing_ok=True)


def check_syntax() -> None:
    python = REPO / ".venv/bin/python"
    if not python.exists():
        raise RuntimeError("Не найден Python окружения /opt/nyan-wallet/.venv")
    run(str(python), "-m", "py_compile",
        "server/__init__.py", "server/vip.py", "server/extended_features.py",
        "server/advanced_features.py", "server/nyan_id.py")
    test = run(str(python), "tools/test_vip_membership.py")
    print(test.stdout.decode("utf-8", "replace").strip())
    if shutil.which("node"):
        for path in ("vip.js", "advanced_features.js", "nyan_id.js"):
            run("node", "--check", path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="Install VIP, verify and restart")
    args = parser.parse_args()
    if os.geteuid() != 0:
        raise RuntimeError("Запускайте под root в Termius")
    if not REPO.is_dir():
        raise RuntimeError(f"Путь не найден: {REPO}")
    print("Nyan VIP: объединяем только VIP код, существующие локальные модули сохраняем")
    replacements, originals = prepare()
    changed = [p for p, data in replacements.items() if data != originals[p]]
    print(f"\nФайлов для установки: {len(changed)} / {len(replacements)}")
    if not args.apply:
        print("Проверка завершена. Ни один файл на VPS не изменён.")
        print("При успешной проверке запустите эту же команду с --apply.")
        return

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_root = Path("/root/nyan-vip-backups") / stamp
    backup_root.mkdir(parents=True, exist_ok=False, mode=0o700)
    manifest = {}
    for path in replacements:
        previous = originals[path]
        manifest[path] = "existed" if previous is not None else "absent"
        if previous is not None:
            destination = backup_root / path
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(previous)
            os.chmod(destination, 0o600)
    (backup_root / "manifest.json").write_text(
        json.dumps({"files": manifest, "base": BASE_SHA, "vip": VIP_SHA},
                   ensure_ascii=False, indent=2), encoding="utf-8"
    )
    os.chmod(backup_root / "manifest.json", 0o600)
    print(f"Резервная копия файлов: {backup_root}")

    installed = []
    try:
        for path in changed:
            disk = REPO / path
            previous = originals[path]
            mode = stat.S_IMODE(disk.stat().st_mode) if previous is not None else 0o644
            write_atomic(disk, replacements[path], mode)
            installed.append(path)
        check_syntax()
        print("Проверка пройдена. Перезапускаем nyan-wallet.service.")
        run("systemctl", "restart", "nyan-wallet.service")
        time.sleep(3)
        service = run("systemctl", "is-active", "nyan-wallet.service")
        if service.stdout.decode("utf-8", "replace").strip() != "active":
            raise RuntimeError("Сервис не активен после обновления")
    except Exception:
        print("Ошибка установки! Восстанавливаем прежние файлы.")
        for path in reversed(installed):
            previous = originals[path]
            disk = REPO / path
            if previous is None:
                disk.unlink(missing_ok=True)
            else:
                copy_path = backup_root / path
                mode = stat.S_IMODE(copy_path.stat().st_mode)
                write_atomic(disk, previous, 0o644 if mode == 0o600 else mode)
        try:
            run("systemctl", "restart", "nyan-wallet.service")
        except Exception as error:
            print(f"ВНИМАНИЕ: требуется ручная проверка сервиса: {error}")
        raise

    print("\nNyan VIP установлен. Сервис: active.")
    print(f"Резервные файлы: {backup_root}")
    print("Git pull не выполнялся. Другие локальные изменения и модули сохранены.")
    print("Проверяйте VIP на тестовом кошельке перед публичным анонсом.")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"VIP УСТАНОВКА ОСТАНОВЛЕНА: {error}", file=sys.stderr)
        sys.exit(1)
