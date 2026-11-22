#!/usr/bin/env python3
"""Owner CLI: stock all 14 products and open the existing shop, once per key.

Uses only the active service's database, without importing server startup code.
Balances, sales counters, purchases and notifications are never rewritten.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

SERVICE = "nyan-wallet"
CATALOG_URL = "http://127.0.0.1:8000/api/nyan-lavka/catalog"
SKUS = ("hint", "chance", "box", "ticket", "key", "letter", "time", "shield",
        "compass", "magnifier", "map", "crystal", "potion", "charm")


def service_value(name: str) -> str:
    result = subprocess.run(
        ["systemctl", "show", SERVICE, "-p", name, "--value"],
        check=True, capture_output=True, text=True,
    )
    return result.stdout.strip()


def utc(value):
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def activate(engine, stock: int, minutes: int, operation_key: str):
    """One transaction, same window/item lock order as the purchase endpoint."""
    from sqlalchemy import Column, DateTime, Integer, MetaData, String, Table, Text, select
    if not 1 <= stock <= 100000 or not 5 <= minutes <= 180:
        raise ValueError("Остаток: 1–100000, время: 5–180 минут")
    if not operation_key or len(operation_key) > 100:
        raise ValueError("Неверный ключ операции")

    metadata = MetaData()
    window = Table("nyan_lavka_window", metadata, autoload_with=engine)
    items = Table("nyan_lavka_items", metadata, autoload_with=engine)
    audit = Table(
        "nyan_lavka_admin_actions", metadata,
        Column("operation_key", String(100), primary_key=True),
        Column("stock", Integer, nullable=False),
        Column("minutes", Integer, nullable=False),
        Column("created_at", DateTime(timezone=True), nullable=False),
        Column("before_json", Text, nullable=False),
        Column("result_json", Text, nullable=False),
    )
    with engine.begin() as conn:
        # PostgreSQL serializes DDL and repeated CLI calls before table creation.
        if engine.dialect.name == "postgresql":
            from sqlalchemy import text
            conn.execute(text("SELECT pg_advisory_xact_lock(692235141)"))
        audit.create(conn, checkfirst=True)
        current = conn.execute(select(window).where(window.c.id == 1).with_for_update()).mappings().one_or_none()
        if current is None:
            raise RuntimeError("Лавка не установлена. Сначала выполни предыдущую команду установки")
        previous = conn.execute(select(audit).where(audit.c.operation_key == operation_key)).mappings().one_or_none()
        if previous:
            if previous["stock"] != stock or previous["minutes"] != minutes:
                raise RuntimeError("Этот ключ уже использован с другими параметрами")
            return {**json.loads(previous["result_json"]), "already_applied": True}
        rows = conn.execute(
            select(items).where(items.c.sku.in_(SKUS)).order_by(items.c.sku).with_for_update()
        ).mappings().all()
        if {row["sku"] for row in rows} != set(SKUS):
            raise RuntimeError("В API должна быть установлена версия со всеми 14 товарами")
        now = datetime.now(timezone.utc)
        before = {
            "window": {name: utc(current[name]).isoformat() if current[name] else None
                       for name in ("opened_at", "closes_at", "stopped_at")},
            "items": [{"sku": row["sku"], "total": row["total"], "sold": row["sold"]} for row in rows],
        }
        for row in rows:
            conn.execute(
                items.update().where(items.c.sku == row["sku"]).values(
                    total=max(row["total"], row["sold"] + stock)
                )
            )
        opened_at = utc(current["opened_at"])
        if opened_at is None or opened_at > now:
            opened_at = now
        closes_at = now + timedelta(minutes=minutes)
        conn.execute(window.update().where(window.c.id == 1).values(
            opened_at=opened_at, closes_at=closes_at, stopped_at=None,
        ))
        result = {"items": len(rows), "minimum_remaining": stock,
                  "closes_at": closes_at.isoformat(), "already_applied": False}
        conn.execute(audit.insert().values(
            operation_key=operation_key, stock=stock, minutes=minutes,
            created_at=now, before_json=json.dumps(before, ensure_ascii=False),
            result_json=json.dumps(result, ensure_ascii=False),
        ))
    return result


def catalog():
    with urllib.request.urlopen(CATALOG_URL, timeout=10) as response:
        result = json.load(response)
    if not result.get("ok") or not set(SKUS).issubset({item["sku"] for item in result.get("items", [])}):
        raise RuntimeError("Сначала установи обновлённую лавку предыдущей командой")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stock", type=int, default=35)
    parser.add_argument("--minutes", type=int, default=180)
    parser.add_argument("--operation-key", default="lavka-stock35-open-20261122-v1")
    args = parser.parse_args()
    if os.geteuid() != 0:
        raise RuntimeError("Запусти команду под root в Termius")
    if service_value("ActiveState") != "active":
        raise RuntimeError("Сервис nyan-wallet не запущен")
    project = Path(service_value("WorkingDirectory"))
    if not project.is_absolute() or not (project / "server/backend_app.py").is_file():
        raise RuntimeError("Не найден рабочий каталог запущенного Nyan Wallet")
    # Always use the wallet's own Python environment when present.
    for directory in (project / ".venv", project / "venv"):
        python = directory / "bin/python"
        if python.is_file():
            if Path(sys.prefix).resolve() != directory.resolve():
                os.execv(str(python), [str(python), str(Path(__file__).resolve()), *sys.argv[1:]])
            break
    if importlib.util.find_spec("sqlalchemy") is None:
        raise RuntimeError("Не найден SQLAlchemy в окружении кошелька")
    pid = service_value("MainPID")
    if not pid.isdigit() or int(pid) <= 0:
        raise RuntimeError("Не найден процесс работающего API")
    running = dict(entry.split(b"=", 1) for entry in Path(f"/proc/{pid}/environ").read_bytes().split(b"\0") if b"=" in entry)
    database_url = running.get(b"DATABASE_URL", b"").decode("utf-8").strip()
    if not database_url.startswith(("postgres://", "postgresql://", "postgresql+psycopg://")):
        raise RuntimeError("Не найдена PostgreSQL база в окружении работающего API")
    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql+psycopg://", 1)
    elif database_url.startswith("postgresql://"):
        database_url = database_url.replace("postgresql://", "postgresql+psycopg://", 1)
    catalog()  # Fail before a database write if the API has not been installed.
    from sqlalchemy import create_engine
    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        result = activate(engine, args.stock, args.minutes, args.operation_key)
    finally:
        engine.dispose()
    state = catalog()
    if result["already_applied"]:
        print("Эта команда уже выполнена. Остатки повторно не пополнялись, таймер не продлевался")
    if not state["is_open"]:
        raise RuntimeError("Лавка сейчас закрыта. Эта операция уже могла завершиться по таймеру")
    end = datetime.fromisoformat(state["closes_at"]).astimezone(ZoneInfo("Europe/Moscow"))
    print(f"Лавка открыта до {end:%d.%m %H:%M} МСК")
    print(f"Товаров: {result['items']}. При открытии выставлено не меньше {result['minimum_remaining']} каждого")
    print("https://t.me/nyancash_bot?startapp=nyan_lavka")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (RuntimeError, ValueError) as error:
        print("ОШИБКА:", error, file=sys.stderr)
        sys.exit(1)
    except Exception as error:
        # Database connection details and service credentials must stay private.
        print(f"Операция не завершена ({type(error).__name__}). Можно безопасно повторить ту же команду", file=sys.stderr)
        sys.exit(1)
