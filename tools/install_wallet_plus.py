#!/usr/bin/env python3
"""Install wallet tools additively on the existing Nyan Wallet VPS."""
import argparse
from datetime import datetime, timezone
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
import urllib.request
import json

FILES=["server/wallet_plus.py","server/transfers.py","server/extended_features.py","server/advanced_features.py","server/wallet_tools.py","server/prize_gifts.py","server/nyan_world.py","advanced_features.js","wallet-plus.html","wallet-plus.js","wallet-plus.css","wallet-plus-entry.js","wallet-tools.css"]
HOOK="\n# WALLET_PLUS_V1\nfrom .wallet_plus import register_wallet_plus, m as wallet_plus_metadata\nif os.getenv('NYAN_RESTORE_SCHEMA_ONLY') == '1':\n    wallet_plus_metadata.create_all(backend_app.engine)\nelse:\n    register_wallet_plus(backend_app.app)\n"
def value(name):
    return subprocess.check_output(["systemctl","show","nyan-wallet","-p",name,"--value"],text=True).strip()
def atomic(path,data):
    path.parent.mkdir(parents=True,exist_ok=True)
    fd,name=tempfile.mkstemp(prefix=".world-",dir=path.parent)
    try:
        with os.fdopen(fd,"wb") as f:
            f.write(data);f.flush();os.fsync(f.fileno())
        os.chmod(name,0o644)
        os.replace(name,path)
    finally:
        Path(name).unlink(missing_ok=True)
def ready(world):
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    deadline=time.monotonic()+120
    while time.monotonic()<deadline:
        try:
            with opener.open("http://127.0.0.1:8000/api/health",timeout=3) as r:
                if not json.load(r).get("ok"): raise ValueError()
            if world:
                with opener.open("http://127.0.0.1:8000/openapi.json",timeout=3) as r:
                    paths=json.load(r).get("paths",{})
                if "/api/wallet-plus/state" not in paths or "/api/wallet-plus/freeze" not in paths: raise ValueError()
            return
        except Exception:
            time.sleep(2)
    raise RuntimeError("API не подтвердил готовность за 120 секунд")
def main():
    parser=argparse.ArgumentParser();parser.add_argument("--ref",required=True);parser.add_argument("--frontend-only",action="store_true")
    args=parser.parse_args()
    if args.frontend_only: raise RuntimeError("Для подключения нужен backend, убери --frontend-only")
    if not re.fullmatch(r"[a-f0-9]{40}",args.ref): raise RuntimeError("нужен SHA версии")
    if os.geteuid()!=0 or value("ActiveState")!="active": raise RuntimeError("запусти под root на VPS работающего кошелька")
    root=Path(value("WorkingDirectory"))
    if not root.is_absolute() or not (root/"server/__init__.py").is_file(): raise RuntimeError("папка API не найдена")
    updated={}
    for file in FILES:
        if args.frontend_only and file.startswith("server/"): continue
        path=root/file
        if path.is_symlink(): raise RuntimeError("символические ссылки не поддерживаются")
        with urllib.request.urlopen("https://raw.githubusercontent.com/qwertsyik0/nyan-wallet/"+args.ref+"/"+file,timeout=30) as response:
            updated[file]=response.read()
        if file.endswith(".py"): compile(updated[file],file,"exec")
    init=root/"server/__init__.py"
    source=init.read_text()
    if "register_wallet_plus(" not in source:
        source+=HOOK
    compile(source,str(init),"exec")
    if not args.frontend_only: updated["server/__init__.py"]=source.encode()
    index=root/"index.html"
    if not index.is_file(): raise RuntimeError("index.html не найден")
    html=index.read_text()
    if "wallet-plus-entry.js" not in html:
        if "</body>" not in html: raise RuntimeError("не найден якорь index.html")
        html=html.replace("</body>",'<script src="./wallet-plus-entry.js?v=20261126-plus2"></script>\n</body>',1)
    html=re.sub(r'advanced_features\.js(?:\?[^"\s>]*)?', "advanced_features.js?v=20261126-plus2",html)
    updated["index.html"]=html.encode()
    originals={file:(root/file).read_bytes() if (root/file).exists() else None for file in updated}
    backup=root/".wallet-plus-backups"/datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
    backup.mkdir(parents=True,mode=0o700)
    for file,data in originals.items():
        if data is not None:
            dest=backup/file;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(data)
    (backup/"manifest.json").write_text(json.dumps({k:v is not None for k,v in originals.items()}))
    ready(False)
    try:
        for file,data in updated.items(): atomic(root/file,data)
        if not args.frontend_only:
            subprocess.run(["systemctl","restart","nyan-wallet"],check=True)
            ready(True)
    except BaseException:
        for file,data in originals.items():
            if data is None: (root/file).unlink(missing_ok=True)
            else: atomic(root/file,data)
        if not args.frontend_only:
            subprocess.run(["systemctl","restart","nyan-wallet"],check=False)
            print("Код возвращён к прежней версии. Проверяем запуск…",flush=True)
            ready(False)
        raise
    print("Инструменты обновлены без перезапуска API." if args.frontend_only else "Возможности Nyan Wallet установлены. API проверен.")
    print("Резервная копия:",backup)
    print("Переоткрой кошелёк. На главном экране появилась карточка Мои возможности.")
    print("Личные балансы не изменялись.")
if __name__=="__main__":
    try: main()
    except Exception as error: raise SystemExit("Ошибка установки: "+str(error))


