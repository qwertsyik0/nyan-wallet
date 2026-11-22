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


def draw(improved):
    rng = secrets.SystemRandom()
    kind = rng.choices(
        ["lapcoins", "discount", "cashback", "warranty", "replacement", "background", "badge", "bundle"],
        weights=[60, 18, 5, 4, 2, 3, 3, 5] if improved else [72, 15, 3, 3, 1, 2, 2, 2],
    )[0]
    if kind == "lapcoins":
        return {"kind": kind, "amount": rng.randrange(400, 1301, 50) if improved else rng.randrange(150, 701, 50)}
    if kind == "discount":
        return {"kind": kind, "percent": rng.choice([10, 15, 20] if improved else [5, 10])}
    if kind == "bundle":
        return {"kind": kind, "amount": rng.choice([200, 300, 400] if improved else [100, 150, 200]),
                "percent": rng.choice([10, 15] if improved else [5, 10])}
    if kind == "warranty":
        return {"kind": kind, "days": 7 if improved else 3}
    return {"kind": kind}


def describe(prize, request_id):
    kind = prize["kind"]
    claim = f"Для получения обратись в поддержку Nyan Shop и назови номер заявки #{request_id}."
    if kind == "lapcoins":
        return f"Твой приз: {prize['amount']} лапкоинов. Они уже начислены на баланс Nyan Wallet."
    if kind in {"discount", "bundle"}:
        message = f"Твой приз: скидка {prize['percent']}% на покупку аккаунта в Nyan Shop. Одноразовый промокод: {prize['code']}. Предъяви код поддержке перед оплатой."
        if kind == "bundle":
            message += f"\nДополнительно начислено {prize['amount']} лапкоинов на баланс Nyan Wallet."
        return message
    labels = {
        "cashback": "удвоенный кэшбэк лапкоинами за одну следующую покупку",
        "warranty": f"дополнительные {prize.get('days', 3)} дня гарантии на одну покупку аккаунта",
        "replacement": "бесплатная замена одного аккаунта один раз",
        "background": "уникальный фон карточки Nyan Wallet",
        "badge": "значок рядом с ником в Nyan Wallet",
    }
    return "Твой приз: " + labels[kind] + ".\n" + claim


def validate_prize(prize):
    kind = prize.get("kind")
    if kind not in {"lapcoins", "discount", "cashback", "warranty", "replacement", "background", "badge", "bundle"}:
        raise RuntimeError("Неизвестный вид приза")
    if kind in {"lapcoins", "bundle"} and (type(prize.get("amount")) is not int or not 1 <= prize["amount"] <= 1300):
        raise RuntimeError("Неверная сумма приза")
    if kind in {"discount", "bundle"} and (type(prize.get("percent")) is not int or not 1 <= prize["percent"] <= 20):
        raise RuntimeError("Скидка должна быть не больше 20%")


def fulfil(engine, chooser=draw):
    from sqlalchemy import select, text
    t = tables(engine)
    r, u, a = t["spend_requests"], t["users"], t["awards"]
    result = []
    with engine.begin() as conn:
        if engine.dialect.name == "postgresql":
            conn.execute(text("SELECT pg_advisory_xact_lock(692235142)"))
        a.create(conn, checkfirst=True)
        rows = conn.execute(select(r).where(r.c.id.in_(EXPECTED)).order_by(r.c.id).with_for_update()).mappings().all()
        users = {
            row["telegram_id"]: row for row in conn.execute(
                select(u).where(u.c.telegram_id.in_(sorted({row["telegram_id"] for row in rows})))
                .order_by(u.c.telegram_id).with_for_update()
            ).mappings()
        }
        for row in rows:
            request_id = row["id"]
            prior = conn.execute(select(a).where(a.c.request_id == request_id)).mappings().one_or_none()
            if prior or row["status"] != "pending":
                result.append((request_id, "уже обработана, пропуск"))
                continue
            expected_user, expected_cost = EXPECTED[request_id] or (row["telegram_id"], row["cost"])
            if expected_cost not in (450, 800):
                raise RuntimeError(f"Заявка #{request_id}: стоимость подарка изменилась, выдача отменена")
            gift_word = "Улучшенный подарок" if expected_cost == 800 else "Случайный подарок"
            if (row["telegram_id"], row["cost"]) != (expected_user, expected_cost) or gift_word not in row["reward_title"]:
                raise RuntimeError(f"Заявка #{request_id} не соответствует проверенному списку. Выдача отменена")
            if expected_user not in users:
                raise RuntimeError(f"Не найден кошелёк для заявки #{request_id}")
            prize = dict(PLANNED[request_id]) if request_id in PLANNED else dict(chooser(expected_cost == 800))
            validate_prize(prize)
            if prize["kind"] in {"discount", "bundle"}:
                code = prize.get("code")
                if code and conn.execute(select(a.c.request_id).where(a.c.code == code)).first():
                    code = None
                while not code:
                    candidate = "#" + "".join(secrets.choice(string.ascii_uppercase) for _ in range(6))
                    if not conn.execute(select(a.c.request_id).where(a.c.code == candidate)).first():
                        code = candidate
                if len(code) != 7 or code[0] != "#" or any(c not in string.ascii_uppercase for c in code[1:]):
                    raise RuntimeError("Неверный формат промокода")
                prize["code"] = code
            now = stamp()
            description = describe(prize, request_id)
            amount = prize.get("amount", 0)
            if amount:
                conn.execute(u.update().where(u.c.telegram_id == expected_user).values(balance=u.c.balance + amount))
                conn.execute(t["transactions"].insert().values(
                    telegram_id=expected_user, amount=amount, operation_type="gift_prize",
                    description=f"Приз по заявке #{request_id}: {amount} лапкоинов", created_at=now,
                ))
            conn.execute(a.insert().values(
                request_id=request_id, telegram_id=expected_user, kind=prize["kind"], code=prize.get("code"),
                payload=json.dumps(prize, ensure_ascii=False), description=description, created_at=now,
                first_state="pending", second_state="pending",
            ))
            conn.execute(r.update().where(r.c.id == request_id).values(status="fulfilled", processed_at=now))
            meta = t["spend_request_meta"]
            old = conn.execute(select(meta).where(meta.c.request_id == request_id)).mappings().one_or_none()
            comment = ((old["owner_comment"] + "\n") if old and old["owner_comment"] else "") + description
            if old:
                conn.execute(meta.update().where(meta.c.request_id == request_id).values(owner_comment=comment, updated_at=now))
            else:
                conn.execute(meta.insert().values(request_id=request_id, owner_comment=comment, updated_at=now))
            for kind, title, body in (
                ("reward_status", "Заявка выполнена", f"Заявка #{request_id} на {row['reward_title']} выполнена."),
                ("gift_prize", "Твой приз", f"Награда по заявке #{request_id}\n{description}"),
            ):
                conn.execute(t["wallet_notifications"].insert().values(
                    telegram_id=expected_user, kind=kind, title=title, body=body,
                    is_read=False, created_at=now,
                ))
            conn.execute(t["admin_audit"].insert().values(
                action="gift_prize_fulfilled", target_telegram_id=expected_user,
                details=json.dumps({"request_id": request_id, "prize": prize}, ensure_ascii=False), created_at=now,
            ))
            result.append((request_id, description))
    return result


def send_telegram(token, recipient, body):
    payload = urllib.parse.urlencode({"chat_id": recipient, "text": body}).encode()
    req = urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMessage", data=payload)
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            result = json.load(response)
    except urllib.error.HTTPError as error:
        # A returned rejection can be retried. Never include the token-bearing URL.
        if error.code in (400, 401, 403, 404, 429):
            return "pending", None
        return "uncertain", None
    except Exception:
        return "uncertain", None
    if not result.get("ok"):
        return "pending", None
    return "sent", result["result"]["message_id"]


def deliver(engine, token, sender=send_telegram):
    from sqlalchemy import select
    t = tables(engine)
    a = t["awards"]
    results = []
    for request_id in sorted(EXPECTED):
        for prefix in ("first", "second"):
            state_column = a.c[prefix + "_state"]
            with engine.begin() as conn:
                row = conn.execute(select(a).where(a.c.request_id == request_id).with_for_update()).mappings().one_or_none()
                if row is None:
                    break
                if row[prefix + "_state"] != "pending":
                    if row[prefix + "_state"] in ("sending", "uncertain"):
                        results.append(f"#{request_id}: доставка {prefix} требует ручной проверки")
                    continue
                # Mark before HTTP: a crash/timeout never silently repeats a message.
                conn.execute(a.update().where(a.c.request_id == request_id).values(**{prefix + "_state": "sending"}))
                recipient = row["telegram_id"]
                body = (f"Заявка #{request_id} выполнена. Описание приза придёт отдельным сообщением."
                        if prefix == "first" else f"Награда по заявке #{request_id}\n{row['description']}")
            state, message_id = sender(token, recipient, body)
            with engine.begin() as conn:
                conn.execute(a.update().where(a.c.request_id == request_id).values(
                    **{prefix + "_state": state, prefix + "_message_id": message_id}))
            if state != "sent":
                results.append(f"#{request_id}: {prefix} не подтверждено; два уведомления уже есть в кошельке")
            if sender is send_telegram:
                time.sleep(1.1)
    return results


def service_value(name):
    return subprocess.check_output(
        ["systemctl", "show", "nyan-wallet", "-p", name, "--value"], text=True
    ).strip()


def redeem(engine, code):
    from sqlalchemy import select
    a = tables(engine)["awards"]
    with engine.begin() as conn:
        row = conn.execute(select(a).where(a.c.code == code).with_for_update()).mappings().one_or_none()
        if not row:
            raise RuntimeError("Промокод не найден")
        if row["redeemed_at"]:
            raise RuntimeError("Промокод уже использован")
        conn.execute(a.update().where(a.c.request_id == row["request_id"]).values(redeemed_at=stamp()))
        print(f"Погашен {code}, заявка #{row['request_id']}, владелец {row['telegram_id']}")
        print(row["description"])


def main():
    global EXPECTED, PLANNED
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--ids", default="", help="Comma-separated request IDs")
    parser.add_argument("--plan", default="", help="Optional assignments: id=amount or id=dPercent")
    parser.add_argument("--redeem", metavar="CODE")
    args = parser.parse_args()
    if not args.apply and not args.redeem:
        raise RuntimeError("Для выдачи укажи --apply, для погашения скидки --redeem '#КОД'")
    if args.apply:
        EXPECTED = {int(value): None for value in args.ids.split(",") if value.strip()}
        if not EXPECTED or len(EXPECTED) > 100 or min(EXPECTED) < 1:
            raise RuntimeError("Укажи от 1 до 100 конкретных номеров заявок через --ids")
        PLANNED = {}
        for spec in args.plan.split(","):
            if not spec:
                continue
            number, value = spec.split("=", 1)
            number = int(number)
            if number not in EXPECTED:
                raise RuntimeError("План содержит заявку вне списка --ids")
            PLANNED[number] = ({"kind": "discount", "percent": int(value[1:])}
                               if value.startswith("d") else {"kind": "lapcoins", "amount": int(value)})
            validate_prize(PLANNED[number])
    if os.geteuid() != 0:
        raise RuntimeError("Запусти под root в Termius")
    if service_value("ActiveState") != "active":
        raise RuntimeError("Сервис Nyan Wallet не запущен")
    project = Path(service_value("WorkingDirectory"))
    if not project.is_absolute() or not (project / "server/backend_app.py").is_file():
        raise RuntimeError("Не найден проект активного API")
    for folder in (project / ".venv", project / "venv"):
        python = folder / "bin/python"
        if python.is_file():
            if Path(sys.prefix).resolve() != folder.resolve():
                os.execv(str(python), [str(python), str(Path(__file__).resolve()), *sys.argv[1:]])
            break
    if importlib.util.find_spec("sqlalchemy") is None:
        raise RuntimeError("Не найдено окружение SQLAlchemy")
    pid = service_value("MainPID")
    if not pid.isdigit() or int(pid) < 1:
        raise RuntimeError("Не найден активный процесс API")
    env = dict(part.split(b"=", 1) for part in Path(f"/proc/{pid}/environ").read_bytes().split(b"\0") if b"=" in part)
    url = env.get(b"DATABASE_URL", b"").decode().strip()
    if not url.startswith(("postgres://", "postgresql://", "postgresql+psycopg://")):
        raise RuntimeError("Не найдена PostgreSQL база работающего API")
    token = env.get(b"BOT_TOKEN", b"").decode().strip()
    if not token:
        from dotenv import dotenv_values
        token = str(dotenv_values(project / ".env").get("BOT_TOKEN") or "").strip()
    if args.apply and not token:
        raise RuntimeError("Не найден BOT_TOKEN работающего API, выдача не начата")
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            url = url.replace(prefix, "postgresql+psycopg://", 1)
            break
    from sqlalchemy import create_engine
    engine = create_engine(url, pool_pre_ping=True)
    try:
        if args.redeem:
            redeem(engine, args.redeem)
            return
        for request_id, description in fulfil(engine):
            print(f"\n#{request_id}: {description}")
        problems = deliver(engine, token)
        for problem in problems:
            print(problem)
        if not problems:
            print("\nГотово. Заявки обработаны, уведомления доставлены")
    finally:
        engine.dispose()


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, ValueError) as error:
        print("ОШИБКА:", error, file=sys.stderr)
        sys.exit(1)
    except Exception as error:
        print(f"Ошибка {type(error).__name__}. Повторный запуск не начислит призы второй раз", file=sys.stderr)
        sys.exit(1)

