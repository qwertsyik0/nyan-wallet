#!/usr/bin/env python3
"""Transfer only credited voters from FirstVDS to SprintHost; send once via IPv6.

Modes:
  --export: FirstVDS; read election_voter data from local PostgreSQL; print one
            compressed transfer code. Never prints credentials.
  --send:   SprintHost; read transfer code from terminal; send via bot IPv6
            with an on-disk at-most-once journal.

No SQL INSERT/UPDATE is performed. Wallet balances are never changed.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import html
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import time
import zlib
from collections import Counter
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

CAMPAIGN = "nyan-election-voter-thanks-20261018-season2"
EXPECTED_RECIPIENTS = 39
SEASON_ID = 2
STATE_FILE = Path("/home/nyanteam/new_bot/.nyan_election_voter_thanks_20261018.json")


def export_recipients():
    pid = subprocess.check_output(
        ["systemctl", "show", "nyan-wallet", "-p", "MainPID", "--value"],
        text=True, timeout=8,
    ).strip()
    if not pid.isdecimal() or int(pid) <= 0:
        raise RuntimeError("Сервис nyan-wallet не работает")

    environment = {}
    for item in Path(f"/proc/{pid}/environ").read_bytes().split(b"\0"):
        if b"=" in item:
            key, value = item.split(b"=", 1)
            environment[key.decode(errors="replace")] = value.decode(errors="replace")
    dsn = environment.get("DATABASE_URL", "").replace(
        "postgresql+psycopg://", "postgresql://", 1
    )
    parsed = urlsplit(dsn)
    if parsed.scheme not in ("postgres", "postgresql") or not parsed.hostname:
        raise RuntimeError("Не удалось прочитать PostgreSQL URL из процесса nyan-wallet")
    query = parse_qs(parsed.query)
    pg_env = os.environ.copy()
    pg_env.update({
        "PGHOST": parsed.hostname,
        "PGPORT": str(parsed.port or 5432),
        "PGUSER": unquote(parsed.username or ""),
        "PGPASSWORD": unquote(parsed.password or ""),
        "PGDATABASE": unquote(parsed.path.lstrip("/")),
        "PGSSLMODE": query.get("sslmode", ["prefer"])[0],
        "PGCONNECT_TIMEOUT": "12",
    })
    sql = """
        SELECT row_to_json(rec)::text
        FROM (
            SELECT v.telegram_id::bigint AS id,
                   COALESCE(u.first_name, '') AS first,
                   COALESCE(u.last_name, '') AS last
              FROM election_votes AS v
              JOIN users AS u ON u.telegram_id = v.telegram_id
             WHERE v.season_id = 2
               AND EXISTS (
                 SELECT 1 FROM transactions AS t
                  WHERE t.telegram_id = v.telegram_id
                    AND t.operation_type = 'election_vote_reward'
                    AND t.amount = 200
                    AND t.created_at >= TIMESTAMPTZ '2026-10-18 00:00:00+00'
               )
             ORDER BY v.telegram_id
        ) AS rec
    """
    result = subprocess.run(
        ["psql", "-X", "-q", "-A", "-t", "-v", "ON_ERROR_STOP=1", "-c", sql],
        env=pg_env, capture_output=True, text=True, timeout=25,
    )
    if result.returncode:
        raise RuntimeError("Запрос к PostgreSQL завершился ошибкой")
    try:
        rows = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
    except (ValueError, TypeError):
        raise RuntimeError("PostgreSQL вернул некорректный список") from None
    validate_rows(rows)
    payload = {
        "campaign": CAMPAIGN,
        "season": SEASON_ID,
        "recipients": rows,
    }
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    code = base64.urlsafe_b64encode(zlib.compress(raw, 9)).decode()
    print(f"ПРОВЕРЕНО: {len(rows)} получателей с подтверждённым начислением 200 🐾.")
    print("Ниже код передачи. Он содержит имена и Telegram ID; не публикуй его.")
    print("=== НАЧАЛО КОДА ===")
    print(code)
    print("=== КОНЕЦ КОДА ===")
    print("Скопируй только строку между маркерами в терминал SprintHost.")


def validate_rows(rows):
    if not isinstance(rows, list) or len(rows) != EXPECTED_RECIPIENTS:
        raise RuntimeError(
            f"Проверка остановлена: найдено {len(rows) if isinstance(rows, list) else 0}, "
            f"ожидалось {EXPECTED_RECIPIENTS} получателей"
        )
    ids = set()
    for item in rows:
        if not isinstance(item, dict):
            raise RuntimeError("Некорректные данные участника")
        uid = item.get("id")
        if not isinstance(uid, int) or isinstance(uid, bool) or uid <= 0 or uid in ids:
            raise RuntimeError("Найден некорректный или повторный Telegram ID")
        ids.add(uid)
        for field in ("first", "last"):
            if not isinstance(item.get(field), str) or len(item[field]) > 255:
                raise RuntimeError("Некорректное имя участника")


def decode_code(code):
    if len(code) > 30000 or not re.fullmatch(r"[A-Za-z0-9_=-]+", code):
        raise RuntimeError("Некорректный формат кода")
    try:
        compressed = base64.urlsafe_b64decode(code)
        stream = zlib.decompressobj()
        raw = stream.decompress(compressed, 60000)
        if not stream.eof or stream.unconsumed_tail or stream.unused_data:
            raise ValueError("invalid compressed data")
        payload = json.loads(raw)
    except (ValueError, TypeError, zlib.error):
        raise RuntimeError("Не удалось прочитать код передачи") from None
    if not isinstance(payload, dict) or payload.get("campaign") != CAMPAIGN:
        raise RuntimeError("Код относится к другой рассылке")
    if payload.get("season") != SEASON_ID:
        raise RuntimeError("Неверный сезон выборов")
    rows = payload.get("recipients")
    validate_rows(rows)
    return rows


def message(uid, first, last):
    name = " ".join(s.strip() for s in (first, last) if s.strip()) or "участник"
    name = html.escape(name)
    return (
        "🐾 <b>NYAN ELECTIONS | ЛИЧНОЕ ПИСЬМО</b>\n\n"
        f'Многоуважаемый <a href="tg://user?id={uid}">{name}</a>!\n\n'
        "Благодарим вас за участие в голосовании Nyan Elections. "
        "Ваш голос учтён. В знак признательности на ваш кошелёк "
        "уже начислено <b>200 🐾</b>.\n\n"
        "Спасибо, что участвуете в жизни Nyan Wallet!\n\n"
        "С уважением, команда Nyan Wallet."
    )


def save_state(state):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".nyan-vote-", dir=str(STATE_FILE.parent))
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, sort_keys=True)
            f.flush()
            os.fsync(f.fileno())
        os.replace(name, STATE_FILE)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def send_letters():
    try:
        code = input("Вставь код из FirstVDS и нажми Enter: ").strip()
    except EOFError:
        raise RuntimeError("Код передачи не введён") from None
    rows = decode_code(code)
    payload_fingerprint = hashlib.sha256(
        json.dumps(rows, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()
    if STATE_FILE.exists():
        state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        if state.get("campaign") != CAMPAIGN or state.get("fingerprint") != payload_fingerprint:
            raise RuntimeError("Уже существует журнал другого набора получателей")
    else:
        state = {"campaign": CAMPAIGN, "fingerprint": payload_fingerprint, "attempts": {}}

    from dotenv import load_dotenv
    import httpx
    load_dotenv("/home/nyanteam/new_bot/.env")
    token = os.getenv("BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("BOT_TOKEN отсутствует на SprintHost")

    transport = httpx.HTTPTransport(local_address="::", retries=0)
    api = f"https://api.telegram.org/bot{token}/"
    with httpx.Client(transport=transport, trust_env=False, timeout=17) as client:
        try:
            response = client.get(api + "getMe")
            data = response.json()
        except (httpx.HTTPError, ValueError):
            raise RuntimeError("Не удалось проверить Telegram-бота по IPv6") from None
        username = str(data.get("result", {}).get("username", "")).lower()
        if not data.get("ok") or username != "nyancash_bot":
            raise RuntimeError("Токен не принадлежит @nyancash_bot")
        print(f"Telegram: @{username}; всего получателей: {len(rows)}")
        print("Подтверждённые отправки не повторяются. Начислений не будет.")
        counts = Counter()
        for entry in rows:
            uid = str(entry["id"])
            if uid in state["attempts"]:
                counts["already_attempted"] += 1
                continue
            # Durable mark BEFORE sending prevents duplicates on crash or timeout.
            state["attempts"][uid] = {"status": "attempted"}
            save_state(state)
            status, mid = "uncertain", None
            try:
                response = client.post(api + "sendMessage", json={
                    "chat_id": entry["id"],
                    "text": message(entry["id"], entry["first"], entry["last"]),
                    "parse_mode": "HTML",
                    "link_preview_options": {"is_disabled": True},
                })
                try:
                    data = response.json()
                except ValueError:
                    data = {}
                mid = data.get("result", {}).get("message_id") if data.get("ok") else None
                if response.status_code == 200 and isinstance(mid, int):
                    status = "sent"
                elif response.status_code in (400, 403):
                    status = "rejected"
                elif response.status_code == 429:
                    status = "rate_limited"
                else:
                    status = "uncertain"
            except httpx.HTTPError:
                status = "uncertain"
            state["attempts"][uid] = {"status": status}
            if isinstance(mid, int):
                state["attempts"][uid]["message_id"] = mid
            save_state(state)
            counts[status] += 1
            print(f"{sum(counts.values()) + counts['already_attempted']}/{EXPECTED_RECIPIENTS}: {status}")
            time.sleep(0.7)
        summary = Counter(item["status"] for item in state["attempts"].values())
        print("=== ИТОГ ===")
        for kind in ("sent", "rejected", "rate_limited", "uncertain", "attempted"):
            print(f"{kind}: {summary.get(kind, 0)}")
        print(f"Записей в журнале: {len(state['attempts'])} из {EXPECTED_RECIPIENTS}")
        print(f"Журнал сохранён: {STATE_FILE}")
        return 0 if summary["sent"] == EXPECTED_RECIPIENTS else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    choices = parser.add_mutually_exclusive_group(required=True)
    choices.add_argument("--export", action="store_true")
    choices.add_argument("--send", action="store_true")
    args = parser.parse_args()
    try:
        if args.export:
            export_recipients()
            return 0
        return send_letters()
    except Exception as exc:
        # Do not leak PostgreSQL passwords, Telegram tokens or person data.
        msg = str(exc) if isinstance(exc, RuntimeError) else type(exc).__name__
        print("ОСТАНОВЛЕНО:", msg, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
