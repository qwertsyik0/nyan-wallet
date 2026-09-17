import hashlib
import hmac
import json
import os
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qsl

from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "wallet.db"

load_dotenv(ROOT / ".env")
BOT_TOKEN = os.getenv("BOT_TOKEN")

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN отсутствует в .env")

app = FastAPI(title="Nyan Wallet API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://qwertsyik0.github.io"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "X-Telegram-Init-Data"],
)

def now_iso():
    return datetime.now(timezone.utc).isoformat()

def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def init_db():
    conn = get_db()
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            telegram_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT NOT NULL,
            last_name TEXT,
            balance INTEGER NOT NULL DEFAULT 0 CHECK(balance >= 0),
            created_at TEXT NOT NULL,
            last_seen_at TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id INTEGER NOT NULL,
            amount INTEGER NOT NULL,
            operation_type TEXT NOT NULL,
            description TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY (telegram_id)
                REFERENCES users(telegram_id)
                ON DELETE CASCADE
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_transactions_user
        ON transactions(telegram_id, id DESC)
    """)
    conn.commit()
    conn.close()

def verify_init_data(init_data: str):
    if not init_data:
        raise HTTPException(status_code=401, detail="Telegram initData отсутствует")

    pairs = dict(parse_qsl(init_data, keep_blank_values=True))
    received_hash = pairs.pop("hash", None)

    if not received_hash:
        raise HTTPException(status_code=401, detail="Telegram hash отсутствует")

    auth_date_raw = pairs.get("auth_date")
    if not auth_date_raw:
        raise HTTPException(status_code=401, detail="auth_date отсутствует")

    try:
        auth_date = int(auth_date_raw)
    except ValueError:
        raise HTTPException(status_code=401, detail="Некорректный auth_date")

    if abs(int(time.time()) - auth_date) > 3600:
        raise HTTPException(
            status_code=401,
            detail="Telegram сессия устарела. Откройте Mini App заново.",
        )

    data_check_string = "\n".join(
        f"{key}={value}" for key, value in sorted(pairs.items())
    )

    secret_key = hmac.new(
        b"WebAppData",
        BOT_TOKEN.encode(),
        hashlib.sha256,
    ).digest()

    calculated_hash = hmac.new(
        secret_key,
        data_check_string.encode(),
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(calculated_hash, received_hash):
        raise HTTPException(
            status_code=401,
            detail="Подпись Telegram недействительна",
        )

    try:
        user = json.loads(pairs["user"])
    except (KeyError, json.JSONDecodeError):
        raise HTTPException(
            status_code=401,
            detail="Данные пользователя Telegram отсутствуют",
        )

    if not isinstance(user.get("id"), int):
        raise HTTPException(status_code=401, detail="Некорректный Telegram ID")

    return user

def get_or_create_user(tg_user):
    telegram_id = tg_user["id"]
    username = tg_user.get("username")
    first_name = tg_user.get("first_name") or "Пользователь"
    last_name = tg_user.get("last_name")
    timestamp = now_iso()

    conn = get_db()
    conn.execute(
        """
        INSERT INTO users (
            telegram_id, username, first_name, last_name,
            balance, created_at, last_seen_at
        )
        VALUES (?, ?, ?, ?, 0, ?, ?)
        ON CONFLICT(telegram_id)
        DO UPDATE SET
            username = excluded.username,
            first_name = excluded.first_name,
            last_name = excluded.last_name,
            last_seen_at = excluded.last_seen_at
        """,
        (
            telegram_id,
            username,
            first_name,
            last_name,
            timestamp,
            timestamp,
        ),
    )
    conn.commit()

    user = conn.execute(
        """
        SELECT telegram_id, username, first_name, last_name, balance, created_at
        FROM users
        WHERE telegram_id = ?
        """,
        (telegram_id,),
    ).fetchone()

    transactions = conn.execute(
        """
        SELECT id, amount, operation_type, description, created_at
        FROM transactions
        WHERE telegram_id = ?
        ORDER BY id DESC
        LIMIT 20
        """,
        (telegram_id,),
    ).fetchall()

    conn.close()

    return {
        "user": dict(user),
        "transactions": [dict(row) for row in transactions],
    }

init_db()

@app.get("/api/health")
async def health():
    return {
        "ok": True,
        "service": "Nyan Wallet API",
        "database": DB_PATH.name,
    }

@app.get("/api/me")
async def me(
    x_telegram_init_data: str | None = Header(
        default=None,
        alias="X-Telegram-Init-Data",
    )
):
    tg_user = verify_init_data(x_telegram_init_data or "")
    data = get_or_create_user(tg_user)
    return {"ok": True, **data}
