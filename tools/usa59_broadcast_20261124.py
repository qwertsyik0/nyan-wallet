#!/usr/bin/env python3
"""Owner-authorized USA 59 RUB offer broadcast with a shared code."""
import argparse
import ast
import fcntl
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import string
import time
import urllib.error
import urllib.parse
import urllib.request

STATE = "usa59_20261124.sqlite3"
RESERVED = {"#FSLYRY", "#NYKZRA", "#KZRVPA", "#RZKVMA", "#JPKVRA"}

def configuration(root):
    cfg = {}
    path = root / ".env"
    if path.exists():
        for line in path.read_text().splitlines():
            key, sep, value = line.strip().removeprefix("export ").partition("=")
            if sep:
                cfg[key.strip()] = value.strip().strip("'\"")
    cfg.update(os.environ)
    token = cfg.get("BOT_TOKEN", "").strip()
    if not token:
        for name in ("config.py", "bot.py", "main.py"):
            path = root / name
            if not path.exists():
                continue
            for node in ast.walk(ast.parse(path.read_text())):
                if not isinstance(node, ast.Assign):
                    continue
                names = {t.id.upper() for t in node.targets if isinstance(t, ast.Name)}
                if names & {"BOT_TOKEN", "TOKEN", "API_TOKEN"}:
                    if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                        candidate = node.value.value.strip()
                        if re.fullmatch(r"\d+:[A-Za-z0-9_-]+", candidate):
                            token = candidate
            if token:
                break
    if not token:
        raise RuntimeError("токен не найден, отправка не начата")
    return cfg, token

def request(url, payload, headers=None):
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    req = urllib.request.Request(url, data=raw, headers={
        "Content-Type": "application/json", **(headers or {})})
    with urllib.request.urlopen(req, timeout=25) as response:
        return json.load(response)

def recipients(api, owner, token):
    ids, after = set(), 0
    while True:
        payload = {"owner_telegram_id": owner, "audience": "all",
                   "after_telegram_id": after, "limit": 500}
        raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
        stamp = str(int(time.time()))
        signature = hmac.new(token.encode(), stamp.encode() + b"\n" + raw,
                             hashlib.sha256).hexdigest()
        try:
            page = request(api + "/api/internal/broadcast/recipients", payload, {
                "X-Nyan-Timestamp": stamp, "X-Nyan-Signature": signature})
        except urllib.error.HTTPError as error:
            raise RuntimeError("список получателей: HTTP " + str(error.code)) from None
        except Exception as error:
            raise RuntimeError("список получателей недоступен: " + type(error).__name__) from None
        if page.get("ok") is not True or not isinstance(page.get("recipients"), list):
            raise RuntimeError("список получателей не подтверждён")
        for uid in page["recipients"]:
            if type(uid) is not int or uid <= 0:
                raise RuntimeError("некорректный получатель")
            if uid != owner:
                ids.add(uid)
        if page.get("has_more") is False:
            return sorted(ids)
        nxt = page.get("next_after_telegram_id")
        if page.get("has_more") is not True or type(nxt) is not int or nxt <= after:
            raise RuntimeError("некорректная пагинация, отправка не начата")
        after = nxt

def prepare(db, ids):
    with db:
        for uid in ids:
            db.execute(
                "INSERT OR IGNORE INTO recipients (uid, code) VALUES (?, ?)",
                (uid, "#USANYAN"))
        db.execute("INSERT INTO meta VALUES ('snapshot')")

def message(code):
    return (
        "🎁 для тебя предложение от нян!\n\n"
        "забирай ФИЗ США всего за 59 ₽ 🐾\n\n"
        f"твой промокод: {code}\n\n"
        "предъяви его продавцу нян шопа перед оплатой, "
        "чтобы купить аккаунт по специальной цене 💗"
    )

def set_state(db, uid, state, mid=None):
    with db:
        db.execute("UPDATE recipients SET state=?, message_id=? WHERE uid=?",
                   (state, mid, uid))

def deliver(db, token):
    rows = db.execute("SELECT uid, code FROM recipients WHERE state='pending' ORDER BY uid").fetchall()
    print("ожидают отправки:", len(rows), flush=True)
    url = "https://api.telegram.org/bot" + token + "/sendMessage"
    for index, (uid, code) in enumerate(rows, 1):
        for attempt in range(3):
            set_state(db, uid, "sending")
            try:
                answer = request(url, {"chat_id": uid, "text": message(code)})
                mid = answer.get("result", {}).get("message_id")
                if answer.get("ok") is True and type(mid) is int:
                    set_state(db, uid, "sent", mid)
                else:
                    set_state(db, uid, "unknown")
                break
            except urllib.error.HTTPError as error:
                if error.code == 429:
                    set_state(db, uid, "pending")
                    try:
                        delay = int(json.load(error).get("parameters", {}).get("retry_after", 5))
                    except Exception:
                        delay = 5
                    if attempt < 2:
                        time.sleep(max(1, delay) + 1)
                        continue
                    break
                state = "blocked" if error.code == 403 else "failed" if error.code < 500 else "unknown"
                set_state(db, uid, state)
                if error.code == 401:
                    raise RuntimeError("токен отклонён, рассылка остановлена") from None
                break
            except Exception:
                set_state(db, uid, "unknown")
                break
        if index % 25 == 0:
            print("обработано:", index, "из", len(rows), flush=True)
        time.sleep(0.12)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="/home/nyanteam/new_bot")
    parser.add_argument("--status", action="store_true")
    args = parser.parse_args()
    root = Path(args.root).resolve()
    if not root.is_dir():
        raise RuntimeError("папка бота не найдена")
    os.umask(0o077)
    lock = (root / ".usa59_20261124.lock").open("w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise RuntimeError("эта рассылка уже запущена") from None
    path = root / STATE
    if args.status and not path.exists():
        print("рассылка ещё не подготовлена")
        return
    db = sqlite3.connect(path)
    try:
        os.chmod(path, 0o600)
        db.execute("CREATE TABLE IF NOT EXISTS recipients (uid INTEGER PRIMARY KEY, code TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'pending', message_id INTEGER)")
        db.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY)")
        db.commit()
        if not args.status:
            cfg, token = configuration(root)
            try:
                me = request("https://api.telegram.org/bot" + token + "/getMe", {})
            except Exception as error:
                raise RuntimeError("соединение с Telegram: " + type(error).__name__) from None
            if not me.get("ok") or me.get("result", {}).get("username", "").lower() != "nyancash_bot":
                raise RuntimeError("это не @nyancash_bot, отправка остановлена")
            if not db.execute("SELECT 1 FROM meta WHERE key='snapshot'").fetchone():
                api = (cfg.get("NYAN_WALLET_API") or cfg.get("NYAN_WALLET_API_URL") or
                       "https://nyan-wallet-153-76-175-145.sslip.io").rstrip("/")
                if urllib.parse.urlparse(api).scheme != "https":
                    raise RuntimeError("для списка получателей требуется HTTPS")
                owner = int(cfg.get("OWNER_TELEGRAM_ID") or 6289461565)
                prepare(db, recipients(api, owner, token))
            deliver(db, token)
        print("\nрезультат:")
        for state, count in db.execute("SELECT state, count(*) FROM recipients GROUP BY state"):
            print(state, count)
        print("коды и результаты:", path)
        print("unknown/sending не отправляются повторно автоматически")
    finally:
        db.close()

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nостановлено; повторный запуск продолжит pending")
    except Exception as error:
        raise SystemExit(str(error))
