-- Install the one-of-one NYAN GAME gold background only for @mppwb.
-- Requires the verified WebP file at /tmp/nyan-game-legend-mppwb-gold.webp.
-- Can safely be executed again: wallet skin and notices are not duplicated.
BEGIN;

SELECT pg_advisory_xact_lock(20261028, 30001);

DO $award$
DECLARE
    target_id CONSTANT BIGINT := 7723488357;
    expected_digest CONSTANT TEXT := '240fbe749d1ba0c3a907591c90b922437f2f3d822ba98754bd77a3902357ce5f';
    skin_title CONSTANT TEXT := 'NYAN GAME · Легенда Няника';
    notification_title CONSTANT TEXT := '👑 Приз NYAN GAME';
    notification_body CONSTANT TEXT := 'Ваш эксклюзивный золотой дизайн «Легенда Няника» установлен в Nyan Wallet.';
    recipient_username TEXT;
    image_bytes BYTEA;
    v_skin_id INTEGER;
BEGIN
    SELECT username INTO recipient_username
    FROM users
    WHERE telegram_id = target_id
    FOR UPDATE;

    IF NOT FOUND OR COALESCE(LOWER(recipient_username), '') <> 'mppwb' THEN
        RAISE EXCEPTION 'Нельзя установить приз: @mppwb не соответствует Telegram ID %', target_id;
    END IF;

    image_bytes := pg_read_binary_file('/tmp/nyan-game-legend-mppwb-gold.webp');
    IF ENCODE(SHA256(image_bytes), 'hex') <> expected_digest THEN
        RAISE EXCEPTION 'Хеш изображения не совпадает: установка отменена';
    END IF;

    SELECT id INTO v_skin_id
    FROM wallet_skins
    WHERE title = skin_title
      AND image_sha256 = expected_digest
      AND is_template = FALSE
    ORDER BY id
    LIMIT 1
    FOR UPDATE;

    IF v_skin_id IS NULL THEN
        INSERT INTO wallet_skins (
            title, description, text_theme, image_mime, image_data,
            image_sha256, image_width, image_height,
            is_template, is_active, created_at
        ) VALUES (
            skin_title,
            'Единственный золотой дизайн за 30 билетов. Владелец: @mppwb.',
            'dark', 'image/webp', image_bytes,
            expected_digest, 1536, 1024,
            FALSE, TRUE, NOW()
        ) RETURNING id INTO v_skin_id;
    END IF;

    UPDATE user_wallet_skins
    SET is_active = FALSE
    WHERE telegram_id = target_id
      AND skin_id <> v_skin_id
      AND is_active = TRUE;

    INSERT INTO user_wallet_skins (
        telegram_id, skin_id, is_active, acquired_at
    ) VALUES (target_id, v_skin_id, TRUE, NOW())
    ON CONFLICT (telegram_id, skin_id)
    DO UPDATE SET is_active = TRUE;

    INSERT INTO wallet_notifications (
        telegram_id, kind, title, body, is_read, created_at
    )
    SELECT target_id, 'appeal', notification_title, notification_body, FALSE, NOW()
    WHERE NOT EXISTS (
        SELECT 1 FROM wallet_notifications
        WHERE telegram_id = target_id
          AND title = notification_title
          AND body = notification_body
    );

    INSERT INTO telegram_relay_outbox (
        source_key, chat_id, body, state, attempts, created_at
    ) VALUES (
        'nyan_game_legend_mppwb_20261028',
        target_id,
        'Поздравляем! Вам установлен эксклюзивный золотой дизайн «Легенда Няника» в Nyan Wallet.',
        'pending', 0, NOW()
    ) ON CONFLICT (source_key) DO NOTHING;

    RAISE NOTICE 'NYAN GAME: skin #%, Telegram ID % (@mppwb)', v_skin_id, target_id;
END
$award$;

COMMIT;
