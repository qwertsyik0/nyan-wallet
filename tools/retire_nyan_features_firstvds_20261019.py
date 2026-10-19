#!/usr/bin/env python3
"""Safely disable finished Nyan Elections, survey and finance recruitment APIs on FirstVDS.

Run as root: python3 tools/retire_nyan_features_firstvds_20261019.py --apply
Does not change database rows or wallet balances. Saves an initializer backup
and rolls back the server file if service/API verification fails.
"""
from __future__ import annotations

import argparse
import ast
import datetime
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import time

SERVICE = "nyan-wallet"
API = "https://nyan-wallet-153-76-175-145.sslip.io"
ENDPOINTS = (
    "/api/elections",
    "/api/elections/voting/status",
    "/api/wallet-survey/status",
    "/api/owner/wallet-survey/results",
    "/api/recruitment/finance/me",
    "/api/recruitment/finance/stage2/me",
)
DISABLE_LINES = (
    "    register_wallet_survey(backend_app.app)\n",
    "    register_finance_recruitment(backend_app.app)\n",
    "    register_finance_stage2(backend_app.app)\n",
    "    register_elections(backend_app.app)\n",
    "    register_elections_voting(backend_app.app)\n",
    "    send_survey_channel_followups_20261011()\n",
)


def command(*args, timeout=45, check=True):
    process = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             universal_newlines=True, timeout=timeout)
    if check and process.returncode:
        raise RuntimeError("{} failed (exit {}): {}".format(
            args[0], process.returncode, process.stderr[-500:]))
    return process.stdout.strip()


def service_root():
    directory = command("systemctl", "show", SERVICE, "-p", "WorkingDirectory", "--value")
    candidates = [directory, "/root/nyan-wallet", "/opt/nyan-wallet",
                  "/srv/nyan-wallet", "/home/nyanteam/nyan-wallet"]
    for candidate in candidates:
        if not candidate or candidate == "/":
            continue
        root = Path(candidate).resolve()
        if (root / "server/__init__.py").is_file() and (
                root / "server/backend_app.py").is_file():
            return root
    raise RuntimeError("Cannot find backend. Check: systemctl show nyan-wallet -p WorkingDirectory")


def status(endpoint):
    value = command("curl", "--connect-timeout", "4", "--max-time", "9",
                    "-sS", "-o", "/dev/null", "-w", "%{http_code}",
                    API + endpoint, timeout=12)
    return value


def verify_remote():
    for _ in range(12):
        try:
            if command("systemctl", "is-active", SERVICE, check=False) == "active" \
                    and status("/api/health") == "200":
                break
        except (RuntimeError, subprocess.TimeoutExpired):
            pass
        time.sleep(2)
    else:
        raise RuntimeError("Production API did not return HTTP 200 after restart")
    for endpoint in ENDPOINTS:
        actual = status(endpoint)
        if actual != "404":
            raise RuntimeError("{} returned HTTP {}, expected 404".format(endpoint, actual))
    print("OK: API healthy and all six retired endpoint checks returned 404.")


def write_atomic(path, content, mode):
    descriptor, tmp = tempfile.mkstemp(prefix=".nyan-retire-", dir=str(path.parent))
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as file:
            file.write(content)
            file.flush()
            os.fsync(file.fileno())
        os.chmod(tmp, mode)
        os.replace(tmp, str(path))
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true",
                        help="Patch production initializer and restart service (default dry-run)")
    args = parser.parse_args()
    if os.geteuid() != 0:
        raise RuntimeError("Run as root on FirstVDS, not on the Telegram bot host")
    if command("systemctl", "is-active", SERVICE, check=False) != "active":
        raise RuntimeError("nyan-wallet service not active, refusing changes")
    root = service_root()
    init = root / "server/__init__.py"
    original = init.read_text(encoding="utf-8")
    if "register_finance_workspace(backend_app.app)" not in original:
        raise RuntimeError("Finance workspace route missing; refusing to change unknown backend")

    patched = original
    changed = []
    for entry in DISABLE_LINES:
        count = patched.count(entry)
        if count > 1:
            raise RuntimeError("Ambiguous repeated API registration: " + entry.strip())
        if count == 1:
            patched = patched.replace(entry, "")
            changed.append(entry.strip())
    ast.parse(patched, filename=str(init))
    print("Backend location:", root)
    print("Registrations to disable:", changed or "(already disabled)")
    if not args.apply:
        print("DRY RUN. No service or database was changed; rerun with --apply.")
        return

    if not changed:
        verify_remote()
        return

    backup_dir = Path("/root/nyan_wallet_backups")
    backup_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(str(backup_dir), 0o700)
    timestamp = datetime.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    backup = backup_dir / ("initializer_before_retirement_{}_{}.py".format(
        timestamp, os.getpid()))
    shutil.copy2(str(init), str(backup))
    mode = stat.S_IMODE(init.stat().st_mode)
    print("Production initializer backup:", backup)

    try:
        write_atomic(init, patched, mode)
        command("systemctl", "restart", SERVICE, timeout=60)
        verify_remote()
    except BaseException:
        print("ERROR: restoring previous initializer and restarting service", file=sys.stderr)
        write_atomic(init, original, mode)
        try:
            command("systemctl", "restart", SERVICE, timeout=60)
        except BaseException as restore_error:
            print("CRITICAL: failed to restart previous backend:", restore_error, file=sys.stderr)
        raise
    print("DONE. Next run the guarded full-database-backup/purge script.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("ERROR:", exc, file=sys.stderr)
        sys.exit(1)
