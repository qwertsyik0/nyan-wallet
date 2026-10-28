-- NYAN GAME: two permanently owned «Разоблачитель» badges.
-- Requires the updated profile UI and API to be deployed first.
-- Safe to rerun; never changes Lapcoin balances or existing purchased badges.
BEGIN;

SELECT pg_advisory_xact_lock(20261028, 401);

CREATE TABLE IF NOT EXISTS limited_profile_badges (
    telegram_id BIGINT NOT NULL REFERENCES users(telegram_id) ON DELETE CASCADE,
    badge_key VARCHAR(64) NOT NULL,
    title VARCHAR(80) NOT NULL,
    edition INTEGER NOT NULL,
    acquired_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (telegram_id, badge_key),
    CONSTRAINT uq_limited_badge_edition UNIQUE (badge_key, edition)
);

CREATE TEMP TABLE unmasker_recipients (
    username TEXT PRIMARY KEY,
    edition INTEGER NOT NULL UNIQUE
) ON COMMIT DROP;

INSERT INTO unmasker_recipients VALUES
    ('PIXEL_ARE_YOU_OKAY', 1),
    ('nirvr', 2);

DO $verify$
DECLARE
    failures TEXT;
BEGIN
    SELECT STRING_AGG('@' || username, ', ')
    INTO failures
    FROM (
        SELECT r.username
        FROM unmasker_recipients r
        LEFT JOIN users u ON LOWER(u.username) = LOWER(r.username)
        GROUP BY r.username
        HAVING COUNT(u.telegram_id) <> 1
    ) bad;

    IF failures IS NOT NULL THEN
        RAISE EXCEPTION 'Покупатели не найдены или неоднозначны: %', failures;
    END IF;

    SELECT STRING_AGG(b.telegram_id::TEXT, ', ')
    INTO failures
    FROM limited_profile_badges b
    WHERE b.badge_key = 'nyan_game_unmasker'
      AND NOT EXISTS (
          SELECT 1
          FROM unmasker_recipients r
          JOIN users u ON LOWER(u.username) = LOWER(r.username)
          WHERE u.telegram_id = b.telegram_id
            AND r.edition = b.edition
      );

    IF failures IS NOT NULL THEN
        RAISE EXCEPTION 'У значка уже есть посторонние владельцы: %', failures;
    END IF;
END
$verify$;

INSERT INTO limited_profile_badges (
    telegram_id, badge_key, title, edition, acquired_at
)
SELECT u.telegram_id, 'nyan_game_unmasker', 'Разоблачитель', r.edition, NOW()
FROM unmasker_recipients r
JOIN users u ON LOWER(u.username) = LOWER(r.username)
ON CONFLICT (telegram_id, badge_key) DO NOTHING;

INSERT INTO wallet_notifications (
    telegram_id, kind, title, body, is_read, created_at
)
SELECT b.telegram_id, 'reward_status', '👁️ Приз NYAN GAME',
       'Вам выдан лимитированный значок «Разоблачитель» №' || b.edition ||
       '/2. Он навсегда доступен в профиле Nyan Wallet.', FALSE, NOW()
FROM limited_profile_badges b
WHERE b.badge_key = 'nyan_game_unmasker'
  AND NOT EXISTS (
      SELECT 1 FROM wallet_notifications n
      WHERE n.telegram_id = b.telegram_id
        AND n.title = '👁️ Приз NYAN GAME'
        AND n.body = 'Вам выдан лимитированный значок «Разоблачитель» №' ||
                     b.edition || '/2. Он навсегда доступен в профиле Nyan Wallet.'
  );

INSERT INTO telegram_relay_outbox (
    source_key, chat_id, body, state, attempts, created_at
)
SELECT 'nyan_game_unmasker_20261028_' || LPAD(b.edition::TEXT, 2, '0'),
       b.telegram_id,
       'Вам выдан лимитированный значок «Разоблачитель» №' || b.edition ||
       '/2! Он навсегда доступен в профиле Nyan Wallet.',
       'pending', 0, NOW()
FROM limited_profile_badges b
WHERE b.badge_key = 'nyan_game_unmasker'
ON CONFLICT (source_key) DO NOTHING;

COMMIT;

SELECT u.username, b.edition, o.state AS notification_status, o.last_error
FROM limited_profile_badges b
JOIN users u ON u.telegram_id = b.telegram_id
LEFT JOIN telegram_relay_outbox o
  ON o.source_key = 'nyan_game_unmasker_20261028_' || LPAD(b.edition::TEXT, 2, '0')
WHERE b.badge_key = 'nyan_game_unmasker'
ORDER BY b.edition;
