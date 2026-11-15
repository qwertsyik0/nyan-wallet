#!/usr/bin/env python3
"""Deploy Nyan Confessions to FirstVDS and optionally queue the launch broadcast."""
from __future__ import annotations

import argparse
import ast
import fcntl
import json
import os
import re
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path("/opt/nyan-wallet")
SERVICE = "nyan-wallet"
LOCAL = "http://127.0.0.1:8000"
PUBLIC = "https://nyan-wallet-bridge.qwertsyik.workers.dev"
WALLET_PAGES = "https://qwertsyik0.github.io/nyan-wallet/"
REPO = "https://raw.githubusercontent.com/qwertsyik0/nyan-wallet"
ROUTE = "/api/nyan-confessions"
INIT = "server/__init__.py"
MODULE = "server/nyan_confessions.py"
FILES = (
    MODULE,
    "assets/nyan-confessions/index.html",
    "assets/nyan-confessions/style.css",
    "assets/nyan-confessions/confessions.js",
    "assets/nyan-confessions/nyanik.webp",
)
IMPORT = "from .nyan_confessions import register_nyan_confessions"
REGISTER = "    register_nyan_confessions(backend_app.app)"
CAMPAIGN = "broadcast:nyan-confessions:v1:"
# Keep the original prefix so older installers also recognize the campaign.
REPEAT_CAMPAIGN = CAMPAIGN + "repeat1:"
ANNOUNCEMENT = (
    "💌 <b>nyan confessions уже открыт</b>\n\n"
    "если есть что рассказать, напиши об этом анонимно. "
    "признание появится в общей ленте без твоего имени.\n\n"
    "в nyan wallet ищи нас в разделе «ещё», сразу под nyan id."
)
BUTTON = {"text": "открыть nyan confessions", "url": "https://t.me/nyancash_bot?startapp=nyan_confessions"}


def command(*parts: str) -> str:
    return subprocess.check_output(parts, text=True, timeout=90).strip()


def read_url(url: str, headers: dict | None = None) -> tuple[bytes, str]:
    request = urllib.request.Request(url, headers={"User-Agent": "NyanWalletDeploy/1.0", **(headers or {})})
    try:
        with urllib.request.urlopen(request, timeout=12) as response:
            body = response.read(850_001)
            if len(body) > 850_000:
                raise RuntimeError(f"Ответ больше ожидаемого: {url}")
            return body, response.headers.get_content_type()
    except urllib.error.HTTPError as error:
        raise RuntimeError(f"HTTP {error.code} при запросе {url}") from None


def add_registration(source: str) -> str:
    if IMPORT not in source:
        anchor = "\nfrom .broadcast import register_broadcast\n"
        if source.count(anchor) != 1:
            raise RuntimeError("Не найден импорт маршрутов в server/__init__.py.")
        source = source.replace(anchor, anchor + IMPORT + "\n", 1)
    if REGISTER not in source:
        anchor = "    register_broadcast(backend_app.app)"
        if source.count(anchor) != 1:
            raise RuntimeError("Не найдено подключение маршрутов в server/__init__.py.")
        source = source.replace(anchor, anchor + "\n" + REGISTER, 1)
    ast.parse(source, filename=INIT)
    return source


def atomic_write(path: Path, content: bytes, mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".nyan-confessions-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        os.chmod(name, mode)
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def verify_site(origin: str) -> None:
    html, html_type = read_url(origin + ROUTE)
    if html_type != "text/html" or b"<title>Nyan Confessions</title>" not in html:
        raise RuntimeError("Страница Nyan Confessions не найдена.")
    for name, mime in (
        ("style.css", "text/css"),
        ("confessions.js", "text/javascript"),
        ("nyanik.webp", "image/webp"),
    ):
        content, media_type = read_url(origin + ROUTE + "/" + name)
        if not content or media_type != mime:
            raise RuntimeError(f"Не загружается ресурс {name}.")
    data, _ = read_url(origin + ROUTE + "/feed?before=1")
    if json.loads(data) != {"posts": [], "before": None}:
        raise RuntimeError("Лента признаний не отвечает.")


def wait_for(check, attempts: int) -> None:
    for attempt in range(attempts):
        try:
            check()
            return
        except (OSError, ValueError, RuntimeError):
            if attempt == attempts - 1:
                raise
            time.sleep(2)


def deploy(revision: str) -> None:
    if command("systemctl", "is-active", SERVICE) != "active":
        raise RuntimeError("Служба Nyan Wallet должна быть активна.")
    if not (ROOT / INIT).is_file():
        raise RuntimeError("Установка Nyan Wallet в /opt/nyan-wallet не найдена.")
    incoming = {filename: read_url(f"{REPO}/{revision}/{filename}")[0] for filename in FILES}
    ast.parse(incoming[MODULE].decode("utf-8"), filename=MODULE)
    if not incoming[FILES[-1]].startswith(b"RIFF"):
        raise RuntimeError("Не скачалось изображение Няника.")
    incoming[INIT] = add_registration((ROOT / INIT).read_text(encoding="utf-8")).encode("utf-8")
    changes = []
    for filename, content in incoming.items():
        path = ROOT / filename
        if path.is_symlink() or (path.exists() and not path.is_file()):
            raise RuntimeError(f"Необычный путь для файла {filename}.")
        old = path.read_bytes() if path.exists() else None
        if old != content:
            mode = path.stat().st_mode & 0o777 if path.exists() else 0o644
            changes.append((filename, old, content, mode))
    if not changes:
        verify_site(LOCAL)
        print("Nyan Confessions уже работает на FirstVDS.", flush=True)
        return

    backup = Path(tempfile.mkdtemp(prefix=".nyan-confessions-backup-", dir=ROOT))
    for filename, old, _, _ in changes:
        if old is not None:
            atomic_write(backup / filename, old, 0o600)
    restarted = False
    try:
        for filename, _, content, mode in changes:
            atomic_write(ROOT / filename, content, mode)
        restarted = True
        command("systemctl", "restart", SERVICE)
        wait_for(lambda: verify_site(LOCAL), 20)
    except Exception:
        for filename, old, _, mode in reversed(changes):
            if old is None:
                (ROOT / filename).unlink(missing_ok=True)
            else:
                atomic_write(ROOT / filename, old, mode)
        if restarted:
            command("systemctl", "restart", SERVICE)
        raise
    print("Nyan Confessions работает на FirstVDS.", flush=True)
    print("Резервная копия", backup, flush=True)


def wallet_ready() -> None:
    html, _ = read_url(WALLET_PAGES + f"?confessions={int(time.time())}")
    if b'startParam === "nyan_confessions"' not in html or (PUBLIC + ROUTE).encode() not in html:
        raise RuntimeError("GitHub Pages ещё не опубликовал переход в Nyan Confessions.")


def service_setting(name: str) -> str:
    pid = int(command("systemctl", "show", SERVICE, "-p", "MainPID", "--value"))
    if pid <= 1:
        raise RuntimeError("Не найден запущенный процесс Nyan Wallet.")
    prefix = name.encode() + b"="
    for entry in Path(f"/proc/{pid}/environ").read_bytes().split(b"\0"):
        if entry.startswith(prefix):
            return entry[len(prefix):].decode().strip()
    from dotenv import dotenv_values
    return (dotenv_values(ROOT / ".env").get(name) or "").strip()


def enqueue_broadcast(cursor, *, campaign: str, envelope: str, owner: int) -> tuple[int, int]:
    cursor.execute("SELECT pg_advisory_xact_lock(%s)", (2026111509,))
    cursor.execute("""
        SELECT EXISTS (SELECT 1 FROM telegram_relay_outbox WHERE starts_with(source_key, %s))
        """, (campaign,))
    if cursor.fetchone()[0]:
        return 0, 0

    carried = 0
    if campaign == REPEAT_CAMPAIGN:
        # The relay acknowledges by row ID and lease token, so in-flight jobs keep their lease.
        cursor.execute("""
            UPDATE telegram_relay_outbox SET source_key = %s || CAST(chat_id AS text)
            WHERE source_key = %s || CAST(chat_id AS text) AND state IN ('pending', 'leased')
            """, (campaign, CAMPAIGN))
        carried = cursor.rowcount

    cursor.execute("""
        INSERT INTO telegram_relay_outbox (source_key, chat_id, body, state, attempts, created_at)
        SELECT %s || CAST(telegram_id AS text), telegram_id, %s, 'pending', 0, now()
        FROM users WHERE telegram_id > 0 AND telegram_id <> %s
        ON CONFLICT (source_key) DO NOTHING
        """, (campaign, envelope, owner))
    return cursor.rowcount, carried


def broadcast(send: bool, *, repeat: bool = False) -> None:
    from psycopg import connect

    campaign = REPEAT_CAMPAIGN if repeat else CAMPAIGN
    dsn = service_setting("DATABASE_URL").replace("postgresql+psycopg://", "postgresql://", 1)
    if not dsn.startswith(("postgresql://", "postgres://")):
        raise RuntimeError("Не настроена PostgreSQL база Nyan Wallet.")
    if send:
        secret = service_setting("NYAN_TELEGRAM_RELAY_SECRET")
        if len(secret) < 32:
            raise RuntimeError("Telegram Relay не подключён к Nyan Wallet.")
        health, _ = read_url(
            LOCAL + "/api/internal/telegram-relay/status", {"X-Nyan-Relay-Secret": secret}
        )
        if not json.loads(health).get("ok"):
            raise RuntimeError("Telegram Relay не отвечает.")
        owner = int(service_setting("OWNER_TELEGRAM_ID"))
        if owner <= 0:
            raise RuntimeError("Не настроен владелец Nyan Wallet.")
        envelope = "NYAN_TG_RICH_V1:" + json.dumps(
            {"text": ANNOUNCEMENT, "buttons": [BUTTON]}, ensure_ascii=False
        )

    with connect(dsn, connect_timeout=8) as connection:
        with connection.cursor() as cursor:
            if send:
                added, carried = enqueue_broadcast(cursor, campaign=campaign, envelope=envelope, owner=owner)
            cursor.execute("""
                SELECT state, count(*) FROM telegram_relay_outbox
                WHERE source_key = %s || CAST(chat_id AS text) GROUP BY state ORDER BY state
                """, (campaign,))
            counts = dict(cursor.fetchall())

    if send:
        print(f"Добавлено получателей в рассылку: {added}", flush=True)
        if repeat:
            print(f"Перенесено ожидающих и отправляемых сообщений: {carried}", flush=True)
    print("Статус рассылки", json.dumps(counts, ensure_ascii=False), flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--revision")
    parser.add_argument("--announce", action="store_true")
    parser.add_argument("--repeat", action="store_true", help="Повторить рассылку установленного сайта")
    parser.add_argument("--status", action="store_true")
    args = parser.parse_args()
    if os.geteuid() != 0:
        parser.error("Запусти команду от root на FirstVDS.")
    if args.status and (args.revision or args.announce):
        parser.error("--status используется отдельно или с --repeat.")
    if args.repeat and (args.revision or args.announce):
        parser.error("--repeat использует установленный сайт.")
    if not (args.status or args.repeat) and not re.fullmatch(r"[a-f0-9]{40}", args.revision or ""):
        parser.error("Укажи SHA опубликованного коммита через --revision.")

    from psycopg import Error as DatabaseError

    def run_broadcast(send: bool) -> None:
        try:
            broadcast(send, repeat=args.repeat)
        except DatabaseError:
            raise RuntimeError("Ошибка соединения с базой или записи рассылки.") from None

    with open("/run/lock/nyan-confessions.lock", "a", encoding="utf-8") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if args.status:
            run_broadcast(False)
            return
        if args.repeat:
            verify_site(LOCAL)
        else:
            deploy(args.revision)
        wait_for(lambda: verify_site(PUBLIC), 5)
        print(PUBLIC + ROUTE, flush=True)
        if args.announce or args.repeat:
            wait_for(wallet_ready, 10)
            run_broadcast(True)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        raise SystemExit(f"Ошибка: {error}") from None
