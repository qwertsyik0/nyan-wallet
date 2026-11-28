#!/usr/bin/env python3
"""Install the World news editor without replacing the local server registration."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time
import urllib.request

FILES = ["server/world_intro.py", "nyan-world-survey.html", "nyan-world-learn.html", "nyan-world-survey.css", "nyan-world-survey.js", "assets/nyan-world/intro-cats.webp"]
HOOK = """
# WORLD_INTRO_V1
from .world_intro import register_world_intro, m as world_intro_metadata
if os.getenv("NYAN_RESTORE_SCHEMA_ONLY") == "1":
    world_intro_metadata.create_all(backend_app.engine)
else:
    register_world_intro(backend_app.app)
"""


def value(key):
    return subprocess.check_output(
        ["systemctl", "show", "nyan-wallet", "-p", key, "--value"], text=True
    ).strip()


def atomic(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".world-news-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(name, 0o644)
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def ready(editor):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        try:
            with opener.open("http://127.0.0.1:8000/api/health", timeout=3) as response:
                if not json.load(response).get("ok"):
                    raise ValueError("health")
            if editor:
                with opener.open("http://127.0.0.1:8000/openapi.json", timeout=3) as response:
                    paths = json.load(response).get("paths", {})
                    if "/api/world-intro/claim" not in paths:
                        raise ValueError("survey routes")
            return
        except Exception:
            time.sleep(2)
    raise RuntimeError("API не подтвердил готовность за 120 секунд")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ref", required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"[a-f0-9]{40}", args.ref):
        raise RuntimeError("Укажи полный SHA версии")
    if os.geteuid() != 0 or value("ActiveState") != "active":
        raise RuntimeError("Запусти под root на VPS работающего кошелька")
    root = Path(value("WorkingDirectory"))
    if not root.is_absolute() or not (root / "server/nyan_world.py").is_file():
        raise RuntimeError("Не найдена установленная серверная часть NYAN WORLD")
    updated = {}
    for file in FILES:
        path = root / file
        if path.is_symlink():
            raise RuntimeError("Символические ссылки не поддерживаются")
        with urllib.request.urlopen(
            "https://raw.githubusercontent.com/qwertsyik0/nyan-wallet/" + args.ref + "/" + file,
            timeout=30
        ) as response:
            updated[file] = response.read()
        if file.endswith(".py"):
            compile(updated[file], file, "exec")
    init = root / "server/__init__.py"
    if init.is_symlink():
        raise RuntimeError("Символические ссылки не поддерживаются")
    source = init.read_text()
    if "register_world(" not in source:
        raise RuntimeError("NYAN WORLD не подключён к API")
    if "register_world_intro(" not in source:
        source += HOOK
    compile(source, str(init), "exec")
    updated["server/__init__.py"] = source.encode()
    originals = {file: (root / file).read_bytes() if (root / file).exists() else None for file in updated}
    backup = root / ".world-intro-backups" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
    backup.mkdir(parents=True, mode=0o700)
    for file, data in originals.items():
        if data is not None:
            dest = backup / file
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
    (backup / "manifest.json").write_text(json.dumps({k: v is not None for k, v in originals.items()}))
    ready(False)
    try:
        for file, data in updated.items():
            atomic(root / file, data)
        subprocess.run(["systemctl", "restart", "nyan-wallet"], check=True)
        ready(True)
    except BaseException:
        for file, data in originals.items():
            if data is None:
                (root / file).unlink(missing_ok=True)
            else:
                atomic(root / file, data)
        subprocess.run(["systemctl", "restart", "nyan-wallet"], check=False)
        ready(False)
        raise
    print("Опрос установлен. Бонус 370 лапкоинов включён.")
    print("Резервная копия:", backup)



if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        raise SystemExit("Ошибка установки: " + str(error))
