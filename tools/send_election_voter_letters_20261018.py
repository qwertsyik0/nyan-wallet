#!/usr/bin/env python3
"""One-time, at-most-once voting thank-you letters; no balance mutations."""
from __future__ import annotations
import argparse
import html
import json
import os
import sys
import time
import urllib.error
import urllib.request
from collections import Counter

EXPECTED = 39
LEDGER = "election_voter_thanks_20261018"

def bot_api(token, method, payload=None):
    data = json.dumps(payload, ensure_ascii=False).encode() if payload is not None else None
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/{method}",
        data=data, headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=17) as response:
            result = json.loads(response.read())
    except urllib.error.HTTPError as exc:
        # NEVER log the full exception: its URL contains the bot token.
        raise RuntimeError(f"telegram_http_{exc.code}") from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise RuntimeError("telegram_delivery_uncertain") from None
    except (ValueError, UnicodeError):
        raise RuntimeError("telegram_invalid_response") from None
    if result.get("ok") is not True:
        raise RuntimeError(f"telegram_api_{result.get('error_code', 'unknown')}")
    return result

def render_letter(telegram_id, first_name, last_name):
    name = " ".join(v.strip() for v in (first_name or "", last_name or "") if v and v.strip())
    name = html.escape(name or "участник")
    mention = f'<a href="tg://user?id={telegram_id}">{name}</a>'
    return (
        "🐾 <b>NYAN ELECTIONS | ЛИЧНОЕ ПИСЬМО</b>\n\n"
        f"Многоуважаемый {mention}!\n\n"
        "Благодарим вас за участие в голосовании Nyan Elections. "
        "Ваш голос учтён. В знак признательности на ваш кошелёк "
        "уже начислено <b>200 🐾</b>.\n\n"
        "Спасибо, что участвуете в жизни Nyan Wallet!\n\n"
        "С уважением, команда Nyan Wallet."
    )

def recipients(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM election_seasons ORDER BY id DESC LIMIT 1")
        row = cur.fetchone()
        if not row:
            raise RuntimeError("season_not_found")
        season = row[0]
        cur.execute("""
            SELECT v.telegram_id, u.first_name, u.last_name
              FROM election_votes v JOIN users u USING (telegram_id)
             WHERE v.season_id = %s ORDER BY v.telegram_id
        """, (season,))
        rows = cur.fetchall()
        if len(rows) != EXPECTED or len({r[0] for r in rows}) != EXPECTED:
            raise RuntimeError(f"voters_{len(rows)}_expected_{EXPECTED}")
        cur.execute("""
            SELECT count(DISTINCT v.telegram_id)
              FROM election_votes v
             WHERE v.season_id = %s
               AND EXISTS (
                SELECT 1 FROM transactions t
                 WHERE t.telegram_id = v.telegram_id
                   AND t.amount = 200
                   AND lower(coalesce(t.description, '')) LIKE '%%голосование в выборах%%'
               )
        """, (season,))
        paid = cur.fetchone()[0]
        if paid != EXPECTED:
            raise RuntimeError(f"credited_{paid}_expected_{EXPECTED}")
    return season, rows

def create_ledger(conn):
    with conn.cursor() as cur:
        cur.execute(f"""
            CREATE TABLE IF NOT EXISTS {LEDGER} (
                season_id integer NOT NULL,
                telegram_id bigint NOT NULL,
                status varchar(24) NOT NULL,
                attempted_at timestamptz NOT NULL,
                delivered_at timestamptz,
                message_id bigint,
                error_code varchar(80),
                PRIMARY KEY (season_id, telegram_id)
            )
        """)

def claim(conn, season, uid):
    # Commit BEFORE Telegram request: do not send twice after a timeout/crash.
    with conn.transaction():
        with conn.cursor() as cur:
            cur.execute(f"""
                INSERT INTO {LEDGER} (season_id, telegram_id, status, attempted_at)
                VALUES (%s, %s, 'attempted', now())
                ON CONFLICT (season_id, telegram_id) DO NOTHING
                RETURNING telegram_id
            """, (season, uid))
            return cur.fetchone() is not None

def finish(conn, season, uid, status, message_id, error):
    with conn.transaction():
        with conn.cursor() as cur:
            cur.execute(f"""
                UPDATE {LEDGER} SET status=%s, message_id=%s, error_code=%s,
                    delivered_at=CASE WHEN %s='sent' THEN now() ELSE NULL END
                WHERE season_id=%s AND telegram_id=%s AND status='attempted'
            """, (status, message_id, error, status, season, uid))

def main():
    arg = argparse.ArgumentParser()
    arg.add_argument("--send", action="store_true")
    live = arg.parse_args().send
    dsn = os.getenv("DATABASE_URL", "")
    token = os.getenv("BOT_TOKEN", "")
    if not dsn.startswith(("postgres://", "postgresql://", "postgresql+psycopg://")):
        print("STOP: DATABASE_URL missing or invalid")
        return 2
    if live and not token:
        print("STOP: BOT_TOKEN missing")
        return 2
    if dsn.startswith("postgresql+psycopg://"):
        dsn = dsn.replace("postgresql+psycopg://", "postgresql://", 1)
    stage = "connect"
    try:
        import psycopg
        with psycopg.connect(dsn, sslmode="require", connect_timeout=12, autocommit=True) as conn:
            stage = "recipient_precheck"
            season, rows = recipients(conn)
            print(f"PRECHECK: season={season} voters={len(rows)} credited={EXPECTED}")
            if not live:
                print("DRY RUN: no messages or database changes")
                return 0
            stage = "verify_telegram_bot"
            bot = bot_api(token, "getMe").get("result", {})
            if str(bot.get("username", "")).lower() != "nyancash_bot":
                print("STOP: expected @nyancash_bot; refusing to use another bot")
                return 2
            stage = "create_delivery_ledger"
            create_ledger(conn)
            stage = "delivery"
            counts = Counter()
            for uid, first, last in rows:
                if not claim(conn, season, uid):
                    counts["previous"] += 1
                    continue
                status, message_id, err = "uncertain", None, None
                try:
                    response = bot_api(token, "sendMessage", {
                        "chat_id": uid,
                        "text": render_letter(uid, first, last),
                        "parse_mode": "HTML",
                        "link_preview_options": {"is_disabled": True},
                    })
                    message_id = response.get("result", {}).get("message_id")
                    status = "sent" if isinstance(message_id, int) else "uncertain"
                except RuntimeError as exc:
                    err = str(exc)[:80]
                    status = "failed" if err in ("telegram_http_400", "telegram_http_403") else "uncertain"
                finish(conn, season, uid, status, message_id, err)
                counts[status] += 1
                time.sleep(0.4)
            with conn.cursor() as cur:
                cur.execute(f"SELECT status, count(*) FROM {LEDGER} WHERE season_id=%s GROUP BY status", (season,))
                history = dict(cur.fetchall())
            print("THIS_RUN:", json.dumps(counts, ensure_ascii=False, sort_keys=True))
            print("TOTAL_LEDGER:", json.dumps(history, ensure_ascii=False, sort_keys=True))
            return 0 if history.get("sent", 0) == EXPECTED else 1
    except Exception as exc:
        # psycopg exceptions may include a connection string; never print them.
        detail = str(exc) if isinstance(exc, RuntimeError) else "database_or_runtime_error"
        msg = str(exc).lower()
        if not isinstance(exc, RuntimeError):
            signatures = (
                ("password authentication failed", "bad_password"),
                ("no pg_hba.conf entry", "network_or_pg_hba_blocked"),
                ("name or service not known", "dns_resolution_failed"),
                ("could not translate host name", "dns_resolution_failed"),
                ("nodename nor servname provided", "dns_resolution_failed"),
                ("connection refused", "connection_refused"),
                ("timeout expired", "connection_timeout"),
                ("timed out", "connection_timeout"),
                ("certificate verify failed", "tls_certificate_verification"),
                ("ssl connection has been closed unexpectedly", "tls_peer_closed_early"),
                ("ssl syscall error", "tls_socket_error"),
                ("tlsv1 alert", "tls_alert"),
                ("does not support ssl", "server_has_no_tls"),
                ("sslmode", "tls_mode_invalid"),
                ("ssl", "tls_error"),
                ("does not exist", "database_or_schema_not_found"),
                ("permission denied", "permission_denied"),
            )
            detail = next((label for signature, label in signatures if signature in msg), "database_or_runtime_error")
        sqlstate = getattr(exc, "sqlstate", None)
        if stage == "connect":
            from urllib.parse import urlsplit, parse_qs
            import socket
            u = urlsplit(dsn)
            hostname = u.hostname or ""
            query = parse_qs(u.query)
            print(f"CONNECTION_CONFIG: render_host={hostname.endswith('.render.com')} internal_host={hostname.endswith('.internal')} port={u.port or 5432} sslmode={query.get('sslmode', ['unset'])[0]} password_present={bool(u.password)}")
            try:
                answers = socket.getaddrinfo(hostname, u.port or 5432, type=socket.SOCK_STREAM)
                print("DNS_CHECK:", "ok" if answers else "empty", "IPv4", any(row[0] == socket.AF_INET for row in answers), "IPv6", any(row[0] == socket.AF_INET6 for row in answers))
            except OSError:
                print("DNS_CHECK: failed")
        print(f"STOP: stage={stage} type={type(exc).__name__} category={detail} sqlstate={sqlstate or 'none'}")
        return 2

if __name__ == "__main__":
    sys.exit(main())
