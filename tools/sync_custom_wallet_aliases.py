#!/usr/bin/env python3
"""Synchronize installed custom wallet numbers with transfer aliases, atomically."""
import os
import argparse
from pathlib import Path
import subprocess
import sys
from datetime import datetime, timezone

def service_value(name):
    return subprocess.check_output(
        ["systemctl", "show", "nyan-wallet", "-p", name, "--value"],
        text=True).strip()

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--user', type=int, help='Synchronize only this wallet')
    args = parser.parse_args()
    if os.geteuid() != 0:
        raise RuntimeError("запусти под root на VPS кошелька")
    if service_value("ActiveState") != "active":
        raise RuntimeError("сервис кошелька не запущен")
    root = Path(service_value("WorkingDirectory"))
    if not root.is_absolute() or not (root / "server/backend_app.py").is_file():
        raise RuntimeError("папка API не найдена")
    for folder in (root / ".venv", root / "venv"):
        python = folder / "bin/python"
        if python.is_file():
            if Path(sys.prefix).resolve() != folder.resolve():
                os.execv(str(python), [str(python), str(Path(__file__).resolve()), *sys.argv[1:]])
            break
    pid = service_value("MainPID")
    if not pid.isdigit() or int(pid) < 1:
        raise RuntimeError("процесс API не найден")
    env = dict(item.split(b"=", 1) for item in
               Path(f"/proc/{pid}/environ").read_bytes().split(b"\0") if b"=" in item)
    from dotenv import dotenv_values
    url = env.get(b"DATABASE_URL", b"").decode().strip() or dotenv_values(root / ".env").get("DATABASE_URL")
    if not url or not url.startswith(("postgres://", "postgresql://", "postgresql+psycopg://")):
        raise RuntimeError("PostgreSQL активного API не найден")
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            url = url.replace(prefix, "postgresql+psycopg://", 1)
            break
    from sqlalchemy import create_engine, text
    engine = create_engine(url)
    results = []
    try:
        with engine.begin() as conn:
            conn.execute(text("SELECT pg_advisory_xact_lock(692235143)"))
            conn.execute(text("LOCK TABLE wallet_aliases IN SHARE ROW EXCLUSIVE MODE"))
            rows = conn.execute(text("""
                SELECT telegram_id, number FROM wallet_custom_numbers
                WHERE (:uid IS NULL OR telegram_id=:uid)
                ORDER BY telegram_id FOR UPDATE
            """), {"uid": args.user}).mappings().all()
            if args.user is not None and not rows:
                raise RuntimeError("у указанного пользователя нет установленного номера")
            for row in rows:
                uid, number = row["telegram_id"], row["number"]
                if len(number) != 12 or not number.isascii() or not number.isdigit() or number == "777777777777":
                    raise RuntimeError("некорректный или зарезервированный номер; всё отменено")
                alias = "NYAN" + number
                other = conn.execute(text(
                    "SELECT telegram_id FROM wallet_aliases WHERE alias=:alias"
                ), {"alias": alias}).scalar_one_or_none()
                if other is not None and int(other) != int(uid):
                    raise RuntimeError(f"номер {alias} для ID {uid} уже принадлежит адресу переводов ID {other}; ничего не изменено")
                current = conn.execute(text(
                    "SELECT alias FROM wallet_aliases WHERE telegram_id=:uid"
                ), {"uid": uid}).scalar_one_or_none()
                if current != alias:
                    conn.execute(text("""
                        INSERT INTO wallet_aliases (telegram_id, alias, created_at)
                        VALUES (:uid, :alias, :now)
                        ON CONFLICT (telegram_id) DO UPDATE SET alias=excluded.alias
                    """), {"uid": uid, "alias": alias, "now": datetime.now(timezone.utc)})
                    conn.execute(text("""
                        INSERT INTO admin_audit (action, target_telegram_id, details, created_at)
                        VALUES ('wallet_alias_sync', :uid, :details, :now)
                    """), {"uid": uid, "details": f"Адрес переводов синхронизирован с номером {alias}",
                            "now": datetime.now(timezone.utc)})
                verified = conn.execute(text(
                    "SELECT telegram_id FROM wallet_aliases WHERE alias=:alias"
                ), {"alias": alias}).scalar_one()
                if int(verified) != int(uid):
                    raise RuntimeError("проверка не прошла, всё отменено")
                results.append((uid, number, current != alias))
        for uid, number, changed in results:
            formatted = " ".join(number[i:i+4] for i in range(0, 12, 4))
            print(f"ID {uid} | NYAN {formatted} | " + ("исправлено" if changed else "уже работает"))
        print("синхронизация завершена; балансы и заявки не изменялись")
    finally:
        engine.dispose()

if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        raise SystemExit("ошибка: " + str(error))
