#!/usr/bin/env python3
"""Four-day transparent zero-only Fortune event; 100-paw automatic compensation.

FirstVDS, root:
  --check   inspect without writing
  --start   preserve original event start if present, extend to 4 days, schedule payout
  --status  show event and service status
  --payout  (also used by systemd timer) award 100 paws once per eligible user

When the event ends, the server automatically restores ordinary probabilities.
A persistent systemd timer awards 100 paws per distinct player who actually
spun 0 during the campaign. The award is transactional and idempotent.
"""

from __future__ import annotations

import ast
import argparse
import datetime as dt
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path("/opt/nyan-wallet")
MODULE = ROOT / "server/fortune.py"
PAUSE = ROOT / ".fortune_disabled"
EVENT = ROOT / ".fortune_zero_day.json"
INSTALLED = ROOT / ".fortune-fourday-payout.py"
UNIT_DIR = Path("/etc/systemd/system")
SERVICE = UNIT_DIR / "nyan-fortune-fourday-payout.service"
TIMER = UNIT_DIR / "nyan-fortune-fourday-payout.timer"
MODULE_URL = "https://raw.githubusercontent.com/qwertsyik0/nyan-wallet/main/server/fortune.py"
SOURCE_BLOBS = {
    "eac4a4dc6fd18192e72b209a34a78215cf5a9d2e": "original",
    "a3e07f4b305623e01bca5117beeda83d5e20d9f7": "paused",
    "fd78dde8b118724243859edf35a71d9b83b2e0a1": "24h-special",
    "b4015ff9e9c96af5f95aa1d140107c0aff986458": "4d-special",
}
TARGET_BLOB = "b4015ff9e9c96af5f95aa1d140107c0aff986458"
DAYS = 4
SECONDS = DAYS * 86400
BONUS = 100
MAX_BALANCE = 2147483647
SQL_LOCK_ID = 911141004
MARKER = "# NYAN-FOURDAY-100-AUTO-PAYOUT"
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def run(*args: str, input_text: str | None = None) -> str:
    proc = subprocess.run(args, capture_output=True, text=True, input=input_text, timeout=100)
    if proc.returncode != 0:
        raise RuntimeError("Команда завершилась ошибкой: "
                           + " ".join(args[:4]) + "\n"
                           + (proc.stderr or proc.stdout)[-1000:])
    return proc.stdout.strip()


def git_blob(body: bytes) -> str:
    return hashlib.sha1(b"blob " + str(len(body)).encode() + b"\0" + body).hexdigest()


def atomic(path: Path, data: bytes, mode: int = 0o600) -> None:
    fd, temporary = tempfile.mkstemp(prefix=".fortune-4day-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def download_target() -> bytes:
    request = urllib.request.Request(
        MODULE_URL, headers={"User-Agent": "NyanWalletFortuneFourday/1"}
    )
    with OPENER.open(request, timeout=25) as response:
        data = response.read(150_000)
    if git_blob(data) != TARGET_BLOB:
        raise RuntimeError("GitHub изменился: целевой серверный файл не совпадает с проверенной версией.")
    code = data.decode("utf-8")
    ast.parse(code, filename="fortune.py")
    if "4 * 24 * 60 * 60 + 1" not in code or "ZERO_SECTOR_INDEX" not in code:
        raise RuntimeError("Режим четырёх дней не найден в загруженном коде")
    return data


def ready(attempts: int = 45) -> None:
    last = ""
    for i in range(attempts):
        try:
            if run("systemctl", "is-active", "nyan-wallet") != "active":
                raise RuntimeError("Служба Nyan Wallet неактивна")
            with OPENER.open("http://127.0.0.1:8000/openapi.json", timeout=5) as res:
                routes = json.load(res).get("paths", {})
            if "/api/fortune" not in routes or "/api/fortune/spin" not in routes:
                raise RuntimeError("Не обнаружено API колеса")
            return
        except Exception as exc:
            last = str(exc)
            if i + 1 != attempts:
                time.sleep(2)
    raise RuntimeError("API не отвечает после ожидания: " + last)


def info() -> dict | None:
    if not EVENT.exists():
        return None
    data = json.loads(EVENT.read_text(encoding="utf-8"))
    start, end = float(data["starts_at_unix"]), float(data["ends_at_unix"])
    if data.get("event") != "nyan_fortune_zero_day":
        raise RuntimeError("Неизвестный тип сохранённой акции")
    if not 0 < end - start <= SECONDS + 1:
        raise RuntimeError("Недопустимый интервал акции")
    return data


def utc_string(t: float) -> str:
    return dt.datetime.fromtimestamp(t, tz=dt.timezone.utc).isoformat()


def event_id(event: dict) -> str:
    start = float(event["starts_at_unix"])
    return "fortune4d-" + hashlib.sha256(f"{start:.6f}".encode()).hexdigest()[:24]


def is_fourday(event: dict) -> bool:
    return (
        int(event.get("future_bonus_per_unique_spinner", -1)) == BONUS
        and abs(float(event["ends_at_unix"]) - float(event["starts_at_unix"]) - SECONDS) < 2
    )


def status(module_version: str) -> None:
    print("Версия серверного колеса:", module_version)
    print("Пауза:", "включена" if PAUSE.exists() else "нет")
    e = info()
    if not e:
        print("Акция: не настроена")
    else:
        print("Начало (UTC):", utc_string(float(e["starts_at_unix"])))
        print("Окончание (UTC):", utc_string(float(e["ends_at_unix"])))
        print("Компенсация:", e.get("future_bonus_per_unique_spinner"), "🐾 / участник")
        print("Статус:", "идёт" if float(e["starts_at_unix"]) <= time.time() < float(e["ends_at_unix"]) else "не идёт")
    print("Автовыплата:", "таймер установлен" if TIMER.exists() else "не установлена")


def pg(sql: str) -> str:
    return run("runuser", "-u", "postgres", "--", "psql", "-X", "-q",
               "-A", "-t", "-P", "pager=off", "-v", "ON_ERROR_STOP=1",
               "-d", "nyan_wallet_db", input_text=sql)


def payout() -> None:
    event = info()
    if not event or not is_fourday(event):
        raise RuntimeError("Не найдена завершённая четырёхдневная акция с компенсацией 100 🐾")
    if time.time() < float(event["ends_at_unix"]) + 2:
        raise RuntimeError("Срок акции ещё не завершился — выплата пока запрещена")
    name = event_id(event)
    start = utc_string(float(event["starts_at_unix"]))
    end = utc_string(float(event["ends_at_unix"]))
    # All parameters are numeric timestamps or sha256 event IDs, not user input.
    sql = f"""
BEGIN;
SET LOCAL lock_timeout = '20s';
SET LOCAL statement_timeout = '10min';
SELECT pg_advisory_xact_lock({SQL_LOCK_ID});
CREATE TABLE IF NOT EXISTS fortune_zero_compensations (
    event_id text NOT NULL,
    telegram_id bigint NOT NULL REFERENCES users(telegram_id),
    amount integer NOT NULL CHECK (amount = 100),
    transaction_id integer NOT NULL REFERENCES transactions(id),
    created_at timestamptz NOT NULL,
    PRIMARY KEY (event_id, telegram_id),
    UNIQUE (transaction_id)
);
DO $award$
DECLARE
    player RECORD;
    old_balance bigint;
    row_count integer;
    transaction_number integer;
BEGIN
    FOR player IN
        SELECT DISTINCT telegram_id FROM fortune_spins
        WHERE spun_at >= timestamptz '{start}'
          AND spun_at < timestamptz '{end}'
          AND sector_index = 4 AND reward_amount = 0
        ORDER BY telegram_id
    LOOP
        SELECT balance INTO old_balance
        FROM users WHERE telegram_id = player.telegram_id FOR UPDATE;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'Игрок % без счёта в users', player.telegram_id;
        END IF;
        IF EXISTS (
            SELECT 1 FROM fortune_zero_compensations
            WHERE event_id = '{name}' AND telegram_id = player.telegram_id
        ) THEN
            CONTINUE;
        END IF;
        IF old_balance > {MAX_BALANCE - BONUS} THEN
            RAISE EXCEPTION 'Недостаточно вместимости баланса для %', player.telegram_id;
        END IF;

        UPDATE users SET balance = balance + {BONUS}
        WHERE telegram_id = player.telegram_id;

        INSERT INTO transactions
            (telegram_id, amount, operation_type, description, created_at)
        VALUES (
            player.telegram_id, {BONUS}, 'fortune_event_compensation',
            'Компенсация за участие в четырёхдневной акции Колеса фортуны',
            now()
        ) RETURNING id INTO transaction_number;

        INSERT INTO fortune_zero_compensations
            (event_id, telegram_id, amount, transaction_id, created_at)
        VALUES ('{name}', player.telegram_id, {BONUS}, transaction_number, now())
        ON CONFLICT (event_id, telegram_id) DO NOTHING;
        GET DIAGNOSTICS row_count = ROW_COUNT;
        IF row_count != 1 THEN
            RAISE EXCEPTION 'Конкурентная выплата для %, отмена транзакции', player.telegram_id;
        END IF;
    END LOOP;
END $award$;
COMMIT;

SELECT 'ПОТРЕБИТЕЛЕЙ=' || count(*) || ' НАЧИСЛЕНО=' || COALESCE(sum(amount),0)
FROM fortune_zero_compensations WHERE event_id = '{name}';
"""
    print("Начисляем 100 🐾 каждому участнику завершённой акции.")
    print(pg(sql))
    print("OK: выплата завершена; повторный запуск не дублирует начисления.")


def make_units(end: float) -> tuple[bytes, bytes]:
    when = dt.datetime.fromtimestamp(end + 120, dt.timezone.utc)
    calendar = when.strftime("%Y-%m-%d %H:%M:%S UTC")
    service = f"""[Unit]
Description=Nyan Wallet fortune four-day participant compensation
After=postgresql.service
{MARKER}

[Service]
Type=oneshot
ExecStart=/usr/bin/python3 {INSTALLED} --payout
Restart=on-failure
RestartSec=5min
"""
    timer = f"""[Unit]
Description=Pay 100 paws to fortune four-day participants
{MARKER}

[Timer]
OnCalendar={calendar}
Persistent=true
AccuracySec=1min
Unit={SERVICE.name}

[Install]
WantedBy=timers.target
"""
    return service.encode(), timer.encode()


def main() -> None:
    arg = argparse.ArgumentParser()
    group = arg.add_mutually_exclusive_group(required=True)
    group.add_argument("--check", action="store_true")
    group.add_argument("--start", action="store_true")
    group.add_argument("--status", action="store_true")
    group.add_argument("--payout", action="store_true")
    opt = arg.parse_args()
    if os.geteuid() != 0:
        raise RuntimeError("Запускай от root на FirstVDS")

    if opt.payout:
        payout()
        return

    if not MODULE.is_file():
        raise RuntimeError("Нет файла " + str(MODULE))
    original = MODULE.read_bytes()
    original_blob = git_blob(original)
    if original_blob not in SOURCE_BLOBS:
        raise RuntimeError(
            "Локальный server/fortune.py изменён ("
            + original_blob + "); не перезаписываю уникальные правки."
        )
    if opt.status:
        status(SOURCE_BLOBS[original_blob])
        return

    target = download_target()
    ready(3)
    status(SOURCE_BLOBS[original_blob])
    if opt.check:
        print("OK: сухая проверка, ничего не изменено.")
        return

    previous = info()
    now = time.time()
    if previous and is_fourday(previous):
        if float(previous["ends_at_unix"]) <= now:
            raise RuntimeError("Прошлая акция завершена. Новую не начинаю до выплаты.")
        if not TIMER.is_file():
            raise RuntimeError("Акция уже идёт, но таймер отсутствует. Нужна диагностика.")
        print("OK: четырёхдневный режим уже запущен. Повторный запуск срок не продлевает.")
        return

    if previous and not previous.get("stopped_early") and \
       float(previous["starts_at_unix"]) <= now < float(previous["starts_at_unix"]) + SECONDS:
        beginning = float(previous["starts_at_unix"])
        print("Продлеваю существующий режим, сохраняя дату его начала.")
    else:
        beginning = now
        print("Начинаю новый четырёхдневный режим.")

    end = beginning + SECONDS
    event = {
        "event": "nyan_fortune_zero_day",
        "starts_at_unix": beginning,
        "ends_at_unix": end,
        "future_bonus_per_unique_spinner": BONUS,
        "event_id": "fortune4d-" + hashlib.sha256(f"{beginning:.6f}".encode()).hexdigest()[:24],
    }
    backup = ROOT / ".fortune-backups" / (
        "4day100-" + dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
    )
    backup.mkdir(mode=0o700, parents=True, exist_ok=False)
    os.chmod(backup, 0o700)
    shutil.copy2(MODULE, backup / "fortune.py")
    old_event = EVENT.read_bytes() if EVENT.exists() else None
    if old_event is not None:
        atomic(backup / "old_event.json", old_event)
    was_paused = PAUSE.exists()
    unit_backups = {}
    for unit in (SERVICE, TIMER):
        if unit.exists():
            data = unit.read_bytes()
            if MARKER.encode() not in data:
                raise RuntimeError("Уже существует чужой systemd unit " + str(unit))
            unit_backups[unit] = data
    previously_installed = INSTALLED.read_bytes() if INSTALLED.exists() else None
    module_changed = original_blob != TARGET_BLOB
    try:
        # The disabled flag prevents spins between module restart and activation.
        PAUSE.touch(exist_ok=True)
        if module_changed:
            atomic(MODULE, target, mode=MODULE.stat().st_mode & 0o777)
            run("systemctl", "restart", "nyan-wallet")
            ready()
        # Install payout command in a persistent path; the timer runs this later.
        atomic(INSTALLED, Path(__file__).read_bytes(), mode=0o700)
        service_bytes, timer_bytes = make_units(end)
        atomic(SERVICE, service_bytes, mode=0o644)
        atomic(TIMER, timer_bytes, mode=0o644)
        run("systemctl", "daemon-reload")
        run("systemctl", "enable", "--now", TIMER.name)
        run("systemctl", "restart", TIMER.name)
        atomic(EVENT, (json.dumps(event, ensure_ascii=False) + "\n").encode())
        PAUSE.unlink(missing_ok=True)
    except Exception as error:
        if old_event is None:
            EVENT.unlink(missing_ok=True)
        else:
            atomic(EVENT, old_event)
        if module_changed:
            atomic(MODULE, original, mode=MODULE.stat().st_mode & 0o777)
            try:
                run("systemctl", "restart", "nyan-wallet")
                ready()
            except Exception as rollback_error:
                raise RuntimeError(
                    f"Ошибка {error}; откат API требует внимания: {rollback_error}; бэкап {backup}"
                ) from error
        if not was_paused:
            PAUSE.unlink(missing_ok=True)
        for unit in (SERVICE, TIMER):
            if unit in unit_backups:
                atomic(unit, unit_backups[unit], mode=0o644)
            else:
                unit.unlink(missing_ok=True)
        if previously_installed is None:
            INSTALLED.unlink(missing_ok=True)
        else:
            atomic(INSTALLED, previously_installed, mode=0o700)
        run("systemctl", "daemon-reload")
        raise RuntimeError("Не удалось применить акцию, изменения отменены: "
                           + str(error) + "; бэкап " + str(backup)) from error

    print("OK: 4 дня по 0 🐾; после окончания автокомпенсация 100 🐾 на участника.")
    print("Время окончания (UTC):", utc_string(end))
    print("Таймер:", run("systemctl", "is-enabled", TIMER.name))
    print("Перезапуска колеса после окончания не требуется.")
    print("Проверка состояния: python3 /root/nyan_fourday.py --status")
    print("Бэкап:", backup)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        raise SystemExit("ОШИБКА: " + str(exc)) from exc
