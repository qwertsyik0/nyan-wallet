"""Deploy VIP changes into a locally customized Nyan Wallet VPS without git pull.

Preserves all unrelated tracked edits and untracked files. Applies only the VIP
changes by three-way merging them against the pre-VIP GitHub base. Fails closed
on conflicts. Backs up every file it touches and restores on failed validation.
"""
from __future__ import annotations

import argparse
import datetime as dt
import io
import os
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path("/opt/nyan-wallet")
VENV = ROOT / ".venv/bin/python"
SERVICE = "nyan-wallet.service"
# Base of PR #39. It is used ONLY as the common ancestor for VIP-only edits.
BASE = "409a30870c1fc6ab653c493073cf9a30b20dc691"
SOURCE = "origin/main"

MODIFIED = (
    "server/__init__.py",
    "server/extended_features.py",
    "server/advanced_features.py",
    "server/nyan_id.py",
    "advanced_features.js",
    "nyan_id.js",
    "nyan_id.css",
    "index.html",
)
ADDED = (
    "server/vip.py",
    "vip.js",
    "vip.css",
    "tools/test_vip_membership.py",
)
ALL = MODIFIED + ADDED


def run(*args: str, timeout: int = 60, check: bool = True) -> subprocess.CompletedProcess:
    result = subprocess.run(
        list(args), cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        timeout=timeout,
    )
    if check and result.returncode:
        detail = result.stderr.decode("utf-8", "replace").strip()
        raise RuntimeError(f"{args[0]} failed ({result.returncode}): {detail[-1800:]}")
    return result


def show(ref: str, path: str) -> bytes:
    return run("git", "show", f"{ref}:{path}").stdout


def merge_one(path: str, local: bytes) -> bytes:
    with tempfile.TemporaryDirectory(prefix="nyan-vip-merge-") as temp:
        folder = Path(temp)
        ours = folder / "ours"
        common = folder / "base"
        theirs = folder / "vip"
        ours.write_bytes(local)
        common.write_bytes(show(BASE, path))
        theirs.write_bytes(show(SOURCE, path))
        result = run(
            "git", "merge-file", "--diff3", "-p",
            str(ours), str(common), str(theirs),
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"{path}: VIP changes conflict with local modifications. "
                "No files have been changed."
            )
        if b"<<<<<<<" in result.stdout or b">>>>>>>" in result.stdout:
            raise RuntimeError(f"{path}: unexpected merge marker")
        return result.stdout


def atomic_write(path: Path, content: bytes, mode: int = 0o644) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".nyan-vip-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(name, mode)
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def check_source(content_by_path: dict[str, bytes]) -> None:
    # A complete Python syntax check without importing live service modules.
    for path, raw in content_by_path.items():
        if path.endswith(".py"):
            try:
                compile(raw.decode("utf-8"), path, "exec")
            except (SyntaxError, UnicodeDecodeError) as exc:
                raise RuntimeError(f"Invalid Python in {path}: {exc}") from exc

    if shutil.which("node"):
        with tempfile.TemporaryDirectory(prefix="nyan-vip-js-") as temp:
            for path, raw in content_by_path.items():
                if not path.endswith(".js"):
                    continue
                filename = Path(temp) / Path(path).name
                filename.write_bytes(raw)
                run("node", "--check", str(filename))

    markers = {
        "server/__init__.py": (b"register_vip(backend_app.app)",),
        "server/extended_features.py": (
            b"VipPurchaseToken", b"activate_vip(session, item.id",
            b"X-VIP-Purchase-Key",
        ),
        "server/advanced_features.py": (
            b"is_vip_subscription", b"vip_profile_status",
        ),
        "server/nyan_id.py": (b"status_for_user(session, user.telegram_id)",),
        "index.html": (b'vip.js?v=', b'vip.css?v='),
        "vip.js": (b"/api/vip/status", b"X-VIP-Purchase-Key"),
        "server/vip.py": (b"vip_subscriptions", b"vip_weekly_credits"),
    }
    for path, required in markers.items():
        if any(marker not in content_by_path[path] for marker in required):
            raise RuntimeError(f"{path}: required VIP hook is missing")


def backup_originals(old_files: dict[str, bytes | None]) -> Path:
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = Path("/root") / f"nyan-vip-predeploy-{stamp}.tar.gz"
    if target.exists():
        raise RuntimeError("Backup name already exists")
    with tarfile.open(target, "w:gz") as tar:
        for path, content in old_files.items():
            if content is None:
                continue
            origin = ROOT / path
            info = tar.gettarinfo(str(origin), arcname=path)
            tar.addfile(info, io.BytesIO(content))
    target.chmod(0o600)
    return target


def service_health() -> None:
    last = "API not ready"
    for attempt in range(20):
        active = run("systemctl", "is-active", SERVICE, check=False)
        if active.returncode == 0:
            try:
                with urllib.request.urlopen(
                    "http://127.0.0.1:8000/openapi.json", timeout=3
                ) as response:
                    import json
                    paths = json.load(response).get("paths", {})
                if "/api/vip/status" in paths and "/api/rewards/{reward_id}/request" in paths:
                    return
                last = "VIP routes not registered"
            except Exception as exc:
                last = f"{type(exc).__name__}: {exc}"
        else:
            last = "Service is not active"
        time.sleep(2)
    raise RuntimeError("VIP health check failed: " + last)


def main() -> None:
    if Path.cwd() != ROOT:
        raise RuntimeError("Run from /opt/nyan-wallet")
    if not (ROOT / ".git").exists():
        raise RuntimeError("Expected /opt/nyan-wallet Git checkout")
    if not VENV.exists():
        raise RuntimeError("Wallet virtualenv not found")

    current: dict[str, bytes | None] = {}
    desired: dict[str, bytes] = {}
    modes: dict[str, int] = {}
    for path in ALL:
        target = ROOT / path
        if target.is_symlink():
            raise RuntimeError(f"{path} is a symlink; refusing to overwrite")
        existing = target.read_bytes() if target.exists() else None
        current[path] = existing
        modes[path] = stat.S_IMODE(target.stat().st_mode) if existing is not None else 0o644
        if path in MODIFIED:
            if existing is None:
                raise RuntimeError(f"Required local file is missing: {path}")
            desired[path] = merge_one(path, existing)
        else:
            remote = show(SOURCE, path)
            if existing is not None and existing != remote:
                raise RuntimeError(f"{path} exists locally with different contents")
            desired[path] = remote

    check_source(desired)
    changed = [p for p in ALL if desired[p] != current[p]]
    if not changed:
        print("VIP already installed locally. No files changed.")
        return

    print("\nVIP-only changes preflight OK. Files:", ", ".join(changed))
    backup = backup_originals(current)
    print("Original files saved:", backup)
    written = []
    try:
        for path in changed:
            if current[path] is not None and (ROOT / path).read_bytes() != current[path]:
                raise RuntimeError(f"{path} changed during preflight; cancelled")
            if current[path] is None and (ROOT / path).exists():
                raise RuntimeError(f"{path} appeared during preflight; cancelled")
        for path in changed:
            atomic_write(ROOT / path, desired[path], modes[path])
            written.append(path)
        checks = run(str(VENV), "tools/test_vip_membership.py", timeout=65)
        print(checks.stdout.decode("utf-8", "replace").strip())
        run("systemctl", "restart", SERVICE, timeout=65)
        service_health()
    except BaseException:
        print("VIP validation failed; restoring the original files...", file=sys.stderr)
        for path in reversed(written):
            old = current[path]
            if old is None:
                (ROOT / path).unlink(missing_ok=True)
            else:
                atomic_write(ROOT / path, old, modes[path])
        try:
            run("systemctl", "restart", SERVICE, timeout=65)
            print("Previous Wallet service files restored.", file=sys.stderr)
        except Exception as exc:
            print("IMPORTANT: restart previous Wallet manually:", exc, file=sys.stderr)
        raise

    print("\n=== VIP INSTALLED SUCCESSFULLY ===")
    print("Service: active; VIP API routes: available")
    print("Affected paths:", len(changed))
    print("Backup:", backup)
    print("Unrelated tracked and untracked local files were not changed.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("VIP installation stopped:", exc, file=sys.stderr)
        sys.exit(1)
