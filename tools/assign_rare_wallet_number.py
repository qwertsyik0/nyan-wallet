#!/usr/bin/env python3
"""Safely install persistent wallet numbers, then fulfil one explicit rare-number request."""
import argparse
import ast
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

CORE_BLOCK = "\nclass WalletCustomNumber(Base):\n    __tablename__ = \"wallet_custom_numbers\"\n    telegram_id: Mapped[int] = mapped_column(BigInteger, ForeignKey(\"users.telegram_id\", ondelete=\"CASCADE\"), primary_key=True)\n    number: Mapped[str] = mapped_column(String(12), unique=True, nullable=False)\n    request_id: Mapped[int] = mapped_column(Integer, unique=True, nullable=False)\n    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)\n    notice_body: Mapped[str] = mapped_column(Text, nullable=False)\n    notice_state: Mapped[str] = mapped_column(String(16), nullable=False, default=\"pending\")\n    notice_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)\n\n\ndef get_custom_wallet_number(telegram_id: int) -> str | None:\n    with SessionLocal() as number_session:\n        number = number_session.scalar(select(WalletCustomNumber.number).where(WalletCustomNumber.telegram_id == telegram_id))\n    if number:\n        return \"NYAN \" + \" \".join(number[i:i + 4] for i in range(0, 12, 4))\n    return None\n\n"


def patch_core(source):
    if "class WalletCustomNumber(" not in source:
        anchor = "Base.metadata.create_all(engine)"
        if source.count(anchor) != 1:
            raise RuntimeError("Не найден безопасный якорь создания схемы")
        source = source.replace(anchor, CORE_BLOCK + "\n" + anchor, 1)
    tree = ast.parse(source)
    method = next((n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "serialize_user"), None)
    if method is None:
        raise RuntimeError("Не найдена функция serialize_user")
    lines = source.splitlines(keepends=True)
    chunk = "".join(lines[method.lineno - 1:method.end_lineno])
    if '"wallet_number": get_custom_wallet_number(' not in chunk:
        anchor = '"unlimited_balance": owner,'
        if chunk.count(anchor) != 1:
            raise RuntimeError("Не найден безопасный якорь номера в API")
        chunk = chunk.replace(anchor, anchor + '\n        "wallet_number": get_custom_wallet_number(user.telegram_id),', 1)
        source = "".join(lines[:method.lineno - 1]) + chunk + "".join(lines[method.end_lineno:])
    compile(source, "server/backend_app.py", "exec")
    return source


def schema(engine):
    from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, Integer, MetaData, String, Table, Text
    m = MetaData()
    t = {name: Table(name, m, autoload_with=engine, resolve_fks=False)
         for name in ("users", "spend_requests", "wallet_notifications", "spend_request_meta", "admin_audit")}
    t["numbers"] = Table("wallet_custom_numbers", m,
        Column("telegram_id", BigInteger, ForeignKey("users.telegram_id", ondelete="CASCADE"), primary_key=True),
        Column("number", String(12), unique=True, nullable=False),
        Column("request_id", Integer, unique=True, nullable=False),
        Column("created_at", DateTime(timezone=True), nullable=False),
        Column("notice_body", Text, nullable=False),
        Column("notice_state", String(16), nullable=False, default="pending"),
        Column("notice_message_id", BigInteger, nullable=True))
    return t


def generated_number(telegram_id):
    left, right = 0x811c9dc5, 0x9e3779b9
    for ch in f"nyan-wallet:{telegram_id}":
        code = ord(ch)
        left = ((left ^ code) * 16777619) & 0xffffffff
        right = ((right ^ code) * 2246822519) & 0xffffffff
    return f"{left % 1000000:06d}{right % 1000000:06d}"


def assign(engine, request_id, telegram_id, raw_number):
    from sqlalchemy import select, text
    number = raw_number.replace("NYAN", "").replace(" ", "")
    if len(number) != 12 or not number.isascii() or not number.isdigit():
        raise RuntimeError("Номер должен содержать 12 цифр")
    if number == "777777777777":
        raise RuntimeError("Этот номер зарезервирован владельцем")
    t = schema(engine)
    n, r, u = t["numbers"], t["spend_requests"], t["users"]
    with engine.begin() as conn:
        if engine.dialect.name == "postgresql":
            conn.execute(text("SELECT pg_advisory_xact_lock(692235143)"))
        n.create(conn, checkfirst=True)
        request = conn.execute(select(r).where(r.c.id == request_id).with_for_update()).mappings().one_or_none()
        if not request or request["telegram_id"] != telegram_id or "Редкий номер кошелька" not in request["reward_title"]:
            raise RuntimeError("Заявка или получатель не соответствует редкому номеру")
        user = conn.execute(select(u).where(u.c.telegram_id == telegram_id).with_for_update()).mappings().one_or_none()
        if not user:
            raise RuntimeError("Кошелёк получателя не найден")
        existing = conn.execute(select(n).where(n.c.telegram_id == telegram_id)).mappings().one_or_none()
        if existing:
            if existing["request_id"] == request_id and existing["number"] == number and request["status"] == "fulfilled":
                return False
            raise RuntimeError("У получателя уже есть другой редкий номер. Изменения не применены")
        if request["status"] != "pending":
            raise RuntimeError("Заявка уже обработана, выдача остановлена")
        custom = dict(conn.execute(select(n.c.telegram_id, n.c.number)).all())
        if number in custom.values():
            raise RuntimeError("Этот номер уже занят")
        for uid in conn.execute(select(u.c.telegram_id)).scalars():
            if uid != telegram_id and uid not in custom and generated_number(uid) == number:
                raise RuntimeError("Этот номер уже используется кошельком")
        now = datetime.now(timezone.utc)
        formatted = "NYAN " + " ".join(number[i:i + 4] for i in range(0, 12, 4))
        body = f"Заявка #{request_id} выполнена!\nТебе установлен редкий номер кошелька: {formatted}.\nОткрой Nyan Wallet заново, чтобы увидеть его на карточке."
        conn.execute(n.insert().values(
            telegram_id=telegram_id, number=number, request_id=request_id, created_at=now,
            notice_body=body, notice_state="pending"))
        conn.execute(r.update().where(r.c.id == request_id).values(status="fulfilled", processed_at=now))
        meta = t["spend_request_meta"]
        previous = conn.execute(select(meta).where(meta.c.request_id == request_id)).mappings().one_or_none()
        comment = f"Установлен редкий номер {formatted}"
        if previous:
            comment = ((previous["owner_comment"] + "\n") if previous["owner_comment"] else "") + comment
            conn.execute(meta.update().where(meta.c.request_id == request_id).values(owner_comment=comment, updated_at=now))
        else:
            conn.execute(meta.insert().values(request_id=request_id, owner_comment=comment, updated_at=now))
        conn.execute(t["wallet_notifications"].insert().values(
            telegram_id=telegram_id, kind="wallet_number", title="Редкий номер установлен",
            body=body, is_read=False, created_at=now))
        conn.execute(t["admin_audit"].insert().values(
            action="wallet_number_assigned", target_telegram_id=telegram_id,
            details=f"Заявка #{request_id}, номер {formatted}", created_at=now))
    return True


def deliver(engine, telegram_id, request_id, token, sender=None):
    from sqlalchemy import select
    n = schema(engine)["numbers"]
    with engine.begin() as conn:
        row = conn.execute(select(n).where(n.c.telegram_id == telegram_id).with_for_update()).mappings().one()
        if row["request_id"] != request_id:
            raise RuntimeError("Номер выдан по другой заявке")
        if row["notice_state"] != "pending":
            return row["notice_state"]
        conn.execute(n.update().where(n.c.telegram_id == telegram_id).values(notice_state="sending"))
        body = row["notice_body"]
    if sender:
        state, message_id = sender(token, telegram_id, body)
    else:
        state, message_id = "uncertain", None
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data=urllib.parse.urlencode({"chat_id": telegram_id, "text": body}).encode())
        try:
            with urllib.request.urlopen(req, timeout=20) as response:
                data = json.load(response)
            if data.get("ok"):
                state, message_id = "sent", data["result"]["message_id"]
            else:
                state = "pending"
        except urllib.error.HTTPError as error:
            state = "pending" if error.code in (400, 401, 403, 404, 429) else "uncertain"
        except Exception:
            pass
    with engine.begin() as conn:
        conn.execute(n.update().where(n.c.telegram_id == telegram_id).values(notice_state=state, notice_message_id=message_id))
    return state


def replace_atomic(path, content):
    handle, filename = tempfile.mkstemp(prefix=".wallet-number-", dir=path.parent)
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(filename, path.stat().st_mode & 0o777)
        os.replace(filename, path)
    finally:
        Path(filename).unlink(missing_ok=True)


def service_value(name):
    return subprocess.check_output(
        ["systemctl", "show", "nyan-wallet", "-p", name, "--value"], text=True).strip()


def health(timeout=120):
    # A local readiness probe must not follow HTTP_PROXY from the SSH shell.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    started = time.monotonic()
    deadline = started + timeout
    next_message = started + 10
    last = "соединение ещё не установлено"
    while time.monotonic() < deadline:
        try:
            with opener.open("http://127.0.0.1:8000/api/health", timeout=3) as response:
                data = json.load(response)
            if isinstance(data, dict) and data.get("ok") is True:
                return
            last = "API ответил, но не подтвердил готовность"
        except urllib.error.HTTPError as error:
            last = f"HTTP {error.code}"
        except urllib.error.URLError as error:
            last = "нет соединения с локальным API"
        except (OSError, ValueError):
            last = "локальный API ещё не готов к ответу"
        if time.monotonic() >= next_message:
            print(f"Ожидаем запуск API: {int(time.monotonic() - started)} с. {last}", flush=True)
            next_message = time.monotonic() + 10
        time.sleep(1)
    raise RuntimeError(f"API не подтвердил готовность за {timeout} с: {last}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=int, required=True)
    parser.add_argument("--user", type=int, required=True)
    parser.add_argument("--number", required=True)
    args = parser.parse_args()
    if os.geteuid() != 0:
        raise RuntimeError("Запусти под root")
    if service_value("ActiveState") != "active":
        raise RuntimeError("Сервис не active")
    project = Path(service_value("WorkingDirectory"))
    core_path = project / "server/backend_app.py"
    if not project.is_absolute() or not core_path.is_file() or core_path.is_symlink():
        raise RuntimeError("Не найден рабочий файл API")
    for folder in (project / ".venv", project / "venv"):
        python = folder / "bin/python"
        if python.is_file():
            if Path(sys.prefix).resolve() != folder.resolve():
                os.execv(str(python), [str(python), str(Path(__file__).resolve()), *sys.argv[1:]])
            break
    pid = service_value("MainPID")
    if not pid.isdigit() or int(pid) < 1:
        raise RuntimeError("Не найден процесс API")
    env = dict(part.split(b"=", 1) for part in Path(f"/proc/{pid}/environ").read_bytes().split(b"\0") if b"=" in part)
    url = env.get(b"DATABASE_URL", b"").decode().strip()
    if not url.startswith(("postgres://", "postgresql://", "postgresql+psycopg://")):
        raise RuntimeError("Не найдена PostgreSQL база активного API")
    token = env.get(b"BOT_TOKEN", b"").decode().strip()
    if not token:
        from dotenv import dotenv_values
        token = str(dotenv_values(project / ".env").get("BOT_TOKEN") or "").strip()
    if not token:
        raise RuntimeError("Не найден токен бота для уведомления")
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            url = url.replace(prefix, "postgresql+psycopg://", 1)
            break
    health()  # Verify the original API before changing files or restarting it.
    before = core_path.read_bytes()
    after = patch_core(before.decode()).encode()
    if after != before:
        backup = project / ".rare-number-backups" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
        backup.mkdir(parents=True, mode=0o700)
        (backup / "backend_app.py").write_bytes(before)
        try:
            replace_atomic(core_path, after)
            subprocess.run(["systemctl", "restart", "nyan-wallet"], check=True)
            health()
        except BaseException as original_error:
            replace_atomic(core_path, before)
            subprocess.run(["systemctl", "restart", "nyan-wallet"], check=False)
            print("Изменение кода отменено. Проверяем запуск прежней версии", flush=True)
            try:
                health()
                print("Прежняя версия API работает", flush=True)
            except Exception:
                print("Прежняя версия пока не подтвердила готовность; нужен журнал systemd", file=sys.stderr)
            raise original_error
        print("Код API обновлён. Копия:", backup)
    else:
        health()
    from sqlalchemy import create_engine
    engine = create_engine(url, pool_pre_ping=True)
    try:
        changed = assign(engine, args.request, args.user, args.number)
        print("Номер установлен, заявка закрыта" if changed else "Номер уже был установлен по этой заявке")
        state = deliver(engine, args.user, args.request, token)
        print("Уведомление в кошельке сохранено. Telegram:", state)
        if state in ("sending", "uncertain"):
            print("Доставку Telegram нужно проверить вручную; повтор сообщения не выполняется")
    finally:
        engine.dispose()


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, ValueError) as error:
        print("ОШИБКА:", error, file=sys.stderr)
        sys.exit(1)
    except Exception as error:
        print(f"Ошибка {type(error).__name__}; повторная выдача защищена", file=sys.stderr)
        sys.exit(1)
