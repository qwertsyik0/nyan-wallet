from __future__ import annotations

import argparse
import ast
import base64
import gzip
import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from datetime import datetime
from pathlib import Path

PAYLOAD_URL = (
    "https://raw.githubusercontent.com/qwertsyik0/nyan-wallet/"
    "9a3ee6c15561960579c3e5481f8cc83c2fe51144/"
    "bot_addons/giveaway_bot.py.gz.b64"
)
EXPECTED_B64_SHA256 = "d1ab94e7703e1fb5ba467586d54a02a5b3c56d382d1d49cc54b3c3ce9540800a"
EXPECTED_SOURCE_SHA256 = "b2c8fc0749bc0066509828c6b2f0fde92542a772ae9d68d2e8350b55e6567c98"
OWNER_TELEGRAM_ID = "6289461565"
API_BASE = "https://nyan-wallet-api.onrender.com"
IMPORT_LINE = "from giveaway_bot import register_giveaway_handlers"
REGISTER_NAME = "register_giveaway_handlers"


class InstallError(RuntimeError):
    pass


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def download_payload() -> bytes:
    request = urllib.request.Request(
        PAYLOAD_URL,
        headers={"User-Agent": "Nyan-Cash-Giveaway-Installer/1.0"},
    )
    try:
        with urllib.request.urlopen(request, timeout=25) as response:
            encoded = response.read()
    except Exception as exc:
        raise InstallError(f"Не удалось скачать модуль розыгрышей: {exc}") from exc

    if sha256_bytes(encoded) != EXPECTED_B64_SHA256:
        raise InstallError("Контрольная сумма загруженного payload не совпала")

    try:
        source = gzip.decompress(base64.b64decode(encoded, validate=True))
    except Exception as exc:
        raise InstallError(f"Payload повреждён: {exc}") from exc

    if sha256_bytes(source) != EXPECTED_SOURCE_SHA256:
        raise InstallError("Контрольная сумма giveaway_bot.py не совпала")

    try:
        compile(source.decode("utf-8"), "giveaway_bot.py", "exec")
    except Exception as exc:
        raise InstallError(f"giveaway_bot.py не проходит синтаксическую проверку: {exc}") from exc
    return source


def choose_python(root: Path) -> Path:
    candidates = [root / "venv" / "bin" / "python", root / ".venv" / "bin" / "python"]
    for candidate in candidates:
        if candidate.exists() and os.access(candidate, os.X_OK):
            return candidate
    executable = Path(sys.executable)
    if executable.exists():
        return executable
    raise InstallError("Не найден Python для проверки")


def check_ptb(python: Path, root: Path) -> str:
    command = [
        str(python),
        "-c",
        "import telegram; print(telegram.__version__)",
    ]
    result = subprocess.run(command, cwd=root, text=True, capture_output=True)
    if result.returncode != 0:
        raise InstallError(
            "В окружении бота не импортируется python-telegram-bot: "
            + (result.stderr.strip() or result.stdout.strip() or "неизвестная ошибка")
        )
    version = result.stdout.strip().splitlines()[-1].strip()
    match = re.match(r"^(\d+)\.(\d+)", version)
    if not match:
        raise InstallError(f"Не удалось определить версию python-telegram-bot: {version}")
    major, minor = int(match.group(1)), int(match.group(2))
    if major != 22 or minor < 8:
        raise InstallError(
            f"Нужен python-telegram-bot 22.8.x (или совместимый 22.x >= 22.8), найден {version}"
        )
    return version


def parse_python(source: str, filename: str) -> ast.Module:
    try:
        return ast.parse(source, filename=filename)
    except SyntaxError as exc:
        raise InstallError(f"{filename} уже содержит синтаксическую ошибку: {exc}") from exc


def has_import(tree: ast.Module) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "giveaway_bot":
            if any(alias.name == REGISTER_NAME for alias in node.names):
                return True
    return False


def has_registration(tree: ast.Module) -> bool:
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name) and func.id == REGISTER_NAME:
            return True
    return False


def run_polling_calls(tree: ast.Module) -> list[tuple[int, str]]:
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (isinstance(func, ast.Attribute) and func.attr == "run_polling"):
            continue
        receiver = func.value
        if not isinstance(receiver, ast.Name):
            raise InstallError(
                f"run_polling в строке {node.lineno} вызывается не через простую переменную; безопасная автозамена остановлена"
            )
        found.append((node.lineno, receiver.id))
    return sorted(found)


def add_registration(source: str) -> str:
    tree = parse_python(source, "bot.py")
    if has_registration(tree):
        return source

    calls = run_polling_calls(tree)
    if len(calls) != 1:
        raise InstallError(
            f"Ожидался ровно один вызов *.run_polling(...), найдено {len(calls)}. bot.py не изменён."
        )

    lineno, app_name = calls[0]
    lines = source.splitlines(keepends=True)
    original = lines[lineno - 1]
    indent = original[: len(original) - len(original.lstrip(" \t"))]
    newline = "\r\n" if original.endswith("\r\n") else "\n"
    lines.insert(lineno - 1, f"{indent}{REGISTER_NAME}({app_name}){newline}")
    return "".join(lines)


def add_import(source: str) -> str:
    tree = parse_python(source, "bot.py")
    if has_import(tree):
        return source

    lines = source.splitlines(keepends=True)
    insert_after = 0
    body = tree.body

    index = 0
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) and isinstance(body[0].value.value, str):
        insert_after = getattr(body[0], "end_lineno", body[0].lineno)
        index = 1

    while index < len(body):
        node = body[index]
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            insert_after = getattr(node, "end_lineno", node.lineno)
            index += 1
            continue
        break

    newline = "\r\n" if "\r\n" in source else "\n"
    lines.insert(insert_after, IMPORT_LINE + newline)
    return "".join(lines)


def patch_bot(source: str) -> str:
    parse_python(source, "bot.py")
    patched = add_registration(source)
    patched = add_import(patched)
    tree = parse_python(patched, "bot.py (после патча)")

    if not has_import(tree):
        raise InstallError("После патча отсутствует импорт register_giveaway_handlers")
    if not has_registration(tree):
        raise InstallError("После патча отсутствует register_giveaway_handlers(app)")
    if len(run_polling_calls(tree)) != 1:
        raise InstallError("После патча изменилось число run_polling вызовов")
    return patched


def env_value(text: str, key: str) -> str | None:
    pattern = re.compile(rf"(?m)^\s*{re.escape(key)}\s*=\s*(.*?)\s*$")
    match = pattern.search(text)
    if not match:
        return None
    value = match.group(1).strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        value = value[1:-1]
    return value


def ensure_env(text: str) -> str:
    owner = env_value(text, "OWNER_TELEGRAM_ID")
    if owner is not None and owner != OWNER_TELEGRAM_ID:
        raise InstallError(
            f"В .env уже указан OWNER_TELEGRAM_ID={owner}, ожидался {OWNER_TELEGRAM_ID}. Изменения остановлены."
        )
    api = env_value(text, "NYAN_WALLET_API")
    if api is not None and api.rstrip("/") != API_BASE:
        raise InstallError(
            f"В .env уже указан другой NYAN_WALLET_API={api}. Изменения остановлены."
        )

    newline = "\r\n" if "\r\n" in text else "\n"
    result = text
    if result and not result.endswith(("\n", "\r")):
        result += newline
    if owner is None:
        result += f"OWNER_TELEGRAM_ID={OWNER_TELEGRAM_ID}{newline}"
    if api is None:
        result += f"NYAN_WALLET_API={API_BASE}{newline}"
    return result


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
        if temp.exists():
            temp.unlink(missing_ok=True)


def backup(path: Path, stamp: str) -> Path | None:
    if not path.exists():
        return None
    target = path.with_name(f"{path.name}.before_giveaway_{stamp}.bak")
    shutil.copy2(path, target)
    return target


def run_checks(python: Path, root: Path, files: list[Path]) -> None:
    command = [str(python), "-m", "py_compile", *[str(path) for path in files]]
    result = subprocess.run(command, cwd=root, text=True, capture_output=True)
    if result.returncode != 0:
        raise InstallError("py_compile не прошёл:\n" + (result.stderr.strip() or result.stdout.strip()))

    smoke = subprocess.run(
        [
            str(python),
            "-c",
            "import giveaway_bot; assert callable(giveaway_bot.register_giveaway_handlers); print('giveaway_bot import OK')",
        ],
        cwd=root,
        text=True,
        capture_output=True,
    )
    if smoke.returncode != 0:
        raise InstallError("Импорт giveaway_bot не прошёл:\n" + (smoke.stderr.strip() or smoke.stdout.strip()))


def main() -> int:
    parser = argparse.ArgumentParser(description="Install Nyan Cash giveaway handlers safely")
    parser.add_argument("--root", default=".", help="Каталог Telegram-бота, по умолчанию текущий")
    args = parser.parse_args()

    root = Path(args.root).expanduser().resolve()
    bot_path = root / "bot.py"
    env_path = root / ".env"
    module_path = root / "giveaway_bot.py"

    if not bot_path.is_file():
        raise InstallError(f"Не найден {bot_path}")
    if not env_path.is_file():
        raise InstallError(f"Не найден {env_path}")

    python = choose_python(root)
    version = check_ptb(python, root)
    source_bytes = download_payload()

    original_bot_bytes = bot_path.read_bytes()
    try:
        original_bot = original_bot_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise InstallError("bot.py должен быть в UTF-8") from exc

    original_env_bytes = env_path.read_bytes()
    try:
        original_env = original_env_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise InstallError(".env должен быть в UTF-8") from exc

    patched_bot = patch_bot(original_bot)
    patched_env = ensure_env(original_env)

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    bot_backup = backup(bot_path, stamp)
    env_backup = backup(env_path, stamp)
    module_backup = backup(module_path, stamp)

    old_module = module_path.read_bytes() if module_path.exists() else None
    bot_mode = bot_path.stat().st_mode & 0o777
    env_mode = env_path.stat().st_mode & 0o777
    module_mode = module_path.stat().st_mode & 0o777 if module_path.exists() else 0o600

    try:
        atomic_write(module_path, source_bytes, module_mode)
        atomic_write(bot_path, patched_bot.encode("utf-8"), bot_mode)
        atomic_write(env_path, patched_env.encode("utf-8"), env_mode)
        run_checks(python, root, [bot_path, module_path])
    except Exception:
        atomic_write(bot_path, original_bot_bytes, bot_mode)
        atomic_write(env_path, original_env_bytes, env_mode)
        if old_module is None:
            module_path.unlink(missing_ok=True)
        else:
            atomic_write(module_path, old_module, module_mode)
        raise

    print("✅ Модуль розыгрышей установлен и проверен")
    print(f"✅ python-telegram-bot: {version}")
    print(f"✅ giveaway_bot.py SHA256: {EXPECTED_SOURCE_SHA256}")
    print("✅ bot.py и giveaway_bot.py прошли py_compile + import smoke-test")
    if bot_backup:
        print(f"📦 Бэкап bot.py: {bot_backup.name}")
    if env_backup:
        print(f"📦 Бэкап .env: {env_backup.name}")
    if module_backup:
        print(f"📦 Бэкап старого giveaway_bot.py: {module_backup.name}")
    print("ℹ️ Процесс бота установщик специально не перезапускал.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except InstallError as exc:
        print(f"❌ Установка остановлена: {exc}", file=sys.stderr)
        raise SystemExit(1)
