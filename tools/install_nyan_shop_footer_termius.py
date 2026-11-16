#!/usr/bin/env python3
"""Install the NYAN SHOP sign-off into the existing Telegram bot and relay.

Run as nyanteam on mjodgiver. --check reads but does not mutate files.
--apply backs up bot.py and the relay, installs a guarded PTB _post hook,
patches the standalone relay sender and restarts the existing bot. The relay
will be restarted when its startup command can be proven safe.
"""

from __future__ import annotations

import argparse
import ast
import datetime
import hashlib
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import urllib.request

ROOT = Path("/home/nyanteam/new_bot")
BOT = ROOT / "bot.py"
MODULE = ROOT / "nyan_shop_footer.py"
RELAY = Path("/home/nyanteam/nyan_telegram_relay_worker.py")
HELPER = Path("/home/nyanteam/nyan-wallet/tools/nyan_bot_autodeploy.py")
PYTHON = ROOT / "venv/bin/python"
BACKUP_BASE = ROOT / ".nyan-shop-footer-backups"
FOOTER = "♡ больше, чем магазин — @nyanshoping"
MODULE_SHA = "629488e25a642739435efa9e9ab4c57a8538b04c"
SOURCE = (
    "https://raw.githubusercontent.com/qwertsyik0/nyan-wallet/main/"
    "bot_addons/nyan_shop_footer.py"
)
BOT_MARKER = "install_nyan_shop_footer"
RELAY_MARKER = "# NYAN_SHOP_FOOTER_RELAY_V1"
RELAY_ANCHOR = "data=telegram_send_payload(chat_id, text),"
RELAY_CALL = "data=_nyan_shop_footer_payload(telegram_send_payload(chat_id, text)),"
RELAY_HELPER = '''
def _nyan_shop_footer_payload(payload: dict) -> dict:
    # NYAN_SHOP_FOOTER_RELAY_V1
    # This runs after rich invitation JSON parsing and preserves buttons/topics.
    signature = "♡ больше, чем магазин — @nyanshoping"
    value = payload.get("text")
    if isinstance(value, str):
        clean = value.rstrip()
        if (clean and not clean.endswith(signature)
                and len(clean) + 2 + len(signature) <= 4096):
            payload = dict(payload)
            payload["text"] = clean + "\\n\\n" + signature
    return payload


'''


def blob(data: bytes) -> str:
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()


def download_module() -> bytes:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    req = urllib.request.Request(
        SOURCE, headers={"User-Agent": "NyanShopFooterInstaller/1.0"}
    )
    with opener.open(req, timeout=25) as response:
        data = response.read(40001)
    if len(data) > 40000 or blob(data) != MODULE_SHA:
        raise RuntimeError("Проверка целостности модуля не пройдена")
    ast.parse(data.decode("utf-8"), filename=str(MODULE))
    return data


def insert_into_bot(source: str) -> str:
    tree = ast.parse(source, filename=str(BOT))
    imports = source.count(
        "from nyan_shop_footer import install_nyan_shop_footer"
    )
    invocations = source.count("install_nyan_shop_footer()")
    if imports == 1 and invocations == 1:
        return source
    if imports or invocations or BOT_MARKER in source:
        raise RuntimeError("В bot.py уже присутствует неполная установка подписи")
    polling_calls = [
        x for x in ast.walk(tree)
        if isinstance(x, ast.Call)
        and isinstance(x.func, ast.Attribute)
        and x.func.attr == "run_polling"
    ]
    if len(polling_calls) != 1:
        raise RuntimeError("Не найден единственный запуск app.run_polling в bot.py")
    call = polling_calls[0]
    lines = source.splitlines(keepends=True)
    start = call.lineno - 1
    line = lines[start]
    indent = line[:len(line) - len(line.lstrip(" \t"))]
    if (not isinstance(call.func.value, ast.Name)
            or not line.lstrip().startswith(call.func.value.id + ".run_polling")):
        raise RuntimeError("Нестандартный запуск бота: автоматическое изменение остановлено")
    end = "\r\n" if line.endswith("\r\n") else "\n"
    lines[start:start] = [
        indent + "from nyan_shop_footer import install_nyan_shop_footer" + end,
        indent + "install_nyan_shop_footer()" + end,
    ]
    updated = "".join(lines)
    ast.parse(updated, filename="bot.py with footer")
    return updated


def insert_into_relay(source: str) -> str:
    ast.parse(source, filename=str(RELAY))
    if RELAY_MARKER in source and RELAY_CALL in source:
        return source
    if RELAY_MARKER in source or RELAY_CALL in source:
        raise RuntimeError("Relay содержит неполную установку подписи")
    if source.count(RELAY_ANCHOR) != 1 or source.count("def send_one(") != 1:
        raise RuntimeError("Нестандартная версия Telegram Relay: изменение остановлено")
    result = source.replace(
        RELAY_ANCHOR, RELAY_CALL, 1
    ).replace("def send_one(", RELAY_HELPER + "def send_one(", 1)
    ast.parse(result, filename="Telegram Relay with footer")
    return result


def atomic_write(path: Path, content: bytes) -> None:
    fd, tmp = tempfile.mkstemp(prefix=".nyan-footer-", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(tmp, (path.stat().st_mode & 0o777) if path.is_file() else 0o644)
        os.replace(tmp, path)
    finally:
        Path(tmp).unlink(missing_ok=True)


def bot_restart() -> None:
    sys.path.insert(0, str(HELPER.parent))
    from nyan_bot_autodeploy import BOT as HELPER_ROOT, find_bot_processes, restart_nohup
    if HELPER_ROOT.resolve() != ROOT.resolve():
        raise RuntimeError("Помощник бота относится к другому каталогу")
    if len(find_bot_processes()) != 1:
        raise RuntimeError("Работает не один экземпляр bot.py. Нельзя безопасно перезапустить")
    restart_nohup()


def processes():
    result = []
    for item in Path("/proc").iterdir():
        if not item.name.isdecimal():
            continue
        try:
            if item.stat().st_uid != os.getuid():
                continue
            argv = [
                os.fsdecode(x) for x in
                (item / "cmdline").read_bytes().split(bytes((0,))) if x
            ]
            if argv:
                result.append((int(item.name), argv))
        except (FileNotFoundError, PermissionError, OSError):
            pass
    return result


def relay_restart() -> str:
    """Only restart a proven single standalone worker, never a supervisor."""
    active = processes()
    workers = [
        (pid, argv) for pid, argv in active
        if Path(argv[0]).name.startswith("python")
        and str(RELAY) in argv[1:]
    ]
    if not workers:
        return "Relay не обнаружен в процессах: файл изменён, запуск проверь отдельно."
    if len(workers) != 1:
        return "Несколько активных Relay: файл обновлён, нужен ручной перезапуск."
    pid, argv = workers[0]
    if "--env-file" not in argv:
        return "Relay запущен без ожидаемого --env-file: нужен штатный перезапуск."
    lock = Path("/home/nyanteam/.nyan-wallet-relay.lock")
    wrappers = [
        (wpid, wargv) for wpid, wargv in active
        if Path(wargv[0]).name == "flock"
        and str(RELAY) in wargv
        and str(lock) in wargv
        and wargv.count("-n") == 1
    ]
    if len(wrappers) != 1:
        return "Схема запуска Relay неизвестна: файл обновлён, нужен штатный перезапуск."
    wp, wargs = wrappers[0]
    if len(wargs) < 6:
        return "Нестандартная команда Relay: нужен штатный перезапуск."
    # Require exactly the established 'flock -n LOCK PYTHON RELAY ...' layout.
    if (
        wargs[1:4] != ["-n", str(lock), argv[0]]
        or wargs[4] != str(RELAY)
        or wargs[4:] != argv[1:]
    ):
        return "Команда Relay отличается от штатной: нужен ручной перезапуск."
    # Confirm flock is the Python process's parent, not a coincidental wrapper.
    status = Path(f"/proc/{pid}/status").read_text()
    parent_line = next((x for x in status.splitlines() if x.startswith("PPid:")), "")
    if parent_line.split()[-1:] != [str(wp)]:
        return "Relay не является дочерним процессом flock: нужен штатный перезапуск."
    os.kill(pid, signal.SIGTERM)
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if not Path(f"/proc/{pid}").exists():
            break
        time.sleep(0.5)
    else:
        return "Relay долго завершает запросы. Новый процесс не запущен."
    # The wrapper will release the exclusive lock once its child exits.
    deadline = time.monotonic() + 10
    while Path(f"/proc/{wp}").exists() and time.monotonic() < deadline:
        time.sleep(0.25)
    log_path = Path("/home/nyanteam/.nyan-wallet-relay.log")
    with log_path.open("ab") as log:
        proc = subprocess.Popen(
            wargs, cwd="/home/nyanteam", stdin=subprocess.DEVNULL,
            stdout=log, stderr=subprocess.STDOUT, start_new_session=True,
            close_fds=True,
        )
    time.sleep(3)
    if proc.poll() is not None:
        return (
            f"Relay не перезапустился (exit {proc.returncode}). "
            f"Проверь {log_path} и {lock}"
        )
    return f"Relay перезапущен через flock, PID={proc.pid}"


def main():
    parser = argparse.ArgumentParser()
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--check", action="store_true")
    selection.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if not (BOT.is_file() and RELAY.is_file()
            and HELPER.is_file() and PYTHON.is_file()):
        raise RuntimeError(
            "Не найдены bot.py, Telegram Relay или штатный помощник перезапуска "
            "на nyanteam@mjodgiver"
        )
    if any(path.is_symlink() for path in (BOT, RELAY, MODULE)):
        raise RuntimeError("Символьные ссылки не поддерживаются")
    import_check = subprocess.run(
        [str(PYTHON), "-c",
         "from telegram import Bot; from telegram.ext import ExtBot; "
         "assert hasattr(Bot, '_post')"],
        capture_output=True, text=True, timeout=15,
    )
    if import_check.returncode:
        raise RuntimeError(
            "python-telegram-bot несовместим: " + import_check.stderr[-600:]
        )
    before_bot = BOT.read_bytes()
    before_relay = RELAY.read_bytes()
    before_module = MODULE.read_bytes() if MODULE.exists() else None
    candidate_module = download_module()
    candidate_bot = insert_into_bot(before_bot.decode("utf-8")).encode("utf-8")
    candidate_relay = insert_into_relay(before_relay.decode("utf-8")).encode("utf-8")
    changes = [
        (BOT, before_bot, candidate_bot),
        (MODULE, before_module, candidate_module),
        (RELAY, before_relay, candidate_relay),
    ]
    changes = [(path, old, new) for path, old, new in changes if old != new]
    if args.check:
        print("OK: сухая проверка прошла. Ничего не изменено.")
        print("Подпись:", FOOTER)
        print("Изменения:", ", ".join(p.name for p, _, _ in changes) or "не нужны")
        return
    if not changes:
        print("Подпись уже установлена в bot.py и Relay.")
        return
    if len(processes()) == 0:
        raise RuntimeError("Не удалось проверить работающие процессы")
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
    backup = BACKUP_BASE / stamp
    backup.mkdir(parents=True, mode=0o700, exist_ok=False)
    os.chmod(backup, 0o700)
    for path, old, _ in changes:
        if old is not None:
            out = backup / path.name
            out.write_bytes(old)
            os.chmod(out, 0o600)
    changed = []
    try:
        for path, old, new in changes:
            atomic_write(path, new)
            changed.append((path, old))
        compiled = subprocess.run(
            [str(PYTHON), "-m", "py_compile", str(BOT), str(MODULE), str(RELAY)],
            capture_output=True, text=True, timeout=20,
        )
        if compiled.returncode:
            raise RuntimeError(compiled.stderr[-1000:])
        if any(path == BOT or path == MODULE for path, _, _ in changes):
            bot_restart()
    except Exception as error:
        for path, old in reversed(changed):
            if old is None:
                path.unlink(missing_ok=True)
            else:
                atomic_write(path, old)
        try:
            if any(path == BOT or path == MODULE for path, _, _ in changes):
                bot_restart()
        except Exception as rollback:
            raise RuntimeError(
                f"Ошибка установки: {error}. Бэкап: {backup}. "
                f"Восстановление запуска бота требует проверки: {rollback}"
            ) from error
        raise RuntimeError(
            f"Ошибка установки: {error}. Старые файлы восстановлены. Бэкап: {backup}"
        ) from error
    print("OK: подпись установлена в основной бот и Telegram Relay.")
    if any(path == RELAY for path, _, _ in changes):
        print(relay_restart())
    print("Резервная копия:", backup)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        raise SystemExit("ОШИБКА: " + str(exc)) from exc
