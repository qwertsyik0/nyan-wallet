#!/usr/bin/env python3
"""Open/close and announce Nyan Quest registration from the existing bot host.

Runs on mjodgiver as nyanteam (never on FirstVDS):
  /home/nyanteam/new_bot/venv/bin/python nyan_quest_termius.py open --chat @nyanquests
  /home/nyanteam/new_bot/venv/bin/python nyan_quest_termius.py close --chat @nyanquests
For the private Quest group use --chat -100YOUR_CHAT_ID.
"""
from __future__ import annotations
import argparse, hashlib, hmac, json, os, time, urllib.error, urllib.parse, urllib.request
from pathlib import Path

try:
    from dotenv import dotenv_values
except ImportError:
    dotenv_values = lambda _path: {}

ENV = dotenv_values('/home/nyanteam/new_bot/.env')
TOKEN = (os.getenv('BOT_TOKEN') or ENV.get('BOT_TOKEN') or ENV.get('TELEGRAM_BOT_TOKEN') or '').strip()
API = (os.getenv('NYAN_QUEST_API_URL') or ENV.get('NYAN_QUEST_API_URL') or
       os.getenv('NYAN_WALLET_API') or ENV.get('NYAN_WALLET_API') or
       'https://nyan-wallet-bridge.qwertsyik.workers.dev').rstrip('/')
BOT_ENDPOINT = f'https://api.telegram.org/bot{TOKEN}/'
PAGE_LINK = 'https://t.me/nyancash_bot?startapp=nyan_quest'


def request(url: str, payload: dict, *, headers: dict | None = None) -> dict:
    data = json.dumps(payload, ensure_ascii=False).encode('utf-8')
    req = urllib.request.Request(url, data=data, headers={'Content-Type':'application/json', **(headers or {})}, method='POST')
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            result = json.load(response)
    except urllib.error.HTTPError as error:
        try:
            detail = json.loads(error.read(4096).decode('utf-8')).get('detail', 'ошибка Telegram/API')
        except Exception:
            detail = f'HTTP {error.code}'
        raise RuntimeError(f'HTTP {error.code}: {detail}') from error
    if not result.get('ok'):
        raise RuntimeError('API не подтвердил действие: ' + str(result)[:400])
    return result.get('result', result)


def telegram(method: str, payload: dict) -> dict:
    return request(BOT_ENDPOINT + method, payload)


def action_on_api(action: str, chat_id: int) -> dict:
    stamp = str(int(time.time()))
    signature = hmac.new(TOKEN.encode(), f'nyan-quest:{action}:v1:{chat_id}:{stamp}'.encode(), hashlib.sha256).hexdigest()
    return request(API + '/api/internal/nyan-quest/' + action, {}, headers={
        'X-Nyan-Quest-Chat': str(chat_id),
        'X-Nyan-Quest-Time': stamp,
        'X-Nyan-Quest-Signature': signature,
    })


def main():
    parser = argparse.ArgumentParser(description='NYAN QUEST: registration management')
    parser.add_argument('action', choices=('open', 'close', 'publish'))
    parser.add_argument('--chat', default='@nyanquests', help='@nyanquests or a numeric group id, e.g. -100...')
    opts = parser.parse_args()
    if not TOKEN:
        raise RuntimeError('BOT_TOKEN не найден в переменных бота')
    if not API.startswith('https://'):
        raise RuntimeError('Для API необходим HTTPS: укажи NYAN_QUEST_API_URL')
    chat = telegram('getChat', {'chat_id': opts.chat})
    chat_id = int(chat['id'])
    print('Цель:', chat.get('title') or chat.get('username') or chat_id)
    if opts.action == 'close':
        result = action_on_api('close', chat_id)
        print(f"OK: запись #{result['round_id']} закрыта. Участников: {result['players']}")
        return
    if opts.action == 'open':
        round_ = action_on_api('open', chat_id)
        print('Регистрация открыта, номер:', round_['round_id'])
    text = (
        '🩸 <b>ТЕБЯ УЖЕ ЖДУТ ПО ТУ СТОРОНУ.</b>\n\n'
        '<b>NYAN QUEST | ЗАПИСЬ НА КВЕСТ ОТКРЫТА</b>\n\n'
        'здесь обычные решения оборачиваются чужими судьбами. '
        'ты можешь войти добровольно. а вот уйти — не обещаем.\n\n'
        'жми кнопку, чтобы попасть в список участников. '
        'запись подтверждается в Telegram автоматически.\n\n'
        '<b>последний шанс перед тем, как дверь закроется.</b>'
    )
    try:
        message = telegram('sendMessage', {
            'chat_id': chat_id,
            'text': text,
            'parse_mode': 'HTML',
            'link_preview_options': {'is_disabled': True},
            'reply_markup': {'inline_keyboard': [[{'text':'🩸 ЗАПИСАТЬСЯ НА КВЕСТ', 'url':PAGE_LINK}]]},
        })
    except Exception as exc:
        print('Внимание: запись на сервере открыта, но объявление не опубликовано.', flush=True)
        print('После проверки прав бота повтори действие publish с тем же --chat (без нового набора).', flush=True)
        raise
    msg_id = message['message_id']
    print('OK: пост опубликован, ID', msg_id)
    if str(opts.chat).startswith('@'):
        print(f"https://t.me/{str(opts.chat).lstrip('@')}/{msg_id}")
    else:
        print(f"https://t.me/c/{str(abs(chat_id))[3:]}/{msg_id}" if str(chat_id).startswith('-100') else f'ID сообщения: {msg_id}')

if __name__ == '__main__':
    try: main()
    except Exception as exc:
        raise SystemExit('ОШИБКА: ' + str(exc)) from exc
