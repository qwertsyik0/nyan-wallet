#!/usr/bin/env python3
"""Targeted production fix for VIP purchase 'Failed to fetch'.

No git pull, no git reset, no database writes or purchase requests.
Preserves all other locally customized Nyan Wallet code.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path("/opt/nyan-wallet")
SERVICE = "nyan-wallet.service"
FILES = ("server/extended_features.py", "server/backend_app.py")


def checked_replace(source: str, old: str, new: str, path: str) -> str:
    count = source.count(old)
    if count != 1:
        raise RuntimeError(
            f"{path}: expected one matching source fragment, found {count}; "
            "nothing has been changed"
        )
    return source.replace(old, new, 1)


def patched_extended(source: str) -> str:
    path = "server/extended_features.py"
    if "activate_vip(session, item.id" not in source:
        raise RuntimeError(
            "VIP server is not installed; stopping without changing files"
        )
    old_signature = (
        '    x_vip_purchase_key: str | None = Header(default=None, alias="X-VIP-Purchase-Key"),\n'
        '):'
    )
    new_signature = (
        '    x_vip_purchase_key: str | None = Header(default=None, alias="X-VIP-Purchase-Key"),\n'
        '    vip_purchase_key: str | None = None,\n'
        '):'
    )
    if "    vip_purchase_key: str | None = None," not in source:
        source = checked_replace(source, old_signature, new_signature, path)

    old_assignment = 'vip_key = (x_vip_purchase_key or "").strip() if is_vip else ""'
    new_assignment = (
        'vip_key = (vip_purchase_key or x_vip_purchase_key or "").strip() '
        'if is_vip else ""'
    )
    if new_assignment not in source:
        source = checked_replace(source, old_assignment, new_assignment, path)

    if source.count("    vip_purchase_key: str | None = None,") != 1:
        raise RuntimeError(f"{path}: duplicated VIP query parameter")
    if source.count(new_assignment) != 1:
        raise RuntimeError(f"{path}: VIP purchase key not updated")
    return source


def patched_cors(source: str) -> str:
    path = "server/backend_app.py"
    old = '    allow_headers=["Content-Type", "X-Telegram-Init-Data"],'
    new = '    allow_headers=["Content-Type", "X-Telegram-Init-Data", "X-VIP-Purchase-Key"],'
    if new in source:
        return source
    return checked_replace(source, old, new, path)


def write_atomic(path: Path, content: bytes, mode: int) -> None:
    fd, name = tempfile.mkstemp(prefix=".nyan-vip-fetch-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(name, mode)
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def call(*args: str) -> None:
    subprocess.run(args, cwd=ROOT, check=True, timeout=60)


def health() -> None:
    last = "unavailable"
    for _ in range(18):
        if subprocess.run(
            ["systemctl", "is-active", "--quiet", SERVICE],
            check=False, timeout=8
        ).returncode == 0:
            try:
                with urllib.request.urlopen(
                    "http://127.0.0.1:8000/openapi.json", timeout=3
                ) as response:
                    schema = json.load(response)
                routes = schema.get("paths", {})
                params = routes.get("/api/rewards/{reward_id}/request", {}).get("post", {}).get("parameters", [])
                if "/api/vip/status" not in routes:
                    raise RuntimeError("VIP status endpoint missing")
                if not any(
                    p.get("name") == "vip_purchase_key" and p.get("in") == "query"
                    for p in params
                ):
                    raise RuntimeError("VIP query parameter not registered")
                request = urllib.request.Request(
                    "http://127.0.0.1:8000/api/rewards/21/request",
                    method="OPTIONS",
                    headers={
                        "Origin": "https://qwertsyik0.github.io",
                        "Access-Control-Request-Method": "POST",
                        "Access-Control-Request-Headers":
                            "x-vip-purchase-key,x-telegram-init-data",
                    },
                )
                with urllib.request.urlopen(request, timeout=3) as response:
                    allowed = response.headers.get(
                        "access-control-allow-headers", ""
                    ).lower()
                    if "x-vip-purchase-key" not in allowed:
                        raise RuntimeError("Legacy VIP CORS header is still blocked")
                return
            except (OSError, ValueError, RuntimeError, urllib.error.HTTPError) as exc:
                last = str(exc)
        time.sleep(2)
    raise RuntimeError("Wallet API check failed: " + last)


def main() -> None:
    if os.geteuid() != 0:
        raise RuntimeError("Run as root")
    if not ROOT.is_dir():
        raise RuntimeError("Wallet checkout is missing")
    if not (ROOT / "server/vip.py").is_file():
        raise RuntimeError("VIP module is not installed yet")

    originals = {}
    changes = {}
    modes = {}
    for rel in FILES:
        path = ROOT / rel
        if not path.is_file() or path.is_symlink():
            raise RuntimeError(f"{rel}: unexpected path; no changes made")
        content = path.read_bytes()
        source = content.decode("utf-8")
        updated = patched_extended(source) if rel.endswith("extended_features.py") else patched_cors(source)
        compile(updated, rel, "exec")
        originals[rel] = content
        changes[rel] = updated.encode("utf-8")
        modes[rel] = stat.S_IMODE(path.stat().st_mode)

    to_change = [rel for rel in FILES if originals[rel] != changes[rel]]
    if not to_change:
        print("VIP fetch patch already installed. Checking API...")
        health()
        print("VIP FETCH FIX VERIFIED")
        return

    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    backup = Path("/root") / ("nyan-vip-fetch-backup-" + stamp)
    backup.mkdir(mode=0o700, exist_ok=False)
    for rel in to_change:
        destination = backup / rel
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(originals[rel])
        destination.chmod(0o600)
    print("Saved original files in", backup, flush=True)

    written = []
    try:
        for rel in to_change:
            path = ROOT / rel
            if path.read_bytes() != originals[rel]:
                raise RuntimeError(f"{rel} changed during preflight")
            write_atomic(path, changes[rel], modes[rel])
            written.append(rel)
        call("systemctl", "restart", SERVICE)
        health()
    except BaseException:
        print("Health check failed. Restoring previous source files...", file=sys.stderr)
        for rel in reversed(written):
            write_atomic(ROOT / rel, originals[rel], modes[rel])
        try:
            call("systemctl", "restart", SERVICE)
        except Exception as exc:
            print("Restore restart failed:", exc, file=sys.stderr)
        raise

    print("VIP FETCH FIX APPLIED")
    print("VIP query purchase parameter: enabled")
    print("Legacy VIP request header: allowed")
    print("API: active")
    print("Backup:", backup)
    print("No wallet balances or unrelated project files were edited.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("VIP FETCH FIX FAILED:", exc, file=sys.stderr)
        sys.exit(1)
