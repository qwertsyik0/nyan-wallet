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

MODULE_URL = (
    "https://raw.githubusercontent.com/qwertsyik0/nyan-wallet/"
    "8178fbbddfac9cf6e8e394e8e4837176c1b31ed5/"
    "bot_addons/broadcast_bot.py"
)
IMPORT_LINE = "from broadcast_bot import register_broadcast_handlers"
REGISTER_NAME = "register_broadcast_handlers"


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
    target = path.with_name(f"{path.name}.before_broadcast_{stamp}.bak")
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
            raise InstallError(
                f"run_polling в строке {node.lineno} вызывается через сложное выражение; "
                "автопатч остановлен"
            )
        calls.append((node.lineno, receiver.id))
    return sorted(calls)


def has_import(tree: ast.Module) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "broadcast_bot":
            if any(alias.name == REGISTER_NAME for alias in node.names):
                return True
    return False


def has_registration(tree: ast.Module) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id == REGISTER_NAME:
                return True
    return False


def add_registration(source: str) -> str:
    tree = parse(source, "bot.py")
    if has_registration(tree):
        return source

    calls = run_polling_calls(tree)
    if len(calls) != 1:
        raise InstallError(
            f"Ожидался ровно один вызов *.run_polling(...), найдено {len(calls)}"
        )

    lineno, app_name = calls[0]
    lines = source.splitlines(keepends=True)
    original = lines[lineno - 1]
    indent = original[: len(original) - len(original.lstrip(" \t"))]
    newline = "\r\n" if original.endswith("\r\n") else "\n"
    lines.insert(lineno - 1, f"{indent}{REGISTER_NAME}({app_name}){newline}")
    return "".join(lines)


def add_import(source: str) -> str:
    tree = parse(source, "bot.py")
    if has_import(tree):
        return source

    body = tree.body
    insert_after = 0
    index = 0
    if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    ):
        insert_after = getattr(body[0], "end_lineno", body[0].lineno)
        index = 1

    while index < len(body) and isinstance(body[index], (ast.Import, ast.ImportFrom)):
        node = body[index]
        insert_after = getattr(node, "end_lineno", node.lineno)
        index += 1

    newline = "\r\n" if "\r\n" in source else "\n"
    lines = source.splitlines(keepends=True)
    lines.insert(insert_after, IMPORT_LINE + newline)
    return "".join(lines)


def patch_bot(source: str) -> str:
    parse(source, "bot.py")
    patched = add_import(add_registration(source))
    tree = parse(patched, "bot.py after patch")
    if not has_import(tree) or not has_registration(tree):
        raise InstallError("Не удалось безопасно подключить broadcast handler")
    if len(run_polling_calls(tree)) != 1:
        raise InstallError("После патча изменилось количество run_polling")
    return patched


def download_module() -> bytes:
    request = urllib.request.Request(
        MODULE_URL,
        headers={"User-Agent": "Nyan-Wallet-Broadcast-Installer/1.0"},
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            data = response.read()
    except Exception as exc:
        raise InstallError(f"Не удалось скачать broadcast_bot.py: {exc}") from exc

    try:
        source = data.decode("utf-8")
        compile(source, "broadcast_bot.py", "exec")
    except Exception as exc:
        raise InstallError(f"Загруженный broadcast_bot.py повреждён: {exc}") from exc
    return data


def choose_python(root: Path) -> Path:
    for candidate in (root / "venv" / "bin" / "python", root / ".venv" / "bin" / "python"):
        if candidate.exists() and os.access(candidate, os.X_OK):
            return candidate
    return Path(sys.executable)


def check_environment(python: Path, root: Path) -> None:
    result = subprocess.run(
        [str(python), "-c", "import telegram; print(telegram.__version__)"],
        cwd=root,
        text=True,
        capture_output=True,
    )
    if result.returncode != 0:
        raise InstallError("python-telegram-bot не импортируется: " + result.stderr.strip())


def run_checks(python: Path, root: Path, files: list[Path]) -> None:
    result = subprocess.run(
        [str(python), "-m", "py_compile", *[str(path) for path in files]],
        cwd=root,
        text=True,
        capture_output=True,
    )
    if result.returncode != 0:
        raise InstallError("py_compile не прошёл:\n" + (result.stderr.strip() or result.stdout.strip()))

    smoke = subprocess.run(
        [
            str(python),
            "-c",
            (
                "import broadcast_bot; "
                "assert callable(broadcast_bot.register_broadcast_handlers); "
                "print('OK')"
            ),
        ],
        cwd=root,
        text=True,
        capture_output=True,
    )
    if smoke.returncode != 0:
        raise InstallError("broadcast_bot не импортируется:\n" + smoke.stderr.strip())


def main() -> int:
    parser = argparse.ArgumentParser(description="Install Nyan Wallet broadcast commands")
    parser.add_argument("--root", default=".", help="Каталог Telegram-бота")
    args = parser.parse_args()

    root = Path(args.root).expanduser().resolve()
    bot_path = root / "bot.py"
    module_path = root / "broadcast_bot.py"

    if not bot_path.is_file():
        raise InstallError(f"Не найден {bot_path}")

    python = choose_python(root)
    check_environment(python, root)

    original_bot_bytes = bot_path.read_bytes()
    try:
        original_bot = original_bot_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise InstallError("bot.py должен быть в UTF-8") from exc

    module_bytes = download_module()
    patched_bot = patch_bot(original_bot)

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    bot_backup = backup(bot_path, stamp)
    module_backup = backup(module_path, stamp)

    old_module = module_path.read_bytes() if module_path.exists() else None
    bot_mode = bot_path.stat().st_mode & 0o777
    module_mode = module_path.stat().st_mode & 0o777 if module_path.exists() else 0o600

    try:
        atomic_write(module_path, module_bytes, module_mode)
        atomic_write(bot_path, patched_bot.encode("utf-8"), bot_mode)
        run_checks(python, root, [bot_path, module_path])
    except Exception:
        atomic_write(bot_path, original_bot_bytes, bot_mode)
        if old_module is None:
            module_path.unlink(missing_ok=True)
        else:
            atomic_write(module_path, old_module, module_mode)
        raise

    print("✅ Рассылка установлена")
    print("✅ bot.py и broadcast_bot.py прошли py_compile и import smoke-test")
    if bot_backup:
        print(f"📦 Бэкап bot.py: {bot_backup.name}")
    if module_backup:
        print(f"📦 Бэкап broadcast_bot.py: {module_backup.name}")
    print("ℹ️ Перезапусти единственный процесс бота после установки.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except InstallError as exc:
        print(f"❌ Установка остановлена: {exc}", file=sys.stderr)
        raise SystemExit(1)
