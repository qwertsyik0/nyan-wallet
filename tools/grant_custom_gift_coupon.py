#!/usr/bin/env python3
"""Owner CLI for explicit random/improved gift request IDs and a persistent prize ledger."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import secrets
import string
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

EXPECTED = {}
PLANNED = {}


def stamp():
    return datetime.now(timezone.utc)


def tables(engine):
    from sqlalchemy import BigInteger, Column, DateTime, Integer, MetaData, String, Table, Text
    meta = MetaData()
    result = {
        name: Table(name, meta, autoload_with=engine, resolve_fks=False)
        for name in ("users", "spend_requests", "transactions", "wallet_notifications",
                     "spend_request_meta", "admin_audit")
    }
    result["awards"] = Table(
        "nyan_gift_prize_awards", meta,
        Column("request_id", Integer, primary_key=True),
        Column("telegram_id", BigInteger, nullable=False),
        Column("kind", String(32), nullable=False),
        Column("code", String(7), nullable=True, unique=True),
        Column("payload", Text, nullable=False),
        Column("description", Text, nullable=False),
        Column("created_at", DateTime(timezone=True), nullable=False),
        Column("redeemed_at", DateTime(timezone=True), nullable=True),
        Column("first_state", String(16), nullable=False),
        Column("second_state", String(16), nullable=False),
        Column("first_message_id", BigInteger, nullable=True),
        Column("second_message_id", BigInteger, nullable=True),
    )
    return result



def grant(engine, user_id, operation_key):
    from sqlalchemy import MetaData, Table, select, text
    t = tables(engine)
    outbox = Table("telegram_relay_outbox", MetaData(), autoload_with=engine)
    a, r, u = t["awards"], t["spend_requests"], t["users"]
    key = f"{operation_key}:{user_id}"
    with engine.begin() as conn:
        if engine.dialect.name == "postgresql":
            conn.execute(text("SELECT pg_advisory_xact_lock(692235142)"))
        a.create(conn, checkfirst=True)
        prior = conn.execute(select(a).where(a.c.telegram_id == user_id, a.c.kind == "custom_coupon")).mappings()
        for row in prior:
            if json.loads(row["payload"]).get("operation_key") == key:
                return row["request_id"], row["code"], True
        request = conn.execute(select(r).where(
            r.c.telegram_id == user_id, r.c.status == "pending",
            r.c.reward_title.contains("Случайный подарок"),
        ).order_by(r.c.id).limit(1).with_for_update()).mappings().one_or_none()
        if request is None:
            raise RuntimeError("У пользователя нет ожидающей заявки на случайный подарок")
        user = conn.execute(select(u).where(u.c.telegram_id == user_id).with_for_update()).mappings().one_or_none()
        if user is None:
            raise RuntimeError("Кошелёк пользователя не найден")
        rid = request["id"]
        if conn.execute(select(a.c.request_id).where(a.c.request_id == rid)).first():
            raise RuntimeError("Для этой заявки уже зарегистрирован приз")
        while True:
            code = "#" + "".join(secrets.choice(string.ascii_uppercase) for _ in range(6))
            if not conn.execute(select(a.c.request_id).where(a.c.code == code)).first():
                break
        now = stamp()
        description = (
            f"Твой приз: скидка 30% на любой аккаунт в Нян Шопе.\n"
            f"При покупке от 200 ₽ дополнительно получишь ФИЗ США в подарок.\n\n"
            f"Твой одноразовый промокод: {code}\n"
            "Предъяви его поддержке Нян Шопа перед оплатой. Код закреплён за твоим аккаунтом."
        )
        payload = {"kind": "custom_coupon", "percent": 30, "scope": "any_account",
                   "bonus": "physical_us_account", "purchase_from_rub": 200,
                   "operation_key": key, "code": code}
        conn.execute(a.insert().values(
            request_id=rid, telegram_id=user_id, kind="custom_coupon", code=code,
            payload=json.dumps(payload, ensure_ascii=False), description=description,
            created_at=now, first_state="queued", second_state="queued"))
        conn.execute(r.update().where(r.c.id == rid).values(status="fulfilled", processed_at=now))
        meta = t["spend_request_meta"]
        previous = conn.execute(select(meta).where(meta.c.request_id == rid)).mappings().one_or_none()
        comment = ((previous["owner_comment"] + "\n") if previous and previous["owner_comment"] else "") + description
        if previous:
            conn.execute(meta.update().where(meta.c.request_id == rid).values(owner_comment=comment, updated_at=now))
        else:
            conn.execute(meta.insert().values(request_id=rid, owner_comment=comment, updated_at=now))
        for suffix, kind, title, body in (
            ("status", "reward_status", "Заявка выполнена", f"Заявка #{rid} на случайный подарок выполнена."),
            ("prize", "gift_prize", "Твой приз", f"Награда по заявке #{rid}\n{description}"),
        ):
            conn.execute(t["wallet_notifications"].insert().values(
                telegram_id=user_id, kind=kind, title=title, body=body, is_read=False, created_at=now))
            conn.execute(outbox.insert().values(
                source_key=f"custom-gift:{rid}:{suffix}", chat_id=user_id,
                body=body, state="pending", attempts=0, created_at=now))
        conn.execute(t["admin_audit"].insert().values(
            action="custom_gift_coupon", target_telegram_id=user_id,
            details=json.dumps({"request_id": rid, "prize": payload}, ensure_ascii=False), created_at=now))
    return rid, code, False


def service_value(name):
    return subprocess.check_output(
        ["systemctl", "show", "nyan-wallet", "-p", name, "--value"], text=True).strip()


def main():
    parser = argparse.ArgumentParser(description="Выдать один специальный приз за случайный подарок")
    parser.add_argument("--user", type=int, required=True)
    parser.add_argument("--operation-key", default="discount30-usgift-20261122")
    args = parser.parse_args()
    if args.user <= 0 or not args.operation_key or len(args.operation_key) > 70:
        raise RuntimeError("Некорректные параметры операции")
    if os.geteuid() != 0:
        raise RuntimeError("Запусти под root в Termius на VPS кошелька")
    if service_value("ActiveState") != "active":
        raise RuntimeError("Сервис кошелька не active")
    root = Path(service_value("WorkingDirectory"))
    if not root.is_absolute() or not (root / "server/backend_app.py").is_file():
        raise RuntimeError("Не найден активный проект кошелька")
    for folder in (root / ".venv", root / "venv"):
        python = folder / "bin/python"
        if python.is_file():
            if Path(sys.prefix).resolve() != folder.resolve():
                os.execv(str(python), [str(python), str(Path(__file__).resolve()), *sys.argv[1:]])
            break
    pid = service_value("MainPID")
    if not pid.isdigit() or int(pid) <= 0:
        raise RuntimeError("Не найден процесс API")
    env = dict(part.split(b"=", 1) for part in Path(f"/proc/{pid}/environ").read_bytes().split(b"\0") if b"=" in part)
    from dotenv import dotenv_values
    settings = dotenv_values(root / ".env")
    if not (env.get(b"NYAN_TELEGRAM_RELAY_SECRET") or settings.get("NYAN_TELEGRAM_RELAY_SECRET")):
        raise RuntimeError("Очередь Telegram не подключена, выдача не начата")
    url = env.get(b"DATABASE_URL", b"").decode().strip()
    if not url.startswith(("postgres://", "postgresql://", "postgresql+psycopg://")):
        raise RuntimeError("Не найдена PostgreSQL база запущенного API")
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            url = url.replace(prefix, "postgresql+psycopg://", 1)
            break
    from sqlalchemy import create_engine
    engine = create_engine(url, pool_pre_ping=True)
    try:
        rid, code, repeated = grant(engine, args.user, args.operation_key)
        print("Приз уже был выдан" if repeated else "Приз зарегистрирован, заявка закрыта")
        print(f"Заявка #{rid}; промокод {code}")
        print("Скидка 30% на любой аккаунт; при покупке от 200 ₽ ФИЗ США в подарок")
        print("Два уведомления сохранены в кошельке, сообщения поставлены в очередь бота")
    finally:
        engine.dispose()


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, ValueError) as error:
        print("ОШИБКА:", error, file=sys.stderr)
        sys.exit(1)
    except Exception as error:
        print(f"Ошибка {type(error).__name__}; повторный запуск защищён от повторной выдачи", file=sys.stderr)
        sys.exit(1)
