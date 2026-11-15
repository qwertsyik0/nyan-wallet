#!/usr/bin/env python3
"""Install partner flood welcome from GitHub without uploading any ZIP.

Run as nyanteam on mjodgiver:
  python3 install_partner_flood_welcome_firstvds.py --check
  python3 install_partner_flood_welcome_firstvds.py --apply
The installer checks bot.py and uses exactly the generated NYAN welcome poster uploaded via SFTP,
backs up changed files, connects the new handler, and restarts the current bot.
"""

from __future__ import annotations

import argparse
import ast
import datetime
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path("/home/nyanteam/new_bot")
BOT = ROOT / "bot.py"
MODULE = ROOT / "partner_flood_welcome.py"
IMAGE = ROOT / "nyan_partner_welcome.jpg"
UPLOADED_IMAGE = Path("/home/nyanteam/nyan_welcome.jpg")
RESTART_HELPER = Path("/home/nyanteam/nyan-wallet/tools/nyan_bot_autodeploy.py")
PREFIX = "https://raw.githubusercontent.com/qwertsyik0/nyan-wallet/main/"
MODULE_URL = PREFIX + "bot_addons/partner_flood_welcome.py"
IMAGE_SHA256 = "7e68cab99ac73ffca0d4005b13a6ff529234994cc2692bd900662c0922bd8244"
MODULE_GIT_BLOB = "ad3f28f56461acb3043a61585ff3e082038afedb"
MARKER = "register_partner_flood_welcome"
OPEN = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def git_blob(data: bytes) -> str:
    return hashlib.sha1(
        b"blob " + str(len(data)).encode() + b"\0" + data
    ).hexdigest()


def download(url: str, expected: str, maximum: int) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "NyanFloodWelcomeInstaller/1.0"})
    with OPEN.open(req, timeout=30) as res:
        data = res.read(maximum + 1)
    if len(data) > maximum or git_blob(data) != expected:
        raise RuntimeError("Скачанный файл отличается от проверенного: " + url)
    return data


def patch_bot(original: str) -> str:
    tree = ast.parse(original, filename="bot.py")
    matching = [
        n for n in ast.walk(tree)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and n.func.attr == "run_polling"
    ]
    if len(matching) != 1 or not isinstance(matching[0].func.value, ast.Name):
        raise RuntimeError(
            "Не найден единственный стандартный run_polling. Файлы не менялись."
        )
    if "register_nyan_welcome_handlers" in original:
        raise RuntimeError(
            "У бота уже обнаружено другое приветствие. Установка остановлена "
            "для исключения двойных сообщений."
        )
    if MARKER in original:
        if (
            original.count("from partner_flood_welcome import register_partner_flood_welcome") != 1
            or original.count("register_partner_flood_welcome(") != 1
        ):
            raise RuntimeError("Найдено частичное подключение приветствия")
        return original
    lines = original.splitlines(keepends=True)
    call = matching[0]
    i = call.lineno - 1
    indent = lines[i][:len(lines[i]) - len(lines[i].lstrip(" \t"))]
    newline = "\r\n" if lines[i].endswith("\r\n") else "\n"
    lines[i:i] = [
        indent + "from partner_flood_welcome import register_partner_flood_welcome" + newline,
        indent + "register_partner_flood_welcome(" + call.func.value.id + ")" + newline,
    ]
    updated = "".join(lines)
    ast.parse(updated, filename="bot.py after welcome patch")
    return updated


def atomic(path: Path, content: bytes) -> None:
    fd, temp = tempfile.mkstemp(prefix=".partner-welcome-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as writer:
            writer.write(content)
            writer.flush()
            os.fsync(writer.fileno())
        mode = (path.stat().st_mode & 0o777) if path.exists() else 0o644
        os.chmod(temp, mode)
        os.replace(temp, path)
    finally:
        Path(temp).unlink(missing_ok=True)


def restart() -> None:
    sys.path.insert(0, str(RESTART_HELPER.parent))
    from nyan_bot_autodeploy import BOT as ROOT_FROM_HELPER, restart_nohup
    if ROOT_FROM_HELPER.resolve() != ROOT.resolve():
        raise RuntimeError("Неверный корень бота в помощнике перезапуска")
    restart_nohup()


def main() -> None:
    args = argparse.ArgumentParser()
    mode = args.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--apply", action="store_true")
    opts = args.parse_args()
    if not BOT.is_file() or not RESTART_HELPER.is_file():
        raise RuntimeError(
            "Не найден работающий бот или штатный помощник перезапуска на mjodgiver"
        )
    if any(p.is_symlink() for p in (BOT, MODULE, IMAGE, UPLOADED_IMAGE)):
        raise RuntimeError("Найдена символическая ссылка вместо файла; установка отменена")
    python = ROOT / "venv/bin/python"
    if not python.is_file():
        raise RuntimeError("Не найден интерпретатор бота")

    original_bot = BOT.read_bytes()
    original_module = MODULE.read_bytes() if MODULE.exists() else None
    original_image = IMAGE.read_bytes() if IMAGE.exists() else None
    new_module = download(MODULE_URL, MODULE_GIT_BLOB, 40_000)
    if not UPLOADED_IMAGE.is_file():
        raise RuntimeError(
            "Исходный баннер не найден: " + str(UPLOADED_IMAGE)
            + ". Скачай nyan_welcome.jpg из чата и загрузи через SFTP."
        )
    new_image = UPLOADED_IMAGE.read_bytes()
    if hashlib.sha256(new_image).hexdigest() != IMAGE_SHA256 or not new_image.startswith(b"\\xff\\xd8\\xff"):
        raise RuntimeError(
            "Баннер не совпадает с ранее созданным изображением. "
            "Загрузи оригинальный nyan_welcome.jpg без изменений."
        )
    ast.parse(new_module.decode("utf-8"), filename="partner_flood_welcome.py")
    updated = patch_bot(original_bot.decode("utf-8")).encode("utf-8")
    check = subprocess.run(
        [str(python), "-c", "from telegram.ext import MessageHandler, filters; "
         "assert filters.StatusUpdate.NEW_CHAT_MEMBERS; print('OK')"],
        cwd=ROOT, capture_output=True, text=True, timeout=15,
    )
    if check.returncode:
        raise RuntimeError("Несовместимая библиотека telegram: " + check.stderr[-800:])
    changes = [
        (BOT, original_bot, updated),
        (MODULE, original_module, new_module),
        (IMAGE, original_image, new_image),
    ]
    changes = [(p, old, new) for (p, old, new) in changes if old != new]
    if opts.check:
        print("OK: проверка завершена, изменений нет.")
        print("Изменения при установке:", [p.name for p, _, _ in changes])
        print("Приветствие: только группа -1003689150794, ответ на системное сообщение")
        return
    if not changes:
        print("Приветствие уже установлено, изменения не требуются")
        return

    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d-%H%M%S")
    backup = ROOT / (".partner-flood-welcome-" + stamp)
    backup.mkdir(mode=0o700, exist_ok=False)
    for p, old, _ in changes:
        if old is not None:
            backup_file = backup / p.name
            backup_file.write_bytes(old)
            os.chmod(backup_file, 0o600)
    try:
        for p, old, new in changes:
            atomic(p, new)
        result = subprocess.run(
            [str(python), "-m", "py_compile", str(BOT), str(MODULE)],
            cwd=ROOT, capture_output=True, text=True, timeout=20,
        )
        if result.returncode:
            raise RuntimeError(result.stderr[-800:])
        restart()
    except Exception as exc:
        for p, old, _ in reversed(changes):
            if old is None:
                p.unlink(missing_ok=True)
            else:
                atomic(p, old)
        try:
            restart()
        except Exception as rollback:
            raise RuntimeError(
                f"Ошибка установки: {exc}. Восстановление запуска требует проверки: "
                f"{rollback}. Копия: {backup}"
            ) from exc
        raise RuntimeError(
            f"Ошибка установки: {exc}. Исходные файлы восстановлены. Бэкап: {backup}"
        ) from exc
    print("OK: приветствие установлено, бот перезапущен без второго процесса.")
    print("Установлен оригинальный баннер NYAN SHOP × ФЛУД из SFTP.")
    print("Следующее вступление во флуд получит приветствие с упоминанием и кнопкой.")
    print("Бэкап:", backup)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        raise SystemExit("ОШИБКА: " + str(exc)) from exc
