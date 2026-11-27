#!/usr/bin/env python3
"""Issue six owner-selected prizes. Ticket request 95 is deliberately excluded."""
import json
import os
import subprocess
import sys
from pathlib import Path
from datetime import datetime, timezone

PLAN = {
    110: (6188280497, 450, {"kind": "poem", "text": "Пусть солнце светит сквозь туман,\nПусть сбудется заветный план.\nПусть каждый новый день несёт\nТепло, удачу и полёт."}),
    111: (5414078028, 800, {"kind": "discount", "percent": 30, "code": "#ZQMVKA"}),
    112: (7235315034, 450, {"kind": "lapcoins", "amount": 500}),
    114: (7182981127, 450, {"kind": "us_bonus", "purchase_from_rub": 150, "code": "#RXTNLP"}),
    118: (6968551476, 800, {"kind": "lapcoins", "amount": 1000}),
    120: (1129986805, 450, {"kind": "discount", "percent": 15, "code": "#WFKJSD"}),
}
BATCH = "owner-prizes-20261127-v1"

def description(p):
    if p["kind"] == "lapcoins":
        return f"Твой приз: {p['amount']} лапкоинов. Они начислены на баланс Nyan Wallet."
    if p["kind"] == "discount":
        return (f"Твой приз: скидка {p['percent']}% на одну покупку аккаунта в Nyan Shop. "
                f"Одноразовый код: {p['code']}. Код закреплён за тобой. "
                "Предъяви его поддержке перед оплатой. Код применяется поддержкой вручную.")
    if p["kind"] == "us_bonus":
        return ("Твой приз: ФИЗ США в подарок при покупке аккаунта от 150 ₽. "
                f"Одноразовый код: {p['code']}. Код закреплён за тобой. "
                "Предъяви его поддержке перед оплатой. Код применяется поддержкой вручную.")
    return "Твой приз: четверостишье.\n\n" + p["text"]

def award_table(meta):
    from sqlalchemy import Table, Column, Integer, BigInteger, String, Text, DateTime
    return Table("nyan_gift_prize_awards", meta,
        Column("request_id", Integer, primary_key=True),
        Column("telegram_id", BigInteger, nullable=False),
        Column("kind", String(32), nullable=False),
        Column("code", String(7), unique=True),
        Column("payload", Text, nullable=False),
        Column("description", Text, nullable=False),
        Column("created_at", DateTime(timezone=True), nullable=False),
        Column("redeemed_at", DateTime(timezone=True)),
        Column("first_state", String(16), nullable=False),
        Column("second_state", String(16), nullable=False),
        Column("first_message_id", BigInteger),
        Column("second_message_id", BigInteger))

def fulfil(engine):
    from sqlalchemy import MetaData, Table, select, text, inspect
    meta = MetaData()
    names = ("users", "spend_requests", "transactions", "wallet_notifications",
             "spend_request_meta", "admin_audit", "telegram_relay_outbox")
    t = {name: Table(name, meta, autoload_with=engine, resolve_fks=False) for name in names}
    awards = award_table(meta)
    result = []
    with engine.begin() as c:
        if engine.dialect.name == "postgresql":
            c.execute(text("SELECT pg_advisory_xact_lock(692235142)"))
        awards.create(c, checkfirst=True)
        req, users = t["spend_requests"], t["users"]
        rows = {r["id"]: r for r in c.execute(
            select(req).where(req.c.id.in_(PLAN)).order_by(req.c.id).with_for_update()).mappings()}
        wallets = {r["telegram_id"]: r for r in c.execute(
            select(users).where(users.c.telegram_id.in_(sorted(v[0] for v in PLAN.values())))
            .order_by(users.c.telegram_id).with_for_update()).mappings()}
        gifts = None
        if inspect(c).has_table("prize_gifts"):
            gifts = Table("prize_gifts", MetaData(), autoload_with=c, resolve_fks=False)
        for rid, (uid, cost, prize) in PLAN.items():
            if rid not in rows or uid not in wallets:
                raise RuntimeError(f"Не найдена заявка #{rid} или её кошелёк")
            r = rows[rid]
            word = "Улучшенный подарок" if cost == 800 else "Случайный подарок"
            if (r["telegram_id"], r["cost"]) != (uid, cost) or word not in r["reward_title"]:
                raise RuntimeError(f"Заявка #{rid} отличается от согласованной")
            if gifts is not None:
                gift = c.execute(select(gifts).where(gifts.c.request_id == rid)).mappings().first()
                if gift and gift["recipient_id"] != uid:
                    raise RuntimeError(f"#{rid} куплена другому получателю. Выдача отменена, проверь получателя")
            payload = dict(prize, batch=BATCH)
            prior = c.execute(select(awards).where(awards.c.request_id == rid)).mappings().first()
            if prior:
                if prior["telegram_id"] != uid or json.loads(prior["payload"]) != payload:
                    raise RuntimeError(f"#{rid}: уже записан другой приз")
                if r["status"] != "fulfilled":
                    raise RuntimeError(f"#{rid}: приз записан, но статус отличается; нужна проверка")
                result.append(f"#{rid}: ранее выдано, без повторения")
                continue
            if r["status"] != "pending":
                raise RuntimeError(f"#{rid}: статус уже {r['status']}, выдача отменена")
            code = prize.get("code")
            if code:
                if len(code) > 7 or c.execute(select(awards.c.request_id).where(awards.c.code == code)).first():
                    raise RuntimeError(f"Код {code} уже занят; ничего не выдано")
            now = datetime.now(timezone.utc)
            body = description(prize)
            amount = prize.get("amount", 0)
            if amount:
                c.execute(users.update().where(users.c.telegram_id == uid).values(balance=users.c.balance + amount))
                c.execute(t["transactions"].insert().values(
                    telegram_id=uid, amount=amount, operation_type="gift_prize",
                    description=f"Приз за подарок #{rid}: {amount} лапкоинов", created_at=now))
            c.execute(awards.insert().values(
                request_id=rid, telegram_id=uid, kind=prize["kind"], code=code,
                payload=json.dumps(payload, ensure_ascii=False), description=body,
                created_at=now, first_state="queued", second_state="queued"))
            c.execute(req.update().where(req.c.id == rid).values(status="fulfilled", processed_at=now))
            mt = t["spend_request_meta"]
            previous = c.execute(select(mt).where(mt.c.request_id == rid)).mappings().first()
            comment = ((previous["owner_comment"] or "") + "\n" if previous else "") + body
            if previous:
                c.execute(mt.update().where(mt.c.request_id == rid).values(owner_comment=comment, updated_at=now))
            else:
                c.execute(mt.insert().values(request_id=rid, owner_comment=comment, updated_at=now))
            for suffix, title, message in (
                ("status", "Подарок выдан", f"Подарок #{rid} выдан."),
                ("prize", "Твой приз", body)):
                c.execute(t["wallet_notifications"].insert().values(
                    telegram_id=uid, kind="gift_prize", title=title,
                    body=message, is_read=False, created_at=now))
                c.execute(t["telegram_relay_outbox"].insert().values(
                    source_key=f"{BATCH}:{rid}:{suffix}", chat_id=uid,
                    body=message, state="pending", attempts=0, created_at=now))
            c.execute(t["admin_audit"].insert().values(
                action="gift_prize_fulfilled", target_telegram_id=uid,
                details=json.dumps({"request_id": rid, "prize": payload}, ensure_ascii=False),
                created_at=now))
            result.append(f"#{rid} | ID {uid} | {body}")
    return result

def service(key):
    return subprocess.check_output(
        ["systemctl", "show", "nyan-wallet", "-p", key, "--value"], text=True).strip()

def main():
    if "--apply" not in sys.argv:
        raise RuntimeError("Для выдачи добавь --apply")
    if os.geteuid() != 0 or service("ActiveState") != "active":
        raise RuntimeError("Запусти под root на VPS работающего кошелька")
    root = Path(service("WorkingDirectory"))
    if not root.is_absolute() or not (root / "server/backend_app.py").is_file():
        raise RuntimeError("Не найдена папка активного API")
    for name in (".venv", "venv"):
        folder = root / name
        python = folder / "bin/python"
        if python.is_file():
            if Path(sys.prefix).resolve() != folder.resolve():
                os.execv(str(python), [str(python), str(Path(__file__).resolve()), *sys.argv[1:]])
            break
    pid = service("MainPID")
    if not pid.isdigit() or int(pid) <= 0:
        raise RuntimeError("Не найден активный процесс")
    runtime = dict(item.decode().split("=", 1)
        for item in Path(f"/proc/{pid}/environ").read_bytes().split(b"\0") if b"=" in item)
    from dotenv import dotenv_values
    cfg = {**dotenv_values(root / ".env"), **runtime}
    if not cfg.get("NYAN_TELEGRAM_RELAY_SECRET"):
        raise RuntimeError("Очередь Telegram не настроена; выдача не начата")
    url = cfg.get("DATABASE_URL") or ""
    if not url.startswith(("postgres://", "postgresql://", "postgresql+psycopg://")):
        raise RuntimeError("Не найдена PostgreSQL база API")
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            url = url.replace(prefix, "postgresql+psycopg://", 1)
            break
    from sqlalchemy import create_engine
    engine = create_engine(url, pool_pre_ping=True)
    try:
        for line in fulfil(engine):
            print(line)
        print("Готово. Уведомления в кошельке, сообщения в очереди бота. Билет #95 не изменён.")
    finally:
        engine.dispose()

if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print("ОШИБКА: выдача не завершена. Тип: " + type(error).__name__, file=sys.stderr)
        if isinstance(error, RuntimeError):
            print(str(error), file=sys.stderr)
        sys.exit(1)
