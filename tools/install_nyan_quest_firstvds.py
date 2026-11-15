#!/usr/bin/env python3
"""Install only Nyan Quest signup API on the existing FirstVDS Nyan Wallet.

root@qwertsyik:
  python3 /root/install_nyan_quest_firstvds.py --check
  python3 /root/install_nyan_quest_firstvds.py --apply

No git pull, other local changes are preserved. Backs up and rolls back on failure.
"""
from __future__ import annotations

import argparse
import ast
import datetime
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path('/opt/nyan-wallet')
SERVICE = 'nyan-wallet'
INIT = ROOT / 'server/__init__.py'
MODULE = ROOT / 'server/nyan_quest_signup.py'
MODULE_URL = 'https://raw.githubusercontent.com/qwertsyik0/nyan-wallet/main/server/nyan_quest_signup.py'
MODULE_GIT_BLOB = '821de28d0e90da963a28020076bed1aab55cd5ed'
IMPORT = 'from .nyan_quest_signup import register_nyan_quest_signup'
CALL = '    register_nyan_quest_signup(backend_app.app)'
ROUTES = ('/api/nyan-quest/status', '/api/nyan-quest/join', '/api/internal/nyan-quest/open', '/api/internal/nyan-quest/close')


def run(*args: str, timeout: int = 90) -> str:
    proc = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    if proc.returncode:
        raise RuntimeError(f"{args[0]} failed: " + (proc.stderr or proc.stdout)[-1000:])
    return proc.stdout.strip()


def atom(path: Path, value: bytes) -> None:
    fd, tmp = tempfile.mkstemp(prefix='.nyan-quest-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(value)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, (path.stat().st_mode & 0o777) if path.exists() else 0o644)
        os.replace(tmp, path)
    finally:
        Path(tmp).unlink(missing_ok=True)


def new_module() -> bytes:
    req = urllib.request.Request(MODULE_URL, headers={'User-Agent': 'NyanQuestFirstVDSInstaller/1.0'})
    with urllib.request.urlopen(req, timeout=25) as resp:
        body = resp.read(100001)
    if hashlib.sha1(b'blob ' + str(len(body)).encode() + b'\0' + body).hexdigest() != MODULE_GIT_BLOB:
        raise RuntimeError('Код API в GitHub отличается от проверенной версии. Установка отменена.')
    if len(body) > 100000:
        raise RuntimeError('Модуль больше ожидаемого')
    ast.parse(body.decode('utf-8'), filename='nyan_quest_signup.py')
    return body


def patch(src: str) -> str:
    ast.parse(src, filename='server/__init__.py')
    has_import = IMPORT in src
    has_call = CALL in src
    if has_import != has_call:
        raise RuntimeError('В __init__.py обнаружено частичное подключение Quest')
    if has_import and has_call:
        return src
    if 'from .nyan_story_signup import register_nyan_story_signup' not in src:
        raise RuntimeError('Не найдено место для нового импорта, исходник изменён')
    if '    register_nyan_story_signup(backend_app.app)' not in src:
        raise RuntimeError('Не найдено место для вызова регистрации, исходник изменён')
    src = src.replace('from .nyan_story_signup import register_nyan_story_signup',
                      'from .nyan_story_signup import register_nyan_story_signup\n' + IMPORT, 1)
    src = src.replace('    register_nyan_story_signup(backend_app.app)',
                      '    register_nyan_story_signup(backend_app.app)\n' + CALL, 1)
    ast.parse(src, filename='server/__init__.py patched')
    return src


def ready(attempts: int = 60) -> None:
    url = 'http://127.0.0.1:8000/openapi.json'
    last = ''
    for i in range(attempts):
        try:
            if run('systemctl','is-active', SERVICE) != 'active':
                raise RuntimeError('служба неактивна')
            with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(url, timeout=5) as resp:
                import json
                paths = json.load(resp).get('paths',{})
            if not all(route in paths for route in ROUTES):
                raise RuntimeError('не появились маршруты Quest API')
            return
        except Exception as e:
            last = str(e)
            if i+1<attempts:
                time.sleep(2)
    raise RuntimeError('Не удалось подтвердить запуск Quest API: ' + last)


def main() -> None:
    ap=argparse.ArgumentParser()
    group=ap.add_mutually_exclusive_group(required=True)
    group.add_argument('--check', action='store_true')
    group.add_argument('--apply', action='store_true')
    opts=ap.parse_args()
    if os.geteuid()!=0:
        raise RuntimeError('Запускай от root на FirstVDS')
    if not INIT.is_file() or INIT.is_symlink() or MODULE.is_symlink():
        raise RuntimeError('Исходный сервер Nyan Wallet не найден или используются symlinks')
    previous_init=INIT.read_bytes()
    previous_module=MODULE.read_bytes() if MODULE.exists() else None
    new_init=patch(previous_init.decode('utf-8')).encode('utf-8')
    new_body=new_module()
    changes = [(p,old,new) for p,old,new in (
        (INIT,previous_init,new_init), (MODULE,previous_module,new_body)
    ) if old != new]
    if opts.check:
        print('OK: проверка пройдена. Ничего не изменено.')
        print('Будут изменены:', ', '.join(p.name for p,_,_ in changes) or 'ничего')
        print('API будет перезапущен только при --apply')
        return
    if not changes:
        ready(3)
        print('Quest API уже установлен и работает')
        return
    stamp=datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d-%H%M%S-%f')
    backup=ROOT/'.nyan-quest-backups'/stamp
    backup.mkdir(parents=True, mode=0o700)
    os.chmod(backup, 0o700)
    for path, old, _ in changes:
        if old is not None:
            saved=backup/path.name
            saved.write_bytes(old)
            os.chmod(saved, 0o600)
    try:
        for path,_,new in changes:
            atom(path,new)
        run('/opt/nyan-wallet/.venv/bin/python','-m','py_compile',str(INIT),str(MODULE))
        run('systemctl','restart',SERVICE)
        ready()
    except Exception as error:
        for path,old,_ in reversed(changes):
            if old is None:path.unlink(missing_ok=True)
            else:atom(path,old)
        try:
            run('systemctl','restart',SERVICE)
            run('systemctl','is-active',SERVICE)
        except Exception as recovery:
            raise RuntimeError(f'Ошибка установки: {error}. Откат требует внимания: {recovery}. Бэкап {backup}') from error
        raise RuntimeError(f'Ошибка установки: {error}. Предыдущие файлы восстановлены. Бэкап {backup}') from error
    print('OK: NYAN QUEST API установлен, все 4 маршрута доступны.')
    print('Резервная копия:',backup)
    print('Запись не открыта, посты не публиковались.')

if __name__=='__main__':
    try:main()
    except Exception as error:raise SystemExit('ОШИБКА: '+str(error)) from error