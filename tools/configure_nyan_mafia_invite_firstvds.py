#!/usr/bin/env python3
"""Enable the separate NYAN MAFIA Telegram deep link; never start a game.

Run on FirstVDS: python3 configure_nyan_mafia_invite_firstvds.py
"""
from __future__ import annotations

import datetime
import os
import re
import shutil
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ENV = Path('/etc/nyan-wallet/nyan-mafia-group.env')
BACKUPS = Path('/opt/nyan-wallet/.nyan-mafia-backups')
GAME_URL = 'https://t.me/nyancash_bot?startapp=nyan_mafia'
PAGE = 'https://qwertsyik0.github.io/nyan-wallet/nyan-mafia.html'
GROUP = '-1004368587366'
NAME = 'NYAN_MAFIA_INVITE_URL'


def command(*args: str) -> str:
    result = subprocess.run(args, capture_output=True, text=True, timeout=75)
    if result.returncode:
        raise RuntimeError((result.stderr or result.stdout or str(args))[-550:])
    return result.stdout.strip()


def validate_live_site() -> None:
    for path in (PAGE, PAGE.replace('.html', '.js'),
                 'https://qwertsyik0.github.io/nyan-wallet/assets/nyan-mafia/cover.webp'):
        req = urllib.request.Request(path, method='GET', headers={'User-Agent': 'NYAN-MAFIA-Installer/1.0'})
        try:
            with urllib.request.urlopen(req, timeout=12) as response:
                if response.status != 200 or not response.read(64):
                    raise RuntimeError('Пустая страница: ' + path)
        except (urllib.error.URLError, TimeoutError) as exc:
            raise RuntimeError('Страница игры ещё недоступна: ' + path + ' (' + str(exc)[:160] + ')') from exc


def atomic_write(path: Path, content: bytes, mode: int) -> None:
    fd, temporary = tempfile.mkstemp(prefix='.nyan-mafia-invite-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as file:
            file.write(content)
            file.flush()
            os.fsync(file.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def test_service() -> None:
    last = ''
    for _ in range(20):
        try:
            if command('systemctl', 'is-active', 'nyan-wallet') != 'active':
                raise RuntimeError('systemd: не active')
            pid = int(command('systemctl', 'show', 'nyan-wallet', '--property=MainPID', '--value'))
            if pid < 1:
                raise RuntimeError('нет главного процесса')
            values = set(Path(f'/proc/{pid}/environ').read_bytes().split(b'\0'))
            for expected in (f'NYAN_MAFIA_GROUP_ID={GROUP}', f'{NAME}={GAME_URL}'):
                if expected.encode() not in values:
                    raise RuntimeError('не применено: ' + expected)
            for route in ('status', 'messages'):
                req = urllib.request.Request('http://127.0.0.1:8000/api/nyan-mafia/' + route)
                try:
                    urllib.request.urlopen(req, timeout=4)
                    raise RuntimeError('API пропускает запрос без Telegram')
                except urllib.error.HTTPError as exc:
                    if exc.code != 401:
                        raise RuntimeError(f'API {route}: HTTP {exc.code}') from exc
            return
        except Exception as exc:
            last = str(exc)
            time.sleep(2)
    raise RuntimeError('после перезапуска: ' + last)


def main() -> None:
    if os.geteuid() != 0:
        raise RuntimeError('запусти под root на FirstVDS')
    if not ENV.is_file() or ENV.is_symlink():
        raise RuntimeError('не найдена конфигурация Nyan Games: /etc/nyan-wallet/nyan-mafia-group.env')
    if command('systemctl', 'is-active', 'nyan-wallet') != 'active':
        raise RuntimeError('сервис nyan-wallet не запущен')
    before = ENV.read_bytes()
    raw = before.decode('utf-8')
    if not re.search(r'^\s*NYAN_MAFIA_GROUP_ID\s*=\s*' + re.escape(GROUP) + r'\s*$', raw, re.M):
        raise RuntimeError('ID группы Nyan Games отличается от ожидаемого')
    matches = list(re.finditer(r'^\s*(?:export\s+)?' + NAME + r'\s*=.*$', raw, re.M))
    if len(matches) > 1:
        raise RuntimeError('повторная запись ' + NAME + ' в конфигурации')
    line = NAME + '=' + GAME_URL
    if matches:
        m = matches[0]
        updated = raw[:m.start()] + line + raw[m.end():]
    else:
        updated = raw.rstrip('\n') + '\n' + line + '\n'
    print('NYAN MAFIA: группа Nyan Games ' + GROUP)
    print('NYAN MAFIA: ссылка ' + GAME_URL)
    print('проверяю доступность опубликованной страницы…', flush=True)
    validate_live_site()
    print('страница и изображения доступны')
    if before == updated.encode():
        try:
            test_service()
            print('OK: ссылка уже настроена, повторных действий нет')
            return
        except Exception:
            pass
    BACKUPS.mkdir(parents=True, exist_ok=True)
    backup = BACKUPS / ('invite-env-' + datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d-%H%M%S-%f'))
    shutil.copy2(ENV, backup)
    mode = ENV.stat().st_mode & 0o777
    try:
        atomic_write(ENV, updated.encode(), mode)
        command('systemctl', 'restart', 'nyan-wallet')
        test_service()
    except Exception:
        atomic_write(ENV, before, mode)
        try:
            command('systemctl', 'restart', 'nyan-wallet')
        except Exception as rollback_error:
            print('ВНИМАНИЕ: не удалось перезапустить прежнюю конфигурацию:', rollback_error)
        raise
    print('OK: игровая ссылка включена, Nyan Games настроена, API защищён')
    print('резервная копия:', backup)
    print('сообщения не отправлялись, регистрация не открывалась')
    print('теперь владелец может написать /mafia боту в личном чате')


if __name__ == '__main__':
    try:
        main()
    except Exception as err:
        raise SystemExit('ОШИБКА: ' + str(err)) from err