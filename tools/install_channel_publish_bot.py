from __future__ import annotations

import argparse
import ast
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from datetime import datetime
from pathlib import Path

RAW_BASE = "https://raw.githubusercontent.com/qwertsyik0/nyan-wallet/main"
MODULES = {
    "broadcast_bot.py": f"{RAW_BASE}/bot_addons/broadcast_bot.py",
    "channel_publish_bot.py": f"{RAW_BASE}/bot_addons/channel_publish_bot.py",
}
IMPORTS = [
    "from broadcast_bot import register_broadcast_handlers",
    "from channel_publish_bot import register_channel_publish_handlers",
]
REGISTRATIONS = [
    "register_broadcast_handlers",
    "register_channel_publish_handlers",
]


class InstallError(RuntimeError):
    pass


def atomic_write(path: Path, data: bytes, mode: int | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    temp = Path(temp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        if mode is not None:
            os.chmod(temp, mode)
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def backup(path: Path, stamp: str) -> Path | None:
    if not path.exists():
        return None
    target = path.with_name(f"{path.name}.before_channel_publish_{stamp}.bak")
    shutil.copy2(path, target)
    return target


def parse(source: str, name: str) -> ast.Module:
    try:
        return ast.parse(source, filename=name)
    except SyntaxError as exc:
        raise InstallError(f"{name} содержит синтаксическую ошибку: {exc}") from exc


def run_polling_calls(tree: ast.Module) -> list[tuple[int, str]]:
    calls: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Attribute) or func.attr != "run_polling":
            continue
        receiver = func.value
        if not isinstance(receiver, ast.Name):
            raise InstallError("run_polling вызывается через сложное выражение, автопатч остановлен")
        calls.append((node.lineno, receiver.id))
    return sorted(calls)


def has_import(tree: ast.Module, module: str, name: str) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == module:
            if any(alias.name == name for alias in node.names):
                return True
    return False


def has_registration(tree: ast.Module, name: str) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == name:
            return True
    return False


def add_imports(source: str) -> str:
    tree = parse(source, "bot.py")
    lines = source.splitlines(keepends=True)
    body = tree.body
    insert_after = 0
    index = 0
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) and isinstance(body[0].value.value, str):
        insert_after = getattr(body[0], "end_lineno", body[0].lineno)
        index = 1
    while index < len(body) and isinstance(body[index], (ast.Import, ast.ImportFrom)):
        node = body[index]
        insert_after = getattr(node, "end_lineno", node.lineno)
        index += 1
    newline = "\r\n" if "\r\n" in source else "\n"
    to_add = []
    for line in IMPORTS:
        module = line.split(" import ", 1)[0].removeprefix("from ")
        name = line.split(" import ", 1)[1]
        if not has_import(tree, module, name):
            to_add.append(line + newline)
    if to_add:
        lines[insert_after:insert_after] = to_add
    return "".join(lines)


def add_registrations(source: str) -> str:
    tree = parse(source, "bot.py")
    calls = run_polling_calls(tree)
    if len(calls) != 1:
        raise InstallError(f"Ожидался ровно один вызов *.run_polling(...), найдено {len(calls)}")
    lineno, app_name = calls[0]
    lines = source.splitlines(keepends=True)
    original = lines[lineno - 1]
    indent = original[: len(original) - len(original.lstrip(" \t"))]
    newline = "\r\n" if original.endswith("\r\n") else "\n"
    insertions = []
    for name in REGISTRATIONS:
        if not has_registration(tree, name):
            insertions.append(f"{indent}{name}({app_name}){newline}")
    if insertions:
        lines[lineno - 1:lineno - 1] = insertions
    return "".join(lines)


def patch_bot(source: str) -> str:
    patched = add_registrations(add_imports(source))
    tree = parse(patched, "bot.py after channel publish patch")
    for line in IMPORTS:
        module = line.split(" import ", 1)[0].removeprefix("from ")
        name = line.split(" import ", 1)[1]
        if not has_import(tree, module, name):
            raise InstallError(f"Не удалось добавить импорт {name}")
    for name in REGISTRATIONS:
        if not has_registration(tree, name):
            raise InstallError(f"Не удалось подключить {name}")
    return patched


def download(url: str, name: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "Nyan-Wallet-Channel-Publisher-Installer/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            data = response.read()
    except Exception as exc:
        raise InstallError(f"Не удалось скачать {name}: {exc}") from exc
    try:
        compile(data.decode("utf-8"), name, "exec")
    except Exception as exc:
        raise InstallError(f"{name} повреждён: {exc}") from exc
    return data


def choose_python(root: Path) -> Path:
    for candidate in (root / "venv" / "bin" / "python", root / ".venv" / "bin" / "python"):
        if candidate.exists() and os.access(candidate, os.X_OK):
            return candidate
    return Path(sys.executable)


def run_checks(python: Path, root: Path, files: list[Path]) -> None:
    result = subprocess.run([str(python), "-m", "py_compile", *map(str, files)], cwd=root, text=True, capture_output=True)
    if result.returncode != 0:
        raise InstallError("py_compile не прошёл:\n" + (result.stderr.strip() or result.stdout.strip()))
    smoke = subprocess.run(
        [str(python), "-c", "import broadcast_bot, channel_publish_bot; assert callable(channel_publish_bot.register_channel_publish_handlers); print('OK')"],
        cwd=root,
        text=True,
        capture_output=True,
    )
    if smoke.returncode != 0:
        raise InstallError("channel_publish_bot не импортируется:\n" + smoke.stderr.strip())


def main() -> int:
    parser = argparse.ArgumentParser(description="Install Nyan Wallet channel publisher")
    parser.add_argument("--root", default=".", help="Каталог Telegram-бота")
    args = parser.parse_args()
    root = Path(args.root).expanduser().resolve()
    bot_path = root / "bot.py"
    if not bot_path.exists():
        raise InstallError(f"bot.py не найден: {bot_path}")
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup(bot_path, stamp)
    files = [bot_path]
    for filename, url in MODULES.items():
        data = download(url, filename)
        target = root / filename
        backup(target, stamp)
        atomic_write(target, data, 0o600)
        files.append(target)
    source = bot_path.read_text(encoding="utf-8")
    patched = patch_bot(source)
    atomic_write(bot_path, patched.encode("utf-8"), 0o600)
    run_checks(choose_python(root), root, files)
    print("OK: channel publishing installed")
    print("Set TELEGRAM_CHANNEL_ID in the bot environment before publishing.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except InstallError as exc:
        print("ERROR:", exc, file=sys.stderr)
        raise SystemExit(1)
