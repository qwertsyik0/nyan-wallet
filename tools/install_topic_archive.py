#!/usr/bin/env python3
"""Add a standalone bot module; no Wallet files, environment values or token output."""
import argparse
import ast
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

def patch(source):
    if "register_topic_archive(app)" in source:
        return source
    tree = ast.parse(source)
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Expr) and
             isinstance(n.value, ast.Call) and isinstance(n.value.func, ast.Attribute) and
             n.value.func.attr == "run_polling"]
    if len(calls) != 1 or not isinstance(calls[0].value.func.value, ast.Name) or calls[0].value.func.value.id != "app":
        raise RuntimeError("Expected exactly one app.run_polling call; bot.py was not changed")
    lines = source.splitlines(keepends=True)
    node = calls[0]
    indent = " " * node.col_offset
    lines.insert(node.lineno-1, indent + "from topic_archive import register_topic_archive\n" +
                 indent + "register_topic_archive(app)\n")
    result = "".join(lines)
    compile(result, "bot.py", "exec")
    return result

def processes(root):
    found = []
    for p in Path("/proc").iterdir():
        if not p.name.isdigit():
            continue
        try:
            if (p/"cwd").resolve() != root:
                continue
            args = [x.decode() for x in (p/"cmdline").read_bytes().split(b"\0") if x]
            if not any(Path(x).name == "bot.py" for x in args):
                continue
            env = dict(x.decode().split("=",1) for x in (p/"environ").read_bytes().split(b"\0") if b"=" in x)
            found.append((int(p.name), args, env))
        except (OSError,UnicodeError):
            continue
    return found

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ref", required=True)
    args = parser.parse_args()
    if len(args.ref)!=40 or any(c not in "0123456789abcdef" for c in args.ref):
        raise RuntimeError("A full commit SHA is required")
    root = Path.cwd().resolve()
    path = root/"bot.py"
    if not path.is_file() or path.is_symlink():
        raise RuntimeError("Run in the bot directory")
    current = processes(root)
    if len(current)!=1:
        raise RuntimeError("Expected one running bot.py process; nothing changed")
    pid, command, env = current[0]
    source = path.read_text(encoding="utf-8")
    patched = patch(source)
    module_path = root/"topic_archive.py"
    with urllib.request.urlopen(
        "https://raw.githubusercontent.com/qwertsyik0/nyan-wallet/" + args.ref +
        "/bot_extensions/topic_archive.py", timeout=30
    ) as response:
        module = response.read()
    compile(module,"topic_archive.py","exec")
    # Use the running interpreter, not an unrelated system Python.
    executable = command[0]
    if not os.path.isabs(executable):
        executable = str(root / executable) if "/" in executable else shutil.which(
            executable, path=env.get("PATH", os.defpath))
    if not executable:
        raise RuntimeError("Bot interpreter not found")
    probe = subprocess.run([executable,"-c",
        "import sqlite3; from telegram.ext import Application, ApplicationHandlerStop; "
        "from telegram.ext import MessageHandler, CommandHandler, filters"],
        cwd=root,env=env,capture_output=True)
    if probe.returncode:
        raise RuntimeError("Running bot interpreter is incompatible; nothing changed")
    stamp=datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    backup=root/(".topic-archive-backup-"+stamp)
    backup.mkdir(mode=0o700)
    shutil.copy2(path,backup/"bot.py")
    old_module=module_path.read_bytes() if module_path.exists() else None
    if old_module is not None:
        (backup/"topic_archive.py").write_bytes(old_module)
    # Refuse supervisor-controlled processes: manual nohup bot only.
    try:
        cgroup=(Path("/proc")/str(pid)/"cgroup").read_text()
        if ".service" in cgroup and not any(x in cgroup for x in ("user@", "session-")):
            raise RuntimeError("Service-managed bot detected: install requires its restart command")
    except OSError:
        raise RuntimeError("Bot process disappeared")
    os.kill(pid,15)
    deadline=time.monotonic()+30
    while processes(root) and time.monotonic()<deadline:
        time.sleep(.5)
    if processes(root):
        raise RuntimeError("Bot did not stop or was auto-restarted. Files unchanged.")
    def launch():
        with (root/"topic-archive-start.log").open("ab") as log:
            return subprocess.Popen(command,cwd=root,env=env,stdin=subprocess.DEVNULL,
                stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
    try:
        module_path.write_bytes(module)
        path.write_text(patched,encoding="utf-8")
        child=launch()
        time.sleep(8)
        if child.poll() is not None:
            raise RuntimeError("Bot exited after restart")
    except BaseException:
        if "child" in locals() and child.poll() is None:
            child.terminate()
            child.wait(timeout=20)
        shutil.copy2(backup/"bot.py",path)
        if old_module is None:
            module_path.unlink(missing_ok=True)
        else:
            module_path.write_bytes(old_module)
        launch()
        raise RuntimeError("Installation failed; previous files restored and bot relaunched. See topic-archive-start.log locally.")
    print("Installed. Bot process running; verify with /export 10 in a topic.")
    print("Backup:",backup)
    print("Database:",root/".nyan_archive/messages.sqlite3")
    print("New messages only; bot must have access to ordinary group messages.")

if __name__=="__main__":
    try:
        main()
    except Exception as error:
        raise SystemExit(str(error))
