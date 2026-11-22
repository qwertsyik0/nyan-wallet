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


def _occurrences(lines: list[str], pattern: list[str]) -> list[int]:
    """Return exact positions, with no fuzzy overwrites."""
    if not pattern:
        return []
    return [
        index for index in range(len(lines) - len(pattern) + 1)
        if lines[index:index + len(pattern)] == pattern
    ]


def _context_score(lines: list[str], position: int, old_end: int,
                   base: list[str], start: int, end: int) -> int:
    left = 0
    while (left < 8 and start - left - 1 >= 0 and position - left - 1 >= 0
           and lines[position - left - 1] == base[start - left - 1]):
        left += 1
    right = 0
    while (right < 8 and end + right < len(base) and old_end + right < len(lines)
           and lines[old_end + right] == base[end + right]):
        right += 1
    return left + right


def _add_vip_delta(path: str, local: bytes, base_raw: bytes,
                   remote_raw: bytes) -> bytes:
    """Apply ONLY uniquely anchored VIP edits when ordinary merge conflicts.

    Each removal must match the original base text exactly. Existing local
    additions and modifications are never removed as a conflict resolution.
    Any ambiguous/missing anchor aborts the entire preflight.
    """
    import difflib
    try:
        base = base_raw.decode("utf-8").splitlines(keepends=True)
        newer = remote_raw.decode("utf-8").splitlines(keepends=True)
        output = local.decode("utf-8").splitlines(keepends=True)
    except UnicodeDecodeError as exc:
        raise RuntimeError(f"{path}: not UTF-8; manual integration required") from exc

    changes = [
        (a0, a1, newer[b0:b1])
        for tag, a0, a1, b0, b1 in
        difflib.SequenceMatcher(None, base, newer, autojunk=False).get_opcodes()
        if tag != "equal"
    ]
    for start, end, replacement in reversed(changes):
        old = base[start:end]
        if old:
            candidates = _occurrences(output, old)
            scored = [
                (_context_score(output, pos, pos + len(old), base, start, end), pos)
                for pos in candidates
            ]
            if not scored:
                # A locally changed line overlaps this VIP edit: abort.
                raise RuntimeError(
                    f"{path}: local edits overlap a VIP replacement "
                    f"near source line {start + 1}; no files changed."
                )
            scored.sort(reverse=True)
            if (len(scored) > 1 and scored[0][0] == scored[1][0]) or (
                    scored[0][0] == 0 and len(old) < 3):
                raise RuntimeError(f"{path}: ambiguous patch context near line {start + 1}")
            pos = scored[0][1]
            output[pos:pos + len(old)] = replacement
            continue

        # VIP added new lines without deleting anything. Preserve all
        # locally inserted lines and select a unique insertion boundary.
        if _occurrences(output, replacement):
            continue
        options: list[tuple[int, int]] = []
        for pos in range(len(output) + 1):
            score = _context_score(output, pos, pos, base, start, end)
            if score >= 2:
                options.append((score, pos))
        options.sort(reverse=True)
        if not options or (len(options) > 1 and options[0][0] == options[1][0]):
            # Adjacent local insertions can interrupt the two-sided anchor.
            # Prefer a uniquely matching preceding source line in that case.
            left = base[max(0, start - 2):start]
            positions = _occurrences(output, left) if len(left) == 2 else []
            if len(positions) != 1:
                raise RuntimeError(
                    f"{path}: cannot locate VIP insertion near line {start + 1}; "
                    "no files changed."
                )
            insertion_at = positions[0] + len(left)
        else:
            insertion_at = options[0][1]
        output[insertion_at:insertion_at] = replacement

    merged = "".join(output).encode("utf-8")
    if b"<<<<<<<" in merged or b">>>>>>>" in merged:
        raise RuntimeError(f"{path}: conflict marker in result")
    return merged


def _merge_init_semantically(local: bytes) -> bytes:
    """Preserve every existing registration, adding exactly two VIP hooks."""
    source = local.decode("utf-8")
    hooks = (
        ("from .advanced_features import register_advanced_features",
         "from .vip import register_vip"),
        ("    register_advanced_features(backend_app.app)",
         "    register_vip(backend_app.app)"),
    )
    for anchor, insertion in hooks:
        if insertion in source:
            if source.count(insertion) != 1:
                raise RuntimeError("server/__init__.py: duplicate VIP registration")
            continue
        if source.count(anchor) != 1:
            raise RuntimeError("server/__init__.py: VIP insertion anchor ambiguous or absent")
        source = source.replace(anchor + "\n", anchor + "\n" + insertion + "\n", 1)
    return source.encode("utf-8")


def _merge_nyan_id_css_semantically(local: bytes, remote: bytes) -> bytes:
    """Only append the paid-VIP styles; never alter local Nyan ID CSS."""
    source = local.decode("utf-8")
    latest = remote.decode("utf-8")
    marker = "/* Paid VIP is independent from the lifetime-earned rank. */"
    if latest.count(marker) != 1:
        raise RuntimeError("nyan_id.css: expected VIP CSS block missing")
    vip_rules = marker + latest.split(marker, 1)[1]
    if marker in source:
        if source.count(marker) == 1 and vip_rules.strip() in source:
            return local
        raise RuntimeError("nyan_id.css: existing VIP styles differ; refusing overwrite")
    if ".nyid-card.nyid-vip-active" in source:
        raise RuntimeError("nyan_id.css: an existing VIP rule requires manual review")
    return (source.rstrip("\n") + "\n\n" + vip_rules.rstrip("\n") + "\n").encode("utf-8")


def _merge_index_semantically(local: bytes) -> bytes:
    """Add only the VIP asset tags, preserving all other HTML and local routes."""
    import re
    source = local.decode("utf-8")

    anchors = (
        ("css", "href", "nyan_id.css", "vip.css", "20261122-vip2"),
        ("js", "src", "nyan_id.js", "vip.js", "20261122-vip2"),
    )
    for kind, attribute, anchor_file, vip_file, revision in anchors:
        regex = re.compile(
            rf"""<{ 'link' if kind == 'css' else 'script' }\b[^>]*"""
            rf"""\b{attribute}\s*=\s*(?P<quote>["'])"""
            rf"""(?P<url>(?:\./)?{re.escape(anchor_file)}(?:\?[^"']*)?)"""
            rf"""(?P=quote)[^>]*>"""
            + (r"\s*</script>" if kind == "js" else ""),
            re.I,
        )
        found = list(regex.finditer(source))
        if len(found) != 1:
            raise RuntimeError(
                f"index.html: expected exactly one {anchor_file} tag, found {len(found)}"
            )
        existing_vip = re.findall(
            rf"""(?:\./)?{re.escape(vip_file)}(?:\?[^"' >]*)?""", source
        )
        if len(existing_vip) > 1:
            raise RuntimeError(f"index.html: duplicated {vip_file} asset")
        match = found[0]
        # Keep the existing tag, its attributes and its relative position.
        tag = match.group(0)
        updated_tag = tag.replace(
            match.group("url"), f"./{anchor_file}?v={revision}", 1
        )
        if not existing_vip:
            addition = (
                f'\n    <link rel="stylesheet" href="./vip.css?v={revision}">'
                if kind == "css" else
                f'\n<script src="./vip.js?v={revision}"></script>'
            )
            updated_tag += addition
        source = source[:match.start()] + updated_tag + source[match.end():]

    if source.count("vip.css?v=") != 1 or source.count("vip.js?v=") != 1:
        raise RuntimeError("index.html: VIP tags must appear exactly once")
    return source.encode("utf-8")


def merge_one(path: str, local: bytes) -> bytes:
    base_raw = show(BASE, path)
    vip_raw = show(SOURCE, path)

    if path == "server/__init__.py":
        return _merge_init_semantically(local)

    if path == "nyan_id.css":
        return _merge_nyan_id_css_semantically(local, vip_raw)
    if path == "index.html":
        return _merge_index_semantically(local)

    with tempfile.TemporaryDirectory(prefix="nyan-vip-merge-") as temp:
        folder = Path(temp)
        ours = folder / "ours"
        common = folder / "base"
        theirs = folder / "vip"
        ours.write_bytes(local)
        common.write_bytes(base_raw)
        theirs.write_bytes(vip_raw)
        result = run(
            "git", "merge-file", "--diff3", "-p",
            str(ours), str(common), str(theirs),
            check=False,
        )
        if result.returncode == 0 and b"<<<<<<<" not in result.stdout:
            return result.stdout

    return _add_vip_delta(path, local, base_raw, vip_raw)


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
        "vip.js": (b"/api/vip/status", b"vip_purchase_key="),
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
    errors: list[str] = []
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
            try:
                desired[path] = merge_one(path, existing)
            except RuntimeError as exc:
                errors.append(str(exc))
        else:
            remote = show(SOURCE, path)
            if existing is not None and existing != remote:
                errors.append(f"{path}: existing local file differs from VIP source")
            else:
                desired[path] = remote

    if errors:
        raise RuntimeError("VIP preflight conflicts (nothing changed):\n" + "\n".join(errors))
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
