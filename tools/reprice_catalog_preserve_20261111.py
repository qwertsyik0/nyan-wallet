#!/usr/bin/env python3
"""One-time owner-authorized Nyan Wallet catalog repricing.

Runs on FirstVDS as root. Safely:
  1. Checks all 24 expected original prices (no blind price overwrite).
  2. Makes private backups of current catalog and server source.
  3. Removes startup overwriting of existing Telegram Stars prices.
  4. Restarts and verifies the wallet API (with code rollback on failure).
  5. Raises all 24 catalog prices by factor 44/35, rounded to nearest 50 paws,
     so 250 Telegram Stars change from 8,750 to exactly 11,000 paws.
  6. Records each old/new price in admin_audit, transactionally and once only.

Neither this script nor --check changes wallet balances, transaction history,
active flags, reward definitions or existing purchase/request prices.
"""

from __future__ import annotations

import argparse
import ast
import datetime as dt
import json
import os
import shutil
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path

DB = "nyan_wallet_db"
SERVICE = "nyan-wallet"
ROOT = Path("/opt/nyan-wallet")
MODULE = ROOT / "server/extended_features.py"
ACTION = "catalog_reprice_20261111_preserve_v1"
EXPECTED = {
    1: 1750, 2: 3500, 3: 8750, 4: 17500,
    5: 2250, 6: 250, 7: 550, 8: 900,
    9: 450, 10: 1250, 11: 350, 12: 650,
    13: 450, 14: 900, 15: 600, 16: 1200,
    17: 550, 18: 1300, 19: 700, 20: 1000,
    21: 2600, 22: 850, 23: 3500, 24: 1500,
}

SEED_BEFORE = (
    "            if reward:\n"
    "                reward.cost = cost\n"
    "                reward.description = description\n"
    "                reward.sort_order = sort_order\n"
)
SEED_AFTER = (
    "            if reward:\n"
    "                # Prices are owner-managed; preserve them on service startup.\n"
    "                reward.description = description\n"
    "                reward.sort_order = sort_order\n"
)


def cmd(*arguments: str, stdin: str | None = None) -> str:
    p = subprocess.run(
        arguments, input=stdin, text=True, capture_output=True,
        check=False, timeout=90,
    )
    if p.returncode:
        raise RuntimeError(
            "Команда завершилась ошибкой: " + " ".join(arguments[:4])
            + "\n" + (p.stderr or p.stdout or "нет деталей")[-1400:]
        )
    return p.stdout.strip()


def pg(sql: str) -> str:
    return cmd(
        "runuser", "-u", "postgres", "--",
        "psql", "-X", "-q", "-A", "-t", "-P", "pager=off",
        "-v", "ON_ERROR_STOP=1", "-d", DB,
        stdin=sql,
    )


def current_catalog() -> list[dict]:
    output = pg(
        "SELECT COALESCE(json_agg(row_to_json(r) ORDER BY r.id), '[]'::json)::text "
        "FROM (SELECT id, title, cost, is_active, sort_order "
        "FROM reward_catalog ORDER BY id) AS r;\n"
    )
    return json.loads(output)


def applied() -> bool:
    return pg(
        "SELECT count(*) FROM admin_audit WHERE action = '" + ACTION + "';\n"
    ) != "0"


def price(cost: int) -> int:
    # Half-up rounding to 50 paw increments, using exact rational arithmetic.
    return ((cost * 44 + 875) // 1750) * 50


def patch(source: str) -> tuple[str, bool]:
    if source.count(SEED_BEFORE) == 1:
        return source.replace(SEED_BEFORE, SEED_AFTER, 1), True
    if source.count(SEED_AFTER) == 1 and "reward.cost = cost" not in source:
        return source, False
    raise RuntimeError(
        "Не найдена ожидаемая функция seed_rewards. "
        "Сервер может содержать дополнительные изменения — ничего не трогаю."
    )


def save_atomic(file: Path, data: bytes) -> None:
    fd, temporary = tempfile.mkstemp(prefix=".nyan-price-", dir=file.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, file.stat().st_mode & 0o777)
        os.replace(temporary, file)
    finally:
        Path(temporary).unlink(missing_ok=True)


def health() -> None:
    error = "нет ответа"
    for _ in range(14):
        try:
            if cmd("systemctl", "is-active", SERVICE) != "active":
                raise RuntimeError("служба ещё запускается")
            with urllib.request.urlopen(
                "http://127.0.0.1:8000/openapi.json", timeout=4
            ) as response:
                schema = json.load(response)
            if "/api/rewards" not in schema.get("paths", {}):
                raise RuntimeError("маршрут /api/rewards недоступен")
            return
        except Exception as exc:
            error = str(exc)
            time.sleep(1)
    raise RuntimeError("Проверка API не прошла: " + error)


def apply_prices(rows: list[dict]) -> None:
    values = ",\n    ".join(
        f"({int(r['id'])}, {int(r['cost'])}, {price(int(r['cost']))})"
        for r in rows
    )
    sql = f"""
BEGIN;
SELECT pg_advisory_xact_lock(761108291);
DO $guard$
BEGIN
  IF EXISTS (SELECT 1 FROM admin_audit WHERE action = '{ACTION}') THEN
    RAISE EXCEPTION 'NYAN reprice already applied';
  END IF;
  IF (SELECT count(*) FROM reward_catalog) != 24 THEN
    RAISE EXCEPTION 'Catalog size changed; no prices updated';
  END IF;
  IF EXISTS (
    SELECT 1 FROM (VALUES {values}) AS e(id, old_cost, new_cost)
    FULL OUTER JOIN reward_catalog AS r ON r.id = e.id
    WHERE e.id IS NULL OR r.id IS NULL OR r.cost IS DISTINCT FROM e.old_cost
  ) THEN
    RAISE EXCEPTION 'Catalog prices changed since preview; no prices updated';
  END IF;
END $guard$;

WITH expected(id, old_cost, new_cost) AS (
  VALUES {values}
), updated AS (
  UPDATE reward_catalog AS r
  SET cost = e.new_cost
  FROM expected AS e
  WHERE r.id = e.id AND r.cost = e.old_cost
  RETURNING r.id, r.title, e.old_cost, r.cost AS new_cost, r.is_active
)
INSERT INTO admin_audit (action, target_telegram_id, details, created_at)
SELECT '{ACTION}', NULL,
       jsonb_build_object(
         'factor', '44/35',
         'rounding', 'nearest 50 pawcoins',
         'items', (SELECT jsonb_agg(
             jsonb_build_object(
               'id', id, 'title', title,
               'old_cost', old_cost, 'new_cost', new_cost,
               'is_active', is_active
             ) ORDER BY id
           ) FROM updated)
       )::text,
       now();
COMMIT;
"""
    pg(sql)


def main() -> None:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--check", action="store_true")
    group.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    if os.geteuid() != 0:
        raise RuntimeError("Запусти от root на FirstVDS")
    if not MODULE.is_file():
        raise RuntimeError("Не найдено " + str(MODULE))
    original = MODULE.read_bytes()
    updated_text, needs_patch = patch(original.decode("utf-8"))
    ast.parse(updated_text, filename=str(MODULE))

    rows = current_catalog()
    current = {int(row["id"]): int(row["cost"]) for row in rows}
    already = applied()

    if already:
        if needs_patch:
            raise RuntimeError(
                "Прайс уже изменён, но код автосброса снова появился. "
                "Остановлено для защиты текущих цен."
            )
        print("Переоценка уже применялась. Повторное начисление цен заблокировано.")
        return

    if current != EXPECTED:
        changed = [
            f"ID {id}: сейчас {current.get(id)}, ожидалось {EXPECTED.get(id)}"
            for id in sorted(set(current) | set(EXPECTED))
            if current.get(id) != EXPECTED.get(id)
        ]
        raise RuntimeError(
            "Текущий каталог отличается от присланной выписки. "
            "Цены не изменены.\n" + "\n".join(changed)
        )

    print("NYAN WALLET · проверка переоценки")
    print("Повышение: +25.7142857% (44/35), округление до 50 🐾")
    print("Изменятся цены всех 24 позиций, включая временно скрытые.")
    print("ID | Наименование                          | Было → Станет")
    for r in rows:
        print(
            f"{r['id']:>2} | {r['title'][:37]:<37} | "
            f"{r['cost']:>6} → {price(int(r['cost'])):>6}"
        )
    if args.check:
        print("\nOK: сухая проверка. Ничего не изменено.")
        print("Код автосброса:", "потребуется отключить" if needs_patch else "уже отключён")
        return

    backup = ROOT / ".nyan-price-backups" / dt.datetime.now(
        dt.timezone.utc
    ).strftime("%Y%m%d-%H%M%S-%f")
    backup.mkdir(parents=True, exist_ok=False)
    os.chmod(backup, 0o700)
    shutil.copy2(MODULE, backup / "extended_features.py")
    catalog_backup = backup / "reward_catalog_before.json"
    catalog_backup.write_text(
        json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    os.chmod(catalog_backup, 0o600)

    patched = False
    try:
        if needs_patch:
            save_atomic(MODULE, updated_text.encode("utf-8"))
            patched = True
            cmd("systemctl", "restart", SERVICE)
            health()
        apply_prices(rows)
    except Exception as error:
        # PostgreSQL rolls back the entire price UPDATE if any SQL error occurs.
        if patched:
            save_atomic(MODULE, original)
            try:
                cmd("systemctl", "restart", SERVICE)
                health()
            except Exception as rollback_error:
                raise RuntimeError(
                    f"Переоценка не завершена: {error}. "
                    f"Откат сервиса требует внимания: {rollback_error}. "
                    f"Резервная копия: {backup}"
                ) from error
        raise RuntimeError(
            "Переоценка отменена, изменение цен не выполнено. "
            f"Причина: {error}\nРезервная копия: {backup}"
        ) from error

    after = {int(row["id"]): int(row["cost"]) for row in current_catalog()}
    expected_after = {id: price(cost) for id, cost in EXPECTED.items()}
    if after != expected_after or not applied():
        raise RuntimeError(
            "SQL завершён, но контрольная проверка не совпала; не запускай "
            "команду повторно, проверь резервную копию и журнал: " + str(backup)
        )
    print("\nOK: автосброс цен отключён, 24 цены обновлены и проверены.")
    print("250 Stars: 8750 → 11000 🐾. Прайс больше не сбрасывается при рестарте.")
    print("Резервная копия:", backup)
    print("Баланс пользователей, история, статус товаров и заявки не изменены.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        raise SystemExit("ОШИБКА: " + str(exc)) from exc
