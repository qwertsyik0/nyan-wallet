#!/usr/bin/env python3
"""Safe single-command FirstVDS installer for Nyan ID XP and leaderboard.

  curl -fsSL https://raw.githubusercontent.com/qwertsyik0/nyan-wallet/main/tools/install_nyan_id_xp_firstvds.py | sudo python3 - --apply

Only server/nyan_experience.py, two small registrations in server/__init__.py,
and the Nyan ID API response in server/nyan_id.py are changed. Existing local
modules, balances, cards, bot handlers and other VPS modifications are preserved.
The installer backs up source, restarts systemd, checks routes/auth, and rolls
back source automatically on failure. The created XP database table is harmless
and remains available if a rollback is necessary.
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import re
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
RAW = "https://raw.githubusercontent.com/qwertsyik0/nyan-wallet"
MODULE = "server/nyan_experience.py"
API = "server/nyan_id.py"
REGISTRY = "server/__init__.py"


def run(*args: str, check: bool = True) -> str:
    p = subprocess.run(args, capture_output=True, text=True, timeout=60, check=False)
    if check and p.returncode:
        raise RuntimeError((p.stderr or p.stdout or "ошибка команды").strip()[-1600:])
    return p.stdout.strip()


def download(ref: str) -> bytes:
    url = f"{RAW}/{ref}/{MODULE}"
    req = urllib.request.Request(url, headers={"User-Agent": "NyanIDVerifiedXPInstaller/1.0"})
    with urllib.request.urlopen(req, timeout=25) as response:
        body = response.read(65001)
    if not body or len(body) > 65000:
        raise RuntimeError("Некорректный размер модуля Nyan XP")
    source = body.decode("utf-8")
    ast.parse(source, filename=MODULE)
    for expected in ('"/api/owner/nyan-id/experience"', '"/api/nyan-id/leaderboard"', "def register_nyan_experience"):
        if expected not in source:
            raise RuntimeError("В скачанном модуле отсутствует " + expected)
    return body


def patch_registry(raw: bytes) -> bytes:
    source = raw.decode("utf-8")
    imp = "from .nyan_experience import register_nyan_experience"
    call = "    register_nyan_experience(backend_app.app)"
    if (imp in source) != (call in source):
        raise RuntimeError("Неполное подключение опыта в server/__init__.py")
    if imp in source and call in source:
        return raw
    anchor_imp = "from .nyan_id import register_nyan_id\n"
    anchor_call = "    register_nyan_id(backend_app.app)\n"
    if source.count(anchor_imp) != 1 or source.count(anchor_call) != 1:
        raise RuntimeError("Не найдена безопасная точка Nyan ID в server/__init__.py")
    source = source.replace(anchor_imp, anchor_imp + imp + "\n", 1)
    source = source.replace(anchor_call, call + "\n" + anchor_call, 1)
    ast.parse(source, filename=REGISTRY)
    return source.encode("utf-8")


def patch_api(raw: bytes) -> bytes:
    source = raw.decode("utf-8")
    imp = "from .nyan_experience import experience_for_user"
    field = '"experience": experience_for_user(session, user.telegram_id),'
    if (imp in source) != (field in source):
        raise RuntimeError("Неполное подключение опыта в server/nyan_id.py")
    if imp in source and field in source:
        return raw
    anchor_imp = "from .advanced_features import level_data, settings\n"
    anchor_field = '            "rank": "Владелец" if core.is_owner(user.telegram_id) else level["name"],\n'
    if source.count(anchor_imp) != 1 or source.count(anchor_field) != 1:
        raise RuntimeError("Существующий Nyan ID отличается; файлы не изменены")
    source = source.replace(anchor_imp, anchor_imp + imp + "\n", 1)
    source = source.replace(anchor_field, anchor_field + "            " + field + "\n", 1)
    ast.parse(source, filename=API)
    return source.encode("utf-8")


def write_atomic(path: Path, body: bytes, mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".nyan-xp-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as writer:
            writer.write(body)
            writer.flush()
            os.fsync(writer.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def verify() -> None:
    last_error = "сервис не ответил"
    expected = {"/api/nyan-id", "/api/nyan-id/send-png",
                "/api/nyan-id/leaderboard", "/api/owner/nyan-id/experience"}
    for _ in range(15):
        try:
            if run("systemctl", "is-active", SERVICE) != "active":
                raise RuntimeError("nyan-wallet не active")
            with urllib.request.urlopen("http://127.0.0.1:8000/api/health", timeout=4) as response:
                if not json.load(response).get("ok"):
                    raise RuntimeError("ошибка /api/health")
            with urllib.request.urlopen("http://127.0.0.1:8000/openapi.json", timeout=4) as response:
                available = set(json.load(response).get("paths", {}))
            if not expected.issubset(available):
                raise RuntimeError("Nyan ID API ещё не зарегистрирован")
            try:
                urllib.request.urlopen("http://127.0.0.1:8000/api/nyan-id", timeout=4)
            except urllib.error.HTTPError as e:
                if e.code == 401:
                    print("OK: Nyan ID требует подтверждение Telegram")
                elif e.code == 503:
                    print("OK: API активен, но на сервисе включены техработы")
                else:
                    raise RuntimeError(f"Неожиданный ответ Nyan ID: HTTP {e.code}")
            else:
                raise RuntimeError("Nyan ID не проверяет авторизацию")
            try:
                urllib.request.urlopen("http://127.0.0.1:8000/api/nyan-id/leaderboard", timeout=4)
            except urllib.error.HTTPError as e:
                if e.code not in (401, 503):
                    raise RuntimeError(f"Неожиданный ответ рейтинга: HTTP {e.code}")
            else:
                raise RuntimeError("Рейтинг доступен без Telegram-авторизации")
            print("OK: сервис активен, Nyan ID и рейтинг защищены авторизацией")
            return
        except Exception as e:
            last_error = str(e)
            time.sleep(2)
    raise RuntimeError("Проверка после перезапуска не пройдена: " + last_error)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--apply", action="store_true")
    parser.add_argument("--ref", default="main")
    args = parser.parse_args()
    if not re.fullmatch(r"(?:main|[0-9a-f]{40})", args.ref):
        raise RuntimeError("Разрешена только ветка main или полный SHA коммита")

    required = (ROOT / "server/backend_app.py", ROOT / "server/nyan_id.py",
                ROOT / "server/__init__.py", ROOT / "server/activity.py",
                ROOT / "server/daily_tasks.py", ROOT / "server/achievements.py",
                ROOT / "server/interactive_ideas.py")
    absent = [str(p) for p in required if not p.is_file()]
    if absent:
        raise RuntimeError("Не найдены компоненты Nyan Wallet: " + ", ".join(absent))
    desired = {
        ROOT / MODULE: download(args.ref),
        ROOT / API: patch_api((ROOT / API).read_bytes()),
        ROOT / REGISTRY: patch_registry((ROOT / REGISTRY).read_bytes()),
    }
    changed = {
        path: body for path, body in desired.items()
        if not path.is_file() or path.read_bytes() != body
    }
    print("Обновляем только:", ", ".join(str(p.relative_to(ROOT)) for p in changed) or "ничего")
    if args.check:
        print("OK: проверка без изменения VPS")
        return
    if os.geteuid() != 0:
        raise RuntimeError("Для установки нужен sudo")
    if run("systemctl", "is-active", SERVICE) != "active":
        raise RuntimeError("Сервис сейчас не active; установка не начата")
    if not changed:
        verify()
        return

    originals = {p: (p.read_bytes() if p.exists() else None) for p in changed}
    backup_root = ROOT / ".nyan-id-xp-backups"
    backup_root.mkdir(exist_ok=True, mode=0o700)
    backup = Path(tempfile.mkdtemp(prefix="release-", dir=backup_root))
    os.chmod(backup, 0o700)
    for path in originals:
        if path.is_file():
            target = backup / path.relative_to(ROOT)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
    print("Резервные копии:", backup)

    try:
        for path, body in changed.items():
            mode_bits = path.stat().st_mode & 0o777 if path.exists() else 0o644
            write_atomic(path, body, mode_bits)
        run("systemctl", "restart", SERVICE)
        verify()
    except BaseException:
        for path, original in originals.items():
            if original is None:
                path.unlink(missing_ok=True)
            else:
                mode_bits = path.stat().st_mode & 0o777 if path.exists() else 0o644
                write_atomic(path, original, mode_bits)
        run("systemctl", "restart", SERVICE, check=False)
        print("ОШИБКА: прежние файлы восстановлены, сервис перезапущен", file=sys.stderr)
        raise

    print("ГОТОВО: Nyan ID XP и рейтинг установлены. Балансы не изменены.")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print("ОШИБКА:", str(error), file=sys.stderr)
        sys.exit(1)
