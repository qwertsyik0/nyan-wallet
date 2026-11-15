# Nyan Quest — отдельная регистрация

Система независима от Nyan Games /story. Страница: `nyan-quest-signup.html`.
Фон: оригинальное изображение «NYAN QUEST — запись на квест» из чата, оптимизированное для WebView и встроенное в HTML (нет внешнего хостинга картинки).

## Как это работает

1. Владелец на SprintHost (mjodgiver, пользователь nyanteam) запускает `nyan_quest.py open --chat <ID_ГРУППЫ>`.
2. CLI разрешает @username/числовой chat ID через Telegram `getChat`, вызывает подписанный HMAC API FirstVDS и публикует сообщение с кнопкой `https://t.me/nyancash_bot?startapp=nyan_quest`.
3. Гость открывает настоящую Telegram Mini App. `index.html` переправляет `startapp=nyan_quest` на отдельную страницу.
4. Сервер проверяет Telegram `initData`; по кнопке `ЗАПИСАТЬСЯ` добавляет Telegram ID/username/first_name в `nyan_quest_signups`.
5. В **той же транзакции** создаётся одно личное уведомление владельцу в очереди `TelegramRelayMessage` с `source_key` по ID набора и Telegram ID. Повторная запись не дублирует заявку и уведомление.
6. `nyan_quest.py close --chat <ID_ТОЙ_ЖЕ_ГРУППЫ>` закрывает набор. Последняя заявка сохраняется в БД.

Не нужен @username: если его нет, сохраняется имя и Telegram ID. Нет произвольных полей, вводимых посетителем.

## Одноразовое развёртывание на FirstVDS

В Termius `root@qwertsyik`:

```bash
curl -fsSLo /root/install_nyan_quest_firstvds.py \
  https://raw.githubusercontent.com/qwertsyik0/nyan-wallet/main/tools/install_nyan_quest_firstvds.py
python3 /root/install_nyan_quest_firstvds.py --check
python3 /root/install_nyan_quest_firstvds.py --apply
```

Проверка выполняется без изменений. Установщик копирует только `server/nyan_quest_signup.py` и добавляет два вызова в локальный `server/__init__.py`. Не выполняет `git pull` поверх живого FirstVDS. Сохраняет оригиналы в `.nyan-quest-backups`, проверяет syntax, перезапускает API и ожидает маршруты; при ошибке восстанавливает исходные файлы.

Не открывает набор и не рассылает анонсы автоматически.

## Публикация из Termius на хосте бота

В Termius `nyanteam@mjodgiver`:

```bash
curl -fsSLo /home/nyanteam/nyan_quest.py \
  https://raw.githubusercontent.com/qwertsyik0/nyan-wallet/main/tools/nyan_quest_publish_termius.py
/home/nyanteam/new_bot/venv/bin/python /home/nyanteam/nyan_quest.py open --chat @nyanquests
```

Для приватной группы укажи её **числовой** ID `-100...` вместо `@nyanquests`. `@nyanquests` означает публичный **канал**, не приватную группу.

Повторить объявление без нового набора:

```bash
/home/nyanteam/new_bot/venv/bin/python /home/nyanteam/nyan_quest.py publish --chat @nyanquests
```

Закрыть набор:

```bash
/home/nyanteam/new_bot/venv/bin/python /home/nyanteam/nyan_quest.py close --chat @nyanquests
```

Для записи и личных уведомлений требуется рабочий Telegram Relay между FirstVDS и ботом, иначе API вернёт 503 и отказ от записи — **система не должна молча терять заявки**. Не публикуй анонс, пока API не установлен и Telegram Relay не работает.

## Проверка

- Открытие в обычном браузере показывает фон и приглашение открыть Telegram.
- В Telegram статус `registration`, затем кнопка записи, затем подтверждение.
- Повторная запись возвращает `new:false`.
- После закрытия новые записи отклоняются.
- Проверка в БД: `SELECT * FROM nyan_quest_signups ORDER BY joined_at DESC LIMIT 10;`.

## Дальнейшие улучшения

Отдельные лимиты мест и резервный список, подтверждение ведущим, кнопка отмены записи, автоматическое сообщение группе о закрытии набора, рейтинг участников после квеста, защита от флуда повторными запросами.
