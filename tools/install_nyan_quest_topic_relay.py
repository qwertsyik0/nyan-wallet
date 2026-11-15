#!/usr/bin/env python3
"""Safely configure the existing SprintHost relay to send Quest invitations to topic 2.

Run as nyanteam on mjodgiver; the script discovers the running relay script.
It only patches a very specific rich-payload block, keeps an untouched backup,
syntax-checks, and reports whether a service restart is needed.
"""
from __future__ import annotations

import argparse
import ast
import datetime
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

MARKER = "# NYAN QUEST_TOPIC_ROUTING_V1"
ANCHOR = '''    return {
        "chat_id": int(chat_id),
        "text": html,
        "parse_mode": "HTML",
        "link_preview_options": {"is_disabled": True},
        "reply_markup": {"inline_keyboard": inline_keyboard},
    }'''
REPLACEMENT = '''    payload = {
        "chat_id": int(chat_id),
        "text": html,
        "parse_mode": "HTML",
        "link_preview_options": {"is_disabled": True},
        "reply_markup": {"inline_keyboard": inline_keyboard},
    }
    # NYAN QUEST_TOPIC_ROUTING_V1: only Quest signup messages in this group.
    if int(chat_id) == -1004381936410 and any(
        button["url"] == "https://t.me/nyancash_bot?startapp=nyan_quest"
        for button in buttons
    ):
        payload["message_thread_id"] = 2
    return payload'''


def worker_processes():
    found = []
    for dirpath in pathlib.Path("/proc").iterdir():
        if not dirpath.name.isdecimal():
            continue
        try:
            args = (dirpath / "cmdline").read_bytes().split(b"\0")
            for idx, arg in enumerate(args):
                if pathlib.PurePath(os.fsdecode(arg)).name == "nyan_telegram_relay_worker.py":
                    path = pathlib.Path(os.fsdecode(arg))
                    if not path.is_absolute():
                        path = (dirpath / "cwd").resolve() / path
                    path = path.resolve()
                    if path.is_file():
                        found.append((int(dirpath.name), path))
                    break
        except (PermissionError, FileNotFoundError, OSError):
            continue
    return found


def find_file():
    processes = worker_processes()
    paths = set(path for _, path in processes)
    if len(paths) == 1:
        return next(iter(paths)), processes
    if len(paths) > 1:
        raise RuntimeError("Найдено несколько разных Telegram Relay. Ничего не изменено.")
    candidates = (
        pathlib.Path("/home/nyanteam/new_bot/nyan_telegram_relay_worker.py"),
        pathlib.Path("/home/nyanteam/nyan-wallet/tools/nyan_telegram_relay_worker.py"),
        pathlib.Path("/home/nyanteam/nyan_telegram_relay_worker.py"),
    )
    files = [p for p in candidates if p.is_file()]
    if len(files) == 1:
        return files[0], processes
    raise RuntimeError(
        "Не удалось однозначно определить файл активного Telegram Relay. "
        "Проверь: pgrep -af nyan_telegram_relay_worker"
    )


def atomic(path, value):
    fd, tmp = tempfile.mkstemp(prefix=".nyan-quest-topic-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(tmp, path.stat().st_mode & 0o777)
        os.replace(tmp, path)
    finally:
        pathlib.Path(tmp).unlink(missing_ok=True)


def restart_user_service(pid):
    # Avoid unsafe kill/starting extra workers. Restart only when supervisor
    # is unambiguously a user systemd unit controlled by this account.
    try:
        cg = pathlib.Path(f"/proc/{pid}/cgroup").read_text()
    except OSError:
        return None
    import re
    matches = re.findall(r"/(?:app\.slice/)?([a-zA-Z0-9_.@-]+\.service)", cg)
    units = [u for u in matches if "relay" in u.lower()]
    if len(units) != 1:
        return None
    unit = units[0]
    proc = subprocess.run(
        ["systemctl", "--user", "show", unit, "--property=MainPID", "--value"],
        text=True, capture_output=True, timeout=10,
    )
    if proc.returncode or proc.stdout.strip() != str(pid):
        return None
    proc = subprocess.run(["systemctl", "--user", "restart", unit], text=True, capture_output=True, timeout=30)
    if proc.returncode:
        raise RuntimeError("systemctl --user restart failed: " + proc.stderr[-300:])
    return unit


def main():
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--apply", action="store_true")
    opts = parser.parse_args()
    path, procs = find_file()
    if path.is_symlink():
        raise RuntimeError("Файл Relay является symlink. Не изменяю.")
    before = path.read_text(encoding="utf-8")
    if MARKER in before:
        updated = before
    else:
        if before.count(ANCHOR) != 1:
            raise RuntimeError("Нестандартный Relay; безопасный шаблон для изменения не найден.")
        updated = before.replace(ANCHOR, REPLACEMENT)
    ast.parse(updated, filename=str(path))
    print("Telegram Relay:", path)
    print("Процессы:", [pid for pid, _ in procs])
    print("Назначение: группа -1004381936410, тема 2, только NYAN QUEST")
    if opts.check:
        print("Проверка OK. Будет обновлён:", before != updated)
        return
    if before == updated:
        print("Маршрутизация уже записана в файле. Для активного процесса может требоваться перезапуск.")
        return
    backup = path.with_name(path.name + ".bak.quest-topic." + datetime.datetime.now().strftime("%Y%m%d-%H%M%S"))
    shutil.copy2(path, backup)
    atomic(path, updated.encode("utf-8"))
    try:
        subprocess.run([sys.executable, "-m", "py_compile", str(path)], check=True, timeout=15, capture_output=True)
        unit = restart_user_service(procs[0][0]) if len(procs) == 1 else None
    except Exception:
        atomic(path, before.encode("utf-8"))
        raise
    print("Файл обновлён. Резервная копия:", backup)
    if unit:
        print("Relay перезапущен автоматически:", unit)
    else:
        print("ВНИМАНИЕ: требуется перезапуск Telegram Relay его штатным способом.")
        print("Другие процессы и основной bot.py не тронуты.")
    print("Следующее объявление Quest в очереди будет отправлено в тему 2.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        raise SystemExit("ОШИБКА: " + str(exc)) from exc
