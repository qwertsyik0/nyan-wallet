-- Nyan Wallet: paid personal background "Тихий гербарий".
-- Recipient: Telegram ID 7992643360; catalog reward "Уникальный фон карточки" (500 pawcoins).
-- Requires /tmp/nyan-custom-7992643360.webp downloaded from this repository.
-- Idempotent and atomic. Does not change wallet balance or transactions.

BEGIN;
SELECT pg_advisory_xact_lock(20261030, 799264);

DO $install$
DECLARE
    v_user_id CONSTANT BIGINT := 7992643360;
    v_title CONSTANT TEXT := 'Тихий гербарий';
    v_digest CONSTANT TEXT := '97e93f3ee5dd98312859f0794edb93ceb68d16d84bea4e7f6b2f388ccb467370';
    v_file CONSTANT TEXT := '/tmp/nyan-custom-7992643360.webp';
    v_notice CONSTANT TEXT := 'Ваш индивидуальный дизайн «Тихий гербарий» установлен в Nyan Wallet. Откройте кошелёк, чтобы увидеть обновлённую карточку.';
    v_count INTEGER;
    v_request RECORD;
    v_image_bytes BYTEA;
    v_skin_id INTEGER;
BEGIN
    SELECT COUNT(*) INTO v_count
    FROM users
    WHERE telegram_id = v_user_id;
    IF v_count <> 1 THEN
        RAISE EXCEPTION 'Получатель Telegram ID % отсутствует в users', v_user_id;
    END IF;

    -- Require exactly one paid request from the date supplied by the owner.
    SELECT COUNT(*) INTO v_count
    FROM spend_requests
    WHERE telegram_id = v_user_id
      AND reward_title = 'Уникальный фон карточки'
      AND cost = 500
      AND (created_at AT TIME ZONE 'Europe/Moscow')::date = DATE '2026-10-30';
    IF v_count <> 1 THEN
        RAISE EXCEPTION 'Ожидалась одна заявка на фон от 30.10.2026, найдено: %', v_count;
    END IF;

    SELECT id, status, created_at INTO v_request
    FROM spend_requests
    WHERE telegram_id = v_user_id
      AND reward_title = 'Уникальный фон карточки'
      AND cost = 500
      AND (created_at AT TIME ZONE 'Europe/Moscow')::date = DATE '2026-10-30'
    FOR UPDATE;

    IF NOT EXISTS (
        SELECT 1 FROM transactions t
        WHERE t.telegram_id = v_user_id
          AND t.amount = -500
          AND t.operation_type = 'reward_request'
          AND t.description = 'Заявка: Уникальный фон карточки'
          AND ABS(EXTRACT(EPOCH FROM (t.created_at - v_request.created_at))) <= 60
    ) THEN
        RAISE EXCEPTION 'Подтверждённое списание 500 лапкоинов не найдено. Установка остановлена';
    END IF;

    v_image_bytes := pg_read_binary_file(v_file);
    IF ENCODE(SHA256(v_image_bytes), 'hex') <> v_digest THEN
        RAISE EXCEPTION 'Не совпал SHA256 фона: установка остановлена';
    END IF;
    IF OCTET_LENGTH(v_image_bytes) > 2 * 1024 * 1024 THEN
        RAISE EXCEPTION 'Фон превышает лимит 2 МБ';
    END IF;

    -- A fulfilled request is immutable. Only report success when the exact
    -- personal design is already owned; never allocate a second skin.
    IF v_request.status = 'fulfilled' THEN
        IF EXISTS (
            SELECT 1 FROM user_wallet_skins uws
            JOIN wallet_skins ws ON ws.id = uws.skin_id
            WHERE uws.telegram_id = v_user_id
              AND ws.title = v_title
              AND ws.image_sha256 = v_digest
              AND ws.is_template = FALSE
        ) THEN
            RAISE NOTICE 'Уже установлено ранее: заявка #%', v_request.id;
            RETURN;
        END IF;
        RAISE EXCEPTION 'Заявка #% уже выполнена, но этот дизайн отсутствует. Нужна проверка', v_request.id;
    END IF;
    -- The owner panel can legitimately move an already-paid request to
    -- "processing" before the personal design has been installed.
    IF v_request.status NOT IN ('pending', 'processing') THEN
        RAISE EXCEPTION 'Неожиданный статус заявки #%: %', v_request.id, v_request.status;
    END IF;

    PERFORM 1 FROM users WHERE telegram_id = v_user_id FOR UPDATE;

    SELECT id INTO v_skin_id
    FROM wallet_skins
    WHERE title = v_title
      AND image_sha256 = v_digest
      AND is_template = FALSE
    ORDER BY id
    LIMIT 1 FOR UPDATE;

    IF v_skin_id IS NULL THEN
        INSERT INTO wallet_skins (
            title, description, text_theme, image_mime, image_data,
            image_sha256, image_width, image_height,
            is_template, is_active, created_at
        ) VALUES (
            v_title,
            'Индивидуальный фон за 500 🐾, Telegram ID 7992643360, заявка #' || v_request.id,
            'light', 'image/webp', v_image_bytes,
            v_digest, 1200, 750,
            FALSE, TRUE, NOW()
        ) RETURNING id INTO v_skin_id;
    ELSE
        UPDATE wallet_skins SET is_active = TRUE WHERE id = v_skin_id;
    END IF;

    UPDATE user_wallet_skins
    SET is_active = FALSE
    WHERE telegram_id = v_user_id
      AND skin_id <> v_skin_id
      AND is_active = TRUE;

    INSERT INTO user_wallet_skins (telegram_id, skin_id, is_active, acquired_at)
    VALUES (v_user_id, v_skin_id, TRUE, NOW())
    ON CONFLICT (telegram_id, skin_id)
    DO UPDATE SET is_active = TRUE;

    UPDATE spend_requests
    SET status = 'fulfilled', processed_at = NOW()
    WHERE id = v_request.id;

    INSERT INTO admin_audit (action, target_telegram_id, details, created_at)
    VALUES (
        'wallet_skin_assigned', v_user_id,
        'Оплаченная заявка #' || v_request.id || ': «' || v_title || '», skin #' || v_skin_id,
        NOW()
    );

    INSERT INTO wallet_notifications (telegram_id, kind, title, body, is_read, created_at)
    SELECT v_user_id, 'appeal', 'Ваш дизайн готов', v_notice, FALSE, NOW()
    WHERE NOT EXISTS (
        SELECT 1 FROM wallet_notifications
        WHERE telegram_id = v_user_id
          AND title = 'Ваш дизайн готов'
          AND body = v_notice
    );

    INSERT INTO telegram_relay_outbox (source_key, chat_id, body, state, attempts, created_at)
    VALUES (
        'custom_wallet_7992643360_20261030', v_user_id,
        v_notice, 'pending', 0, NOW()
    ) ON CONFLICT (source_key) DO NOTHING;

    RAISE NOTICE 'Установлен дизайн «%»: Telegram ID %, заявка #%, skin #%',
        v_title, v_user_id, v_request.id, v_skin_id;
END
$install$;

COMMIT;

SELECT sr.id AS request_id, sr.status, uws.skin_id, uws.is_active,
       ws.title, ws.text_theme, ws.image_width, ws.image_height
FROM spend_requests sr
JOIN user_wallet_skins uws ON uws.telegram_id = sr.telegram_id
JOIN wallet_skins ws ON ws.id = uws.skin_id
WHERE sr.telegram_id = 7992643360
  AND sr.reward_title = 'Уникальный фон карточки'
  AND sr.cost = 500
  AND (sr.created_at AT TIME ZONE 'Europe/Moscow')::date = DATE '2026-10-30'
  AND ws.title = 'Тихий гербарий';
