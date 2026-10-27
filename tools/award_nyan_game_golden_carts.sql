-- Install both limited NYAN GAME Golden Cart wallet backgrounds.
-- Requires two verified WebP files in /tmp, downloaded from this repository.
-- The transaction is atomic and can be rerun safely.
BEGIN;

SELECT pg_advisory_xact_lock(20261028, 30002);

DO $award$
DECLARE
    prize RECORD;
    v_telegram_id BIGINT;
    v_matches INTEGER;
    v_image_bytes BYTEA;
    v_skin_id INTEGER;
    v_title TEXT;
    v_notice TEXT;
BEGIN
    FOR prize IN
        SELECT * FROM (VALUES
            (
                'PIXEL_ARE_YOU_OKAY', '01',
                '/tmp/nyan-game-golden-cart-01-pixel.webp',
                '176d481d9400df74b6c14d4cad27e623e336c5354714b7298dea801e0ef622f8',
                'nyan_game_golden_cart_01_20261028'
            ),
            (
                'assstre', '02',
                '/tmp/nyan-game-golden-cart-02-assstre.webp',
                '641c1a293fe1d42b536e92e9c8a6b1b793060bced50da7237ab815f6ecb1a013',
                'nyan_game_golden_cart_02_20261028'
            )
        ) AS p(username, edition, filepath, digest, source_key)
    LOOP
        SELECT COUNT(*), MIN(telegram_id)
        INTO v_matches, v_telegram_id
        FROM users
        WHERE LOWER(username) = LOWER(prize.username);

        IF v_matches <> 1 THEN
            RAISE EXCEPTION 'Неоднозначный или отсутствующий пользователь @%: % совпадений',
                prize.username, v_matches;
        END IF;

        PERFORM 1 FROM users WHERE telegram_id = v_telegram_id FOR UPDATE;

        v_image_bytes := pg_read_binary_file(prize.filepath);
        IF ENCODE(SHA256(v_image_bytes), 'hex') <> prize.digest THEN
            RAISE EXCEPTION 'Хеш изображения для @% не совпадает: установка отменена',
                prize.username;
        END IF;

        v_title := 'NYAN GAME · Золотая тележка №' || prize.edition;
        v_notice := 'Ваш приз NYAN GAME — золотой дизайн «Золотая тележка №'
                    || prize.edition || '» установлен в Nyan Wallet.';

        SELECT id INTO v_skin_id
        FROM wallet_skins
        WHERE title = v_title
          AND image_sha256 = prize.digest
          AND is_template = FALSE
        ORDER BY id LIMIT 1
        FOR UPDATE;

        IF v_skin_id IS NULL THEN
            INSERT INTO wallet_skins (
                title, description, text_theme, image_mime, image_data,
                image_sha256, image_width, image_height,
                is_template, is_active, created_at
            ) VALUES (
                v_title,
                'Лимитированный номерной приз NYAN GAME за 22 билета. Получатель: @'
                  || prize.username || '.',
                'dark', 'image/webp', v_image_bytes,
                prize.digest, 1536, 1024, FALSE, TRUE, NOW()
            ) RETURNING id INTO v_skin_id;
        END IF;

        UPDATE user_wallet_skins
        SET is_active = FALSE
        WHERE telegram_id = v_telegram_id
          AND skin_id <> v_skin_id
          AND is_active = TRUE;

        INSERT INTO user_wallet_skins (
            telegram_id, skin_id, is_active, acquired_at
        ) VALUES (v_telegram_id, v_skin_id, TRUE, NOW())
        ON CONFLICT (telegram_id, skin_id)
        DO UPDATE SET is_active = TRUE;

        INSERT INTO wallet_notifications (
            telegram_id, kind, title, body, is_read, created_at
        )
        SELECT v_telegram_id, 'appeal', '✨ Приз NYAN GAME', v_notice, FALSE, NOW()
        WHERE NOT EXISTS (
            SELECT 1 FROM wallet_notifications
            WHERE telegram_id = v_telegram_id
              AND title = '✨ Приз NYAN GAME'
              AND body = v_notice
        );

        INSERT INTO telegram_relay_outbox (
            source_key, chat_id, body, state, attempts, created_at
        ) VALUES (
            prize.source_key, v_telegram_id, v_notice, 'pending', 0, NOW()
        ) ON CONFLICT (source_key) DO NOTHING;

        RAISE NOTICE 'NYAN GAME: Golden Cart #%, skin #%, @%, Telegram ID %',
            prize.edition, v_skin_id, prize.username, v_telegram_id;
    END LOOP;
END
$award$;

COMMIT;