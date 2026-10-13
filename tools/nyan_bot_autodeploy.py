#!/usr/bin/env python3
"""Nyan Wallet Telegram bot auto-deploy (the API is deployed by Render).

Run once on the VPS: python3 tools/nyan_bot_autodeploy.py install
Every minute cron fetches main, checks Python syntax, copies installed bot
add-ons, restarts the actual systemd unit, and rolls back on failure.
"""
from __future__ import annotations

import argparse
import base64
import fcntl
import gzip
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
BOT = Path(os.environ.get("NYAN_BOT_ROOT", "/home/nyanteam/new_bot"))
STATE = Path.home() / ".local" / "state" / "nyan-bot-autodeploy"
CONFIG = STATE / "config.json"
MARKER = "# NYAN_BOT_AUTO_DEPLOY"
MODULES = ("ban_bot.py", "broadcast_bot.py", "channel_publish_bot.py",
           "channel_publish_bot_v2.py", "maintenance_bot.py")


def command(*args: str, cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess:
    result = subprocess.run(args, cwd=cwd, text=True, capture_output=True, timeout=120)
    if check and result.returncode:
        raise RuntimeError(f"{' '.join(args)}: {result.stderr.strip() or result.stdout.strip()}")
    return result


def git(*args: str) -> str:
    return command("git", "-C", str(REPO), *args).stdout.strip()


def date() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def service_command(config: dict, action: str, check: bool = True) -> subprocess.CompletedProcess:
    scope = config["scope"]
    unit = config["service"]
    if scope == "user":
        args = ["systemctl", "--user", action, unit]
        # User systemd services also work when started by cron, if lingering is enabled.
        os.environ.setdefault("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
        os.environ.setdefault("DBUS_SESSION_BUS_ADDRESS",
                              f"unix:path=/run/user/{os.getuid()}/bus")
    elif scope == "system":
        args = ["systemctl", action, unit]
        if os.geteuid() != 0:
            args.insert(0, "sudo")
            args.insert(1, "-n")
    else:
        raise RuntimeError("Unknown systemd scope")
    return command(*args, check=check)


def discover_service(bot_dir: Path) -> tuple[str, str] | None:
    found: set[tuple[str, str]] = set()
    for proc in Path("/proc").iterdir():
        if not proc.name.isdigit():
            continue
        try:
            cmdline = (proc / "cmdline").read_bytes().replace(b"\0", b" ").decode("utf-8", "replace")
            if not re.search(r"(^|\s)([^\s]*/)?bot\.py(\s|$)", cmdline):
                continue
            cwd = (proc / "cwd").resolve()
            if cwd != bot_dir.resolve() and str(bot_dir.resolve()) not in cmdline:
                continue
            cgroup = (proc / "cgroup").read_text()
        except (OSError, PermissionError):
            continue
        for line in cgroup.splitlines():
            path = line.rsplit(":", 1)[-1]
            services = re.findall(r"/([^/]+\.service)(?:/|$)", path)
            services = [s for s in services if not s.startswith("user@")]
            if services:
                scope = "user" if "/user.slice/" in path else "system"
                found.add((services[-1], scope))
    if len(found) > 1:
        raise RuntimeError(f"Multiple bot units found: {sorted(found)}")
    return next(iter(found), None)


def install(args: argparse.Namespace) -> None:
    if not (REPO / ".git").exists():
        raise RuntimeError(f"Not a git checkout: {REPO}")
    if not (BOT / "bot.py").is_file():
        raise RuntimeError(f"Bot entry point not found: {BOT / 'bot.py'}")
    detected = discover_service(BOT)
    service = args.service or (detected[0] if detected else None)
    scope = args.scope or (detected[1] if detected else None)
    if not service or not scope:
        raise RuntimeError(
            "Cannot identify the running bot's systemd unit. No cron job installed.\n"
            "Check: systemctl --user list-units --type=service --all ; "
            "systemctl list-units --type=service --all\n"
            "Then run: python3 tools/nyan_bot_autodeploy.py install "
            "--service YOUR_BOT.service --scope user|system"
        )
    if not re.fullmatch(r"[a-zA-Z0-9_.@-]+\.service", service):
        raise RuntimeError("Invalid systemd unit name")
    cfg = {"service": service, "scope": scope, "bot_root": str(BOT)}
    check = service_command(cfg, "is-active", check=False)
    if check.returncode:
        raise RuntimeError(f"Bot service {scope}:{service} is not active; refusing to configure auto-restart.")
    if scope == "system" and os.geteuid() != 0:
        sudo = command("sudo", "-n", "-l", check=False)
        if sudo.returncode:
            raise RuntimeError("System unit needs non-interactive sudo permission for systemctl restart.")
    STATE.mkdir(parents=True, exist_ok=True)
    CONFIG.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    CONFIG.chmod(0o600)
    current = command("crontab", "-l", check=False)
    old = current.stdout if current.returncode == 0 else ""
    lines = [line for line in old.splitlines() if MARKER not in line]
    python = shutil.which("python3") or sys.executable
    log = STATE / "deploy.log"
    cron = f"* * * * * {python} {REPO / 'tools/nyan_bot_autodeploy.py'} run >> {log} 2>&1 {MARKER}"
    update = "\n".join(lines + [cron]) + "\n"
    subprocess.run(["crontab", "-"], input=update, text=True, check=True)
    print(f"Configured {service} ({scope}). Checking GitHub every minute.")
    print(f"Logs: tail -n 60 {log}")
    print("Performing initial synchronisation.")
    deploy(force=True)


def syntax_check(folder: Path) -> None:
    for directory in ("server", "bot_addons", "tools"):
        source = folder / directory
        if source.is_dir():
            for path in source.rglob("*.py"):
                compile(path.read_bytes(), str(path), "exec")
    payload = folder / "bot_addons" / "giveaway_bot.py.gz.b64"
    if payload.exists():
        raw = gzip.decompress(base64.b64decode(payload.read_bytes(), validate=True))
        compile(raw, "giveaway_bot.py", "exec")


def giveaway_source(folder: Path) -> bytes:
    import importlib.util
    installer = folder / "tools" / "install_giveaway_bot.py"
    spec = importlib.util.spec_from_file_location("_nyan_giveaway_installer", installer)
    if not spec or not spec.loader:
        raise RuntimeError("Cannot load giveaway installer")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    payload = folder / "bot_addons" / "giveaway_bot.py.gz.b64"
    raw = gzip.decompress(base64.b64decode(payload.read_bytes(), validate=True))
    result = mod.adapt_giveaway_source(raw)
    compile(result, "giveaway_bot.py", "exec")
    return result


def bot_python() -> str:
    for path in (BOT / ".venv/bin/python", BOT / "venv/bin/python"):
        if path.exists():
            return str(path)
    return sys.executable


def sync_from(stage: Path, previous: str | None) -> dict[Path, bytes]:
    """Only replace already-installed modules; never edit bot.py or .env."""
    changes: dict[Path, bytes] = {}
    for name in MODULES:
        src = stage / "bot_addons" / name
        dst = BOT / name
        if src.is_file() and dst.is_file():
            new = src.read_bytes()
            if dst.read_bytes() != new:
                changes[dst] = new
    payload = stage / "bot_addons" / "giveaway_bot.py.gz.b64"
    dst = BOT / "giveaway_bot.py"
    # The archive is an installer base, not the live version. Only re-apply
    # when it was changed in Git after the last successfully deployed commit.
    if previous and dst.is_file() and payload.is_file():
        changed = command("git", "-C", str(REPO), "diff", "--name-only",
                          previous, "origin/main", "--", "bot_addons/giveaway_bot.py.gz.b64",
                          check=False)
        if changed.returncode != 0:
            raise RuntimeError("Cannot compare giveaway payload revisions")
        if changed.stdout.strip():
            new = giveaway_source(stage)
            if dst.read_bytes() != new:
                changes[dst] = new
    for dst, new in changes.items():
        compile(new, str(dst), "exec")
    # Ensure bot.py itself remains syntactically valid.
    compile((BOT / "bot.py").read_bytes(), str(BOT / "bot.py"), "exec")
    return changes


def check_bot_imports(changes: dict[Path, bytes]) -> None:
    # Preflight using the same Python interpreter as the bot, without
    # importing bot.py (which could start a second polling process).
    if not changes:
        return
    with tempfile.TemporaryDirectory(prefix="nyan-bot-smoke-") as temp:
        check_root = Path(temp)
        for path, data in changes.items():
            (check_root / path.name).write_bytes(data)
        command(bot_python(), "-m", "py_compile", *[str(check_root / path.name) for path in changes])


def deploy(force: bool = False) -> None:
    STATE.mkdir(parents=True, exist_ok=True)
    if not CONFIG.is_file():
        raise RuntimeError("Auto-deploy not installed. Run: python3 tools/nyan_bot_autodeploy.py install")
    cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
    BOT_ROOT = Path(cfg["bot_root"])
    if BOT_ROOT != BOT:
        raise RuntimeError("NYAN_BOT_ROOT and installed bot path differ")
    with (STATE / "lock").open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        git("fetch", "--quiet", "origin", "main")
        old = git("rev-parse", "HEAD")
        target = git("rev-parse", "origin/main")
        successful = (STATE / "deployed.sha").read_text().strip() if (STATE / "deployed.sha").exists() else None
        failed = (STATE / "failed.sha").read_text().strip() if (STATE / "failed.sha").exists() else None
        if not force and successful == target:
            return
        if not force and failed == target:
            return
        if git("rev-parse", "--abbrev-ref", "HEAD") != "main":
            raise RuntimeError("Checkout must be on the main branch")
        if git("status", "--porcelain", "--untracked-files=no"):
            raise RuntimeError("Tracked local edits found; refusing to overwrite them")
        if command("git", "-C", str(REPO), "merge-base", "--is-ancestor", old, target, check=False).returncode:
            raise RuntimeError("main diverged; refusing non-fast-forward update")
        print(f"[{date()}] deploy {old[:10]} -> {target[:10]}", flush=True)
        backup: dict[Path, bytes] = {}
        touched = False
        checkout_updated = False
        try:
            with tempfile.TemporaryDirectory(prefix="nyan-release-") as directory:
                stage = Path(directory)
                git("worktree", "add", "--detach", "--quiet", str(stage), target)
                try:
                    syntax_check(stage)
                    # Compare current deployed version rather than current local checkout:
                    # this also supports first-time installation.
                    changes = sync_from(stage, successful)
                    check_bot_imports(changes)
                    for dst, data in changes.items():
                        backup[dst] = dst.read_bytes()
                    # Keep production git fast-forward only. Never touch .env or DB.
                    git("merge", "--ff-only", target)
                    checkout_updated = old != target
                    if changes:
                        snapshot = STATE / "backups" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
                        snapshot.mkdir(parents=True, exist_ok=True)
                        for dst, old_data in backup.items():
                            (snapshot / dst.name).write_bytes(old_data)
                        print(f"[{date()}] saved pre-deploy backup: {snapshot}", flush=True)
                    for dst, data in changes.items():
                        mode = dst.stat().st_mode & 0o777
                        tmp = dst.with_suffix(dst.suffix + ".deploy-tmp")
                        try:
                            tmp.write_bytes(data)
                            tmp.chmod(mode)
                            os.replace(tmp, dst)
                        finally:
                            tmp.unlink(missing_ok=True)
                        touched = True
                    if touched:
                        service_command(cfg, "restart")
                        time.sleep(5)
                        active = service_command(cfg, "is-active", check=False)
                        if active.returncode:
                            raise RuntimeError(f"Bot did not stay active after restart: {active.stderr.strip()}")
                    (STATE / "deployed.sha").write_text(target + "\n", encoding="utf-8")
                    (STATE / "failed.sha").unlink(missing_ok=True)
                    print(f"[{date()}] success: {target[:10]}; modules: {', '.join(p.name for p in changes) or 'no changes'}", flush=True)
                finally:
                    command("git", "-C", str(REPO), "worktree", "remove",
                            "--force", str(stage), check=False)
        except Exception as error:
            for path, content in backup.items():
                path.write_bytes(content)
            if checkout_updated:
                git("reset", "--hard", old)
            if touched:
                retry = service_command(cfg, "restart", check=False)
                if retry.returncode:
                    print(f"[{date()}] rollback restart FAILED: {retry.stderr.strip()}", flush=True)
            (STATE / "failed.sha").write_text(target + "\n", encoding="utf-8")
            print(f"[{date()}] FAILED, rolled back: {error}", flush=True)
            raise


def main() -> None:
    parser = argparse.ArgumentParser(description="Nyan Wallet VPS Telegram bot auto-deploy")
    sub = parser.add_subparsers(dest="action", required=True)
    setup = sub.add_parser("install")
    setup.add_argument("--service", help="Existing bot systemd unit, e.g. nyancash.service")
    setup.add_argument("--scope", choices=("user", "system"))
    sub.add_parser("run")
    sub.add_parser("retry")
    sub.add_parser("status")
    args = parser.parse_args()
    if args.action == "install":
        install(args)
    elif args.action == "status":
        print(CONFIG.read_text() if CONFIG.exists() else "Not installed")
        print("Applied:", (STATE / "deployed.sha").read_text().strip() if (STATE / "deployed.sha").exists() else "-")
        print("Blocked:", (STATE / "failed.sha").read_text().strip() if (STATE / "failed.sha").exists() else "-")
    else:
        deploy(force=(args.action == "retry"))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"[{date()}] ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
