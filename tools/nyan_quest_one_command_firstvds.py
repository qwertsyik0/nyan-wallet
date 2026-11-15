#!/usr/bin/env python3
"""Nyan Quest one-command deployment + registration announcement on FirstVDS.

Run as root on qwertsyik:
    python3 /root/nyan_quest_setup.py
The script installs the separate Quest API, safely backs up files, asks for
the destination Telegram group ID, and opens registration, queuing the post
with a Mini App button through the existing durable Telegram relay.

Later:
    python3 /root/nyan_quest_setup.py --close
    python3 /root/nyan_quest_setup.py --status
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path("/opt/nyan-wallet")
PYTHON = ROOT / ".venv/bin/python"
INSTALLER = Path("/root/nyan_quest_api_installer.py")
TARGET = Path("/root/.nyan_quest_destination")
LOCAL = "http://127.0.0.1:8000"
RAW = (
    "https://raw.githubusercontent.com/qwertsyik0/nyan-wallet/main/"
    "tools/install_nyan_quest_firstvds.py"
)
INSTALLER_BLOB = "1661c69f179912087eda7e4b4678b46701fa0559"
REQUIRED = (
    "/api/nyan-quest/status", "/api/nyan-quest/join",
    "/api/internal/nyan-quest/open", "/api/internal/nyan-quest/close",
)
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def get_json(url: str, body=None, headers=None, timeout: float = 15) -> dict:
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    request = urllib.request.Request(
        url, data=data,
        headers={"Accept": "application/json", **({"Content-Type": "application/json"} if data is not None else {}), **(headers or {})},
        method="POST" if data is not None else "GET",
    )
    try:
        with OPENER.open(request, timeout=timeout) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        detail = error.read(10240).decode("utf-8", errors="replace")
        try:
            detail = json.loads(detail).get("detail") or detail
        except ValueError:
            pass
        raise RuntimeError(f"HTTP {error.code}: {str(detail)[:400]}") from error


def check_routes():
    paths = get_json(LOCAL + "/openapi.json", timeout=7).get("paths", {})
    missing = [route for route in REQUIRED if route not in paths]
    if missing:
        raise RuntimeError("Отсутствуют маршруты Quest API: " + ", ".join(missing))


def known_token() -> str:
    # python-dotenv is installed in the Nyan Wallet API virtual environment.
    # The token is returned only into this process's memory, not printed or logged.
    code = (
        "from dotenv import dotenv_values; import os; "
        "e=dotenv_values('/opt/nyan-wallet/.env'); "
        "print(os.getenv('BOT_TOKEN') or e.get('BOT_TOKEN') or '')"
    )
    proc = subprocess.run(
        [str(PYTHON), "-c", code],
        capture_output=True, text=True, timeout=15,
    )
    if proc.returncode:
        raise RuntimeError("Не удаётся прочитать конфигурацию API: " + proc.stderr[-250:])
    token = proc.stdout.strip()
    if not token or ":" not in token:
        raise RuntimeError("BOT_TOKEN отсутствует в /opt/nyan-wallet/.env")
    return token


def download_installer():
    req = urllib.request.Request(
        RAW, headers={"User-Agent": "NyanQuestOneCommand/1.0"}
    )
    with OPENER.open(req, timeout=30) as response:
        body = response.read(250001)
    blob = hashlib.sha1(b"blob " + str(len(body)).encode() + b"\0" + body).hexdigest()
    if blob != INSTALLER_BLOB:
        raise RuntimeError("Установщик GitHub изменился. Ничего не установлено.")
    INSTALLER.write_bytes(body)
    os.chmod(INSTALLER, 0o600)


def run_install():
    download_installer()
    for mode in ("--check", "--apply"):
        print(f"== NYAN QUEST API {mode} ==", flush=True)
        subprocess.run(
            [str(PYTHON), str(INSTALLER), mode], check=True,
            timeout=220,
        )
    check_routes()


def dest(token: str) -> int:
    stored = TARGET.read_text(encoding="utf-8").strip() if TARGET.exists() else ""
    prompt = (
        "ID группы Nyan Quest (-100...) или @nyanquests для канала"
        + (f" [{stored}]" if stored else "") + ": "
    )
    target = input(prompt).strip() or stored
    if not target:
        raise RuntimeError("Нужно указать чат: ID частной группы или @nyanquests")
    if target.startswith("-100") and target[1:].isdigit():
        chat_id = int(target)
    elif target.startswith("@"):
        # Only public usernames can be resolved with getChat;
        # private invite links are not chat IDs.
        response = get_json(
            "https://api.telegram.org/bot" + token + "/getChat",
            {"chat_id": target}, timeout=25,
        )
        if response.get("ok") is not True:
            raise RuntimeError("Бот не может найти указанный канал или группу")
        chat = response["result"]
        chat_id = int(chat["id"])
        print("Найден чат:", chat.get("title") or target)
    else:
        raise RuntimeError("Используй ID вида -100... или публичный @username")
    if chat_id >= 0:
        raise RuntimeError("Нужен ID группы/канала, не личного чата")
    print("Целевой чат:", chat_id)
    return chat_id


def signed_action(token: str, action: str, chat_id: int) -> dict:
    timestamp = str(int(time.time()))
    payload = f"nyan-quest:{action}:v1:{chat_id}:{timestamp}".encode("utf-8")
    signature = hmac.new(token.encode("utf-8"), payload, hashlib.sha256).hexdigest()
    result = get_json(
        LOCAL + f"/api/internal/nyan-quest/{action}",
        body={}, headers={
            "X-Nyan-Quest-Chat": str(chat_id),
            "X-Nyan-Quest-Time": timestamp,
            "X-Nyan-Quest-Signature": signature,
        },
        timeout=25,
    )
    if result.get("ok") is not True:
        raise RuntimeError("API не подтвердило открытие/закрытие набора")
    return result


def save_target(chat_id: int) -> None:
    TARGET.write_text(str(chat_id) + "\n", encoding="utf-8")
    os.chmod(TARGET, 0o600)


def main():
    options = argparse.ArgumentParser(description="Nyan Quest registration setup")
    options.add_argument(
        "--close", action="store_true", help="close the current registration"
    )
    options.add_argument(
        "--status", action="store_true", help="check that API endpoints are installed"
    )
    args = options.parse_args()
    if os.geteuid() != 0:
        raise RuntimeError("Выполняй под root на FirstVDS (root@qwertsyik)")
    if not PYTHON.is_file():
        raise RuntimeError("Не найден действующий сервер /opt/nyan-wallet")
    token = known_token()
    if args.status:
        check_routes()
        print("OK: четыре маршрута Nyan Quest работают")
        if TARGET.exists():
            print("Чат:", TARGET.read_text().strip())
        return
    if args.close:
        check_routes()
        if not TARGET.exists():
            raise RuntimeError("Не сохранён ID группы; сначала открой запись")
        chat_id = int(TARGET.read_text().strip())
        closed = signed_action(token, "close", chat_id)
        print(f"OK: набор #{closed['round_id']} закрыт; участников: {closed['players']}")
        return

    # Verify the existing API before changing a production service.
    try:
        get_json(LOCAL + "/openapi.json")
    except Exception as exc:
        raise RuntimeError("Nyan Wallet API сейчас не отвечает, установка отменена: " + str(exc)) from exc

    print("Устанавливаю отдельную страницу регистрации Nyan Quest.")
    run_install()
    print("Проверка API завершена. Набор ещё не открыт.", flush=True)
    chat_id = dest(token)
    # The signed API queues the group announcement with the Telegram Mini App
    # button inside the same transaction that opens the registration.
    opened = signed_action(token, "open", chat_id)
    save_target(chat_id)
    print(f"OK: набор №{opened['round_id']} открыт.")
    if opened.get("invitation_queued"):
        print("Объявление с кнопкой ЗАПИСАТЬСЯ НА КВЕСТ поставлено в Telegram Relay.")
        print("Доставка зависит от рабочего relay на сервере бота.")
    else:
        print("ВНИМАНИЕ: сервер не подтвердил постановку объявления в очередь.")
    print("Мини-приложение: https://t.me/nyancash_bot?startapp=nyan_quest")
    print("Позже закрыть набор: python3 /root/nyan_quest_setup.py --close")


if __name__ == "__main__":
    try:
        main()
    except (Exception, KeyboardInterrupt) as error:
        raise SystemExit("ОШИБКА: " + str(error)) from error
