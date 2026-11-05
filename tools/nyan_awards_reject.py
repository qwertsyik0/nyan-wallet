#!/usr/bin/env python3
"""Termius tool: safely reject one confirmed NYAN AWARDS nomination.

Requires PostgreSQL local access (root + sudo -u postgres) and the existing
Telegram relay outbox. Nothing is sent if the database transaction fails.

Examples:
  python3 nyan_awards_reject.py --list
  python3 nyan_awards_reject.py --id 12 --check
  python3 nyan_awards_reject.py --id 12 --reason '...' --apply
"""

from __future__ import annotations

import argparse
import subprocess
import sys


AWARDS = {
    "legend_nyan": "Легенда Нян", "soul_nyan": "Душа Нян", "face_nyan": "Лицо Нян",
    "discovery": "Открытие года", "creator": "Творец Нян", "engine": "Двигатель Нян",
    "games_legend": "Легенда Nyan Games", "mafia_master": "Мастер мафии",
    "finance": "Финансовый стратег", "admin": "Администратор года",
    "flood_legend": "Легенда флуда",
}


def psql(database: str, query: str, **variables: str) -> str:
    command = ["sudo", "-u", "postgres", "psql", "-X", "-qAt", "-P", "pager=off",
               "-v", "ON_ERROR_STOP=1", "-d", database]
    for key, value in variables.items():
        command.extend(["-v", f"{key}={value}"])
    command.extend(["-f", "-"])
    result = subprocess.run(command, input=query, text=True, capture_output=True)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or f"psql exited with {result.returncode}")
    return result.stdout.strip()


LIST_SQL = """
SELECT n.id, n.category, n.display_name, n.candidate_id,
       n.status, n.nominated_by
FROM nyan_awards_nominations_2026 n
ORDER BY n.id;
"""

CHECK_SQL = """
SELECT n.id, n.category, n.display_name, n.candidate_id, n.status,
       COALESCE(r.replacement_nomination_id::text, 'не использована') AS retry,
       COALESCE(x.reason, '') AS previous_reason
FROM nyan_awards_nominations_2026 n
LEFT JOIN nyan_awards_retry_2026 r ON r.candidate_id = n.candidate_id
LEFT JOIN nyan_awards_rejections_2026 x ON x.nomination_id = n.id
WHERE n.id = :'nomination_id'::integer;
"""

APPLY_SQL = """
BEGIN;
SELECT pg_advisory_xact_lock(20261105, 2026);
WITH selected AS (
    SELECT id, category, candidate_id, display_name, status
    FROM nyan_awards_nominations_2026
    WHERE id = :'nomination_id'::integer
    FOR UPDATE
), changed AS (
    UPDATE nyan_awards_nominations_2026 n
    SET status = 'rejected'
    FROM selected s
    WHERE n.id = s.id AND s.status = 'confirmed' AND s.candidate_id IS NOT NULL
      AND (CURRENT_TIMESTAMP AT TIME ZONE 'Europe/Moscow') < TIMESTAMP '2026-11-08 00:00:00'
    RETURNING n.id, n.category, n.candidate_id, n.display_name
), reasons AS (
    INSERT INTO nyan_awards_rejections_2026 (nomination_id, candidate_id, reason, created_at)
    SELECT id, candidate_id, :'reason', NOW() FROM changed
    ON CONFLICT (nomination_id) DO NOTHING
    RETURNING nomination_id
), rights AS (
    INSERT INTO nyan_awards_retry_2026 (candidate_id, origin_nomination_id, granted_at)
    SELECT candidate_id, id, NOW() FROM changed
    ON CONFLICT (candidate_id) DO NOTHING
    RETURNING candidate_id
), queued AS (
    INSERT INTO telegram_relay_outbox (source_key, chat_id, body, state, attempts, created_at)
    SELECT 'awards-reject:' || c.id, c.candidate_id,
           'NYAN AWARDS 2026' || CHR(10) || CHR(10)
           || 'Ваша кандидатура в номинации «' ||
           (CASE c.category
              WHEN 'legend_nyan' THEN 'Легенда Нян' WHEN 'soul_nyan' THEN 'Душа Нян'
              WHEN 'face_nyan' THEN 'Лицо Нян' WHEN 'discovery' THEN 'Открытие года'
              WHEN 'creator' THEN 'Творец Нян' WHEN 'engine' THEN 'Двигатель Нян'
              WHEN 'games_legend' THEN 'Легенда Nyan Games'
              WHEN 'mafia_master' THEN 'Мастер мафии'
              WHEN 'finance' THEN 'Финансовый стратег'
              WHEN 'admin' THEN 'Администратор года'
              WHEN 'flood_legend' THEN 'Легенда флуда' ELSE c.category END)
           || '» была отклонена после проверки.' || CHR(10)
           || 'Причина: ' || :'reason' || CHR(10) || CHR(10)
           || CASE WHEN EXISTS (
                SELECT 1 FROM nyan_awards_retry_2026 r
                WHERE r.candidate_id = c.candidate_id
                  AND r.replacement_nomination_id IS NOT NULL
              ) THEN 'Повторная попытка уже использована.'
              ELSE 'Вы можете один раз выдвинуть себя в ДРУГУЮ номинацию до конца 7 ноября.' END
           || CHR(10) || 'Открыть: https://t.me/nyancash_bot?startapp=nyan_awards',
           'pending', 0, NOW()
    FROM changed c
    ON CONFLICT (source_key) DO NOTHING
    RETURNING id
)
SELECT (SELECT COUNT(*) FROM changed), (SELECT COUNT(*) FROM queued);
COMMIT;
"""


def preview(database: str, nomination_id: int) -> tuple[str, str, str, str, str]:
    rows = psql(database, CHECK_SQL, nomination_id=str(nomination_id)).splitlines()
    if len(rows) != 1:
        raise RuntimeError("Кандидатура с таким ID не найдена")
    parts = rows[0].split("|")
    if len(parts) < 5:
        raise RuntimeError("Неожиданный ответ базы данных")
    return parts[0], parts[1], parts[2], parts[3], parts[4]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument("--list", action="store_true", help="Показать все кандидатуры с ID")
    actions.add_argument("--check", action="store_true", help="Проверить кандидата без изменений")
    actions.add_argument("--apply", action="store_true", help="Отклонить после ручного подтверждения")
    parser.add_argument("--id", type=int, help="ID заявки из --list")
    parser.add_argument("--reason", help="Конкретное объяснение причины отказа")
    parser.add_argument("--database", default="nyan_wallet_db", help="База PostgreSQL")
    args = parser.parse_args()

    if args.list:
        print("ID | категория | кандидат | Telegram ID | статус | кто предложил")
        for line in psql(args.database, LIST_SQL).splitlines():
            parts = line.split("|")
            if len(parts) == 6:
                parts[1] = AWARDS.get(parts[1], parts[1])
                print(" | ".join(parts))
        return 0

    if not args.id or args.id < 1:
        parser.error("Для проверки и отклонения укажи --id <положительный ID>")
    ident, category, candidate, telegram_id, status = preview(args.database, args.id)
    print(f"Заявка #{ident} · {AWARDS.get(category, category)} · {candidate}")
    print(f"Telegram ID: {telegram_id or 'неизвестен'} · статус: {status}")
    if args.check:
        print("Только проверка: никаких изменений и уведомлений")
        return 0

    reason = " ".join((args.reason or "").split())
    if not 10 <= len(reason) <= 500:
        parser.error("Причина должна содержать от 10 до 500 символов")
    if status != "confirmed" or not telegram_id:
        raise RuntimeError("Отклонять можно только подтверждённые заявки с Telegram ID")
    print("Причина:", reason)
    answer = input(f"Для отклонения и уведомления напиши ровно REJECT {ident}: ")
    if answer != f"REJECT {ident}":
        print("Отменено без изменений")
        return 1

    output = psql(args.database, APPLY_SQL, nomination_id=str(args.id), reason=reason)
    numbers = [line for line in output.splitlines() if line.count("|") == 1
               and all(item.isdigit() for item in line.split("|"))]
    if not numbers or numbers[-1] != "1|1":
        raise RuntimeError("Ничего не отклонено. Проверь статус и сроки. Ответ: " + output[-500:])
    print("Готово. Отказ записан, одна повторная попытка выдана, уведомление в очереди Telegram relay")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as error:
        print("ОШИБКА:", error, file=sys.stderr)
        sys.exit(1)
