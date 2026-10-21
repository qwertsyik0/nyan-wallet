#!/usr/bin/env python3
"""Fulfil already-paid request #42 with a visible custom badge beside wallet nickname.

On FirstVDS as root:
  python3 fulfill_name_badge_42.py --check
  python3 fulfill_name_badge_42.py --apply
"""
from __future__ import annotations

import argparse
import ast
import datetime
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

PROJECT = Path("/opt/nyan-wallet")
MODULE = PROJECT / "server/achievements.py"
DATABASE = "nyan_wallet_db"
REQUEST_ID = 42
TELEGRAM_ID = 8178699225
COST = 650
SERVICE = "nyan-wallet"

MODEL_ANCHOR = "class WalletActivityDay(core.Base):"
MODEL_BLOCK = """class PurchasedNameBadge(core.Base):
    \"\"\"Paid cosmetic displayed beside a wallet nickname; unrelated to achievements.\"\"\"
    __tablename__ = "purchased_name_badges"

    telegram_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.telegram_id", ondelete="CASCADE"), primary_key=True
    )
    symbol: Mapped[str] = mapped_column(String(12), nullable=False)
    title: Mapped[str] = mapped_column(String(40), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


"""
SERIALIZE_FROM = """    return {
        "items": items,
        "unlocked_count": len(unlock_map),
        "total": len(ACHIEVEMENTS),
        "selected_badge": selected,
    }"""
SERIALIZE_TO = """    purchased = session.get(PurchasedNameBadge, telegram_id)
    return {
        "items": items,
        "unlocked_count": len(unlock_map),
        "total": len(ACHIEVEMENTS),
        "selected_badge": selected,
        "purchased_badge": (
            {"symbol": purchased.symbol, "title": purchased.title}
            if purchased else None
        ),
    }"""


def cmd(*argv, input_text=None):
    result = subprocess.run(argv, input=input_text, capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(
            f"Команда {argv[0]} завершилась с ошибкой: "
            + (result.stderr or result.stdout).strip()[-1200:]
        )
    return result.stdout.strip()


def db(sql):
    return cmd("sudo", "-u", "postgres", "psql", "-X",
               "-v", "ON_ERROR_STOP=1", "-d", DATABASE,
               "-At", "-F", "|", input_text=sql)


def check_order():
    result = db(f"""SELECT telegram_id, cost, status, reward_title
FROM spend_requests WHERE id = {REQUEST_ID};
""")
    if not result:
        raise RuntimeError("Заявка #42 не найдена")
    fields = result.splitlines()[0].split("|", 3)
    if len(fields) != 4:
        raise RuntimeError("Не удалось прочитать заявку #42")
    uid, cost, status, title = fields
    print(f"Заявка #{REQUEST_ID}: {title} · ID {uid} · {cost} 🐾 · {status}")
    if int(uid) != TELEGRAM_ID or int(cost) != COST or (
        "значок" not in title.lower() or "ник" not in title.lower()
    ):
        raise RuntimeError("Данные заявки не совпадают, выполнение отменено")
    if status not in ("pending", "processing", "fulfilled"):
        raise RuntimeError("Невозможно выполнить заявку в статусе " + status)


def patch_source(source):
    if "class PurchasedNameBadge(core.Base):" not in source:
        if source.count(MODEL_ANCHOR) != 1:
            raise RuntimeError("Не найден безопасный якорь модели достижений")
        source = source.replace(MODEL_ANCHOR, MODEL_BLOCK + MODEL_ANCHOR, 1)
    if '"purchased_badge":' not in source:
        if source.count(SERIALIZE_FROM) != 1:
            raise RuntimeError("Не найден безопасный якорь ответа достижений")
        source = source.replace(SERIALIZE_FROM, SERIALIZE_TO, 1)
    ast.parse(source, str(MODULE))
    return source


def health():
    last = ""
    for _ in range(12):
        try:
            with urllib.request.urlopen(
                "http://127.0.0.1:8000/api/health", timeout=3
            ) as response:
                if response.status == 200:
                    return
        except Exception as exc:
            last = repr(exc)
        time.sleep(2)
    raise RuntimeError("API не отвечает после обновления: " + last)


def fulfil():
    sql = f"""BEGIN;
SELECT pg_advisory_xact_lock({REQUEST_ID});
INSERT INTO purchased_name_badges
    (telegram_id, symbol, title, created_at)
SELECT telegram_id, '✦', 'Особый знак Nyan', NOW()
FROM spend_requests
WHERE id={REQUEST_ID} AND telegram_id={TELEGRAM_ID}
  AND cost={COST}
  AND status IN ('pending','processing','fulfilled')
  AND reward_title ILIKE '%значок%'
ON CONFLICT (telegram_id) DO NOTHING;

WITH finished AS (
    UPDATE spend_requests
    SET status='fulfilled', processed_at=NOW()
    WHERE id={REQUEST_ID} AND telegram_id={TELEGRAM_ID}
      AND cost={COST} AND status IN ('pending','processing')
      AND EXISTS (
          SELECT 1 FROM purchased_name_badges
          WHERE telegram_id={TELEGRAM_ID}
      )
    RETURNING id, telegram_id
)
INSERT INTO wallet_notifications
    (telegram_id, kind, title, body, is_read, created_at)
SELECT telegram_id, 'reward_status', 'Заявка №42 выполнена',
       'Установлен персональный значок ✦ рядом с вашим именем в Nyan Wallet.',
       FALSE, NOW()
FROM finished;
COMMIT;

SELECT 'Заявка', id, telegram_id, status FROM spend_requests
WHERE id={REQUEST_ID};
SELECT 'Значок', telegram_id, symbol, title
FROM purchased_name_badges WHERE telegram_id={TELEGRAM_ID};
"""
    print(db(sql))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--check", action="store_true")
    group.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if not MODULE.is_file():
        raise RuntimeError("Не найден серверный файл " + str(MODULE))
    check_order()
    current = MODULE.read_text(encoding="utf-8")
    updated = patch_source(current)
    print("Обновление backend:", "требуется" if current != updated else "уже установлено")
    print("Предлагаемый персональный значок: ✦")
    if args.check:
        print("Проверка завершена. Ничего не изменено.")
        return
    if cmd("systemctl", "is-active", SERVICE) != "active":
        raise RuntimeError("Сервис Nyan Wallet не active")
    if current != updated:
        backup = MODULE.with_name("achievements.py.backup-" + datetime.datetime.now().strftime("%Y%m%d-%H%M%S"))
        shutil.copy2(MODULE, backup)
        print("Резервная копия:", backup)
        try:
            MODULE.write_text(updated, encoding="utf-8")
            cmd("systemctl", "restart", SERVICE)
            health()
        except Exception:
            MODULE.write_text(current, encoding="utf-8")
            subprocess.run(["systemctl", "restart", SERVICE], check=False)
            raise
    else:
        health()
    fulfil()
    print("Готово. Баланс не изменялся. Отправка через Telegram API не требовалась.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("ОШИБКА:", exc, file=sys.stderr)
        sys.exit(1)
