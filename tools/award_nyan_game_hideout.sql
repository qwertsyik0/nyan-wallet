-- NYAN GAME: award the three sold copies of 'Тайник Няника'.
-- Requires /tmp/nyan-game-nyanik-hideout-limited.webp.
-- Idempotent and atomic; no Lapcoin balances are changed by this installer.
BEGIN;

SELECT pg_advisory_xact_lock(20261028, 30003);

DO $award$
DECLARE
    expected_hash CONSTANT TEXT := 'e5e9422afa42ed65dacfdb4755062fffc128560568ce934aaa2224710e11497d';
    design_title CONSTANT TEXT := 'NYAN GAME · Тайник Няника';
    notice_title CONSTANT TEXT := '🌸 Приз NYAN GAME';
    notice_body CONSTANT TEXT := 'Вам установлен лимитированный дизайн «Тайник Няника» в Nyan Wallet.';
    nickname TEXT;
    recipient_id BIGINT;
    matches INTEGER;
    image_bytes BYTEA;
    design_id INTEGER;
BEGIN
    -- Check all three buyers before modifying any account.
    FOREACH nickname IN ARRAY ARRAY['liviskas', 'zedhxyd', 'zrxwt'] LOOP
        SELECT COUNT(*) INTO matches
        FROM users WHERE LOWER(username) = nickname;
        IF matches <> 1 THEN
            RAISE EXCEPTION 'Не удалось однозначно найти @%: % совпадений', nickname, matches;
        END IF;
    END LOOP;

    image_bytes := pg_read_binary_file('/tmp/nyan-game-nyanik-hideout-limited.webp');
    IF ENCODE(SHA256(image_bytes), 'hex') <> expected_hash THEN
        RAISE EXCEPTION 'Хеш файла Тайника Няника неверный: выдача отменена';
    END IF;

    SELECT id INTO design_id
    FROM wallet_skins
    WHERE title = design_title
      AND image_sha256 = expected_hash
      AND is_template = FALSE
    ORDER BY id LIMIT 1 FOR UPDATE;

    IF design_id IS NULL THEN
        INSERT INTO wallet_skins (
            title, description, text_theme, image_mime, image_data,
            image_sha256, image_width, image_height,
            is_template, is_active, created_at
        ) VALUES (
            design_title,
            'Лимитированный фон NYAN GAME, три экземпляра за 15 билетов: @liviskas, @zedhxyd, @zrxwt.',
            'dark', 'image/webp', image_bytes,
            expected_hash, 1536, 1024, FALSE, TRUE, NOW()
        ) RETURNING id INTO design_id;
    END IF;

    FOREACH nickname IN ARRAY ARRAY['liviskas', 'zedhxyd', 'zrxwt'] LOOP
        SELECT telegram_id INTO recipient_id
        FROM users WHERE LOWER(username) = nickname
        FOR UPDATE;

        UPDATE user_wallet_skins
        SET is_active = FALSE
        WHERE telegram_id = recipient_id
          AND skin_id <> design_id
          AND is_active = TRUE;

        INSERT INTO user_wallet_skins (
            telegram_id, skin_id, is_active, acquired_at
        ) VALUES (recipient_id, design_id, TRUE, NOW())
        ON CONFLICT (telegram_id, skin_id)
        DO UPDATE SET is_active = TRUE;

        INSERT INTO wallet_notifications (
            telegram_id, kind, title, body, is_read, created_at
        )
        SELECT recipient_id, 'appeal', notice_title, notice_body, FALSE, NOW()
        WHERE NOT EXISTS (
            SELECT 1 FROM wallet_notifications
            WHERE telegram_id = recipient_id
              AND title = notice_title
              AND body = notice_body
        );

        INSERT INTO telegram_relay_outbox (
            source_key, chat_id, body, state, attempts, created_at
        ) VALUES (
            'nyan_game_hideout_20261028_' || nickname,
            recipient_id, notice_body, 'pending', 0, NOW()
        ) ON CONFLICT (source_key) DO NOTHING;

        RAISE NOTICE 'NYAN GAME: Тайник Няника skin #%, @%, Telegram ID %',
            design_id, nickname, recipient_id;
    END LOOP;
END
$award$;

COMMIT;