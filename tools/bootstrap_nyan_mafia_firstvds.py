#!/usr/bin/env python3
"""Fetch a pinned NYAN MAFIA bundle and run its guarded VPS installer."""

import argparse
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path
from zipfile import ZipFile


BASE = "https://raw.githubusercontent.com/qwertsyik0/nyan-wallet/019b0423adeceea2c3acd51aa06b6519cae859c5/"
FILES = (
    "server/nyan_mafia.py",
    "server/nyan_mafia_rules.py",
    "tools/install_nyan_mafia_firstvds.py",
)


def main():
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="nyan-mafia-") as temp:
        folder = Path(temp)
        for name in FILES:
            request = urllib.request.Request(BASE + name, headers={"User-Agent": "Nyan-Mafia-Installer"})
            with urllib.request.urlopen(request, timeout=25) as response:
                data = response.read(160001)
            if not data or len(data) > 160000:
                raise RuntimeError("unexpected download size for " + name)
            target = folder / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        archive_path = folder / "nyan-mafia.zip"
        with ZipFile(archive_path, "w") as bundle:
            for name in FILES[:2]:
                bundle.write(folder / name, name)
        command = [sys.executable, str(folder / FILES[2]), "--bundle", str(archive_path), "--root", "/opt/nyan-wallet", "--apply" if args.apply else "--check"]
        subprocess.run(command, check=True)


if __name__ == "__main__":
    main()
