from __future__ import annotations

import asyncio
import csv
import hmac
import io
import json
import os
import threading
import time
import urllib.request
import uuid
import zipfile
from collections import defaultdict, deque
from datetime import date, datetime, timezone
from typing import Any

from fastapi import Header, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import Date, DateTime, String, Text, select
from sqlalchemy.orm import Mapped, mapped_column

from . import backend_app as core


class BackupRun(core.Base):
    __tablename__ = "backup_runs"

    backup_date: Mapped[date] = mapped_column(Date, primary_key=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    attempted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class SlidingWindowLimiter:
    def __init__(self) -> None:
        self._items: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str, limit: int, window_seconds: int) -> tuple[bool, int]:
        now = time.monotonic()
        cutoff = now - window_seconds
        with self._lock:
            bucket = self._items[key]
            while bucket and bucket[0] <= cutoff:
                bucket.popleft()
            if len(bucket) >= limit:
                retry_after = max(1, int(window_seconds - (now - bucket[0])) + 1)
                return False, retry_after
            bucket.append(now)
            return True, 0


_limiter = SlidingWindowLimiter()
_backup_lock = threading.Lock()
_backup_task: asyncio.Task | None = None
_REGISTERED = False


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "").split(",", 1)[0].strip()
    if forwarded:
        return forwarded[:80]
    if request.client and request.client.host:
        return request.client.host[:80]
    return "unknown"


def _specific_rule(path: str) -> tuple[str, int, int] | None:
    if path in {"/api/promo/redeem", "/api/promo/redeem-notify"}:
        return "promo", 6, 60
    if path == "/api/referrals/apply":
        return "referral", 5, 300
    if path.startswith("/api/rewards/") and path.endswith("/request"):
        return "reward", 8, 60
    if path.startswith("/api/giveaways/") and path.endswith("/tickets/purchase"):
        return "giveaway-purchase", 15, 60
    if path.startswith("/api/giveaways/") and path.endswith("/join"):
        return "giveaway-join", 20, 60
    if path == "/api/notifications/read-all":
        return "notifications", 30, 60
    if path == "/api/appeals":
        return "appeal-create", 4, 300
    if path.startswith("/api/appeals/") and path.endswith("/messages"):
        return "appeal-message", 12, 60
    if path.startswith("/api/owner/"):
        return "owner", 120, 60
    return None


def _rate_limit_response(retry_after: int) -> JSONResponse:
    return JSONResponse(
        status_code=429,
        content={"detail": "Слишком много запросов. Попробуйте чуть позже."},
        headers={"Retry-After": str(retry_after)},
    )


async def rate_limit_middleware(request: Request, call_next):
    if request.method != "POST" or not request.url.path.startswith("/api/"):
        return await call_next(request)

    ip = _client_ip(request)
    allowed, retry_after = _limiter.allow(f"global-ip:{ip}", 100, 60)
    if not allowed:
        return _rate_limit_response(retry_after)

    init_data = request.headers.get("x-telegram-init-data", "")
    telegram_id: int | None = None
    if init_data:
        try:
            telegram_id = int(core.verify_init_data(init_data)["id"])
        except Exception:
            telegram_id = None

    if telegram_id is not None:
        allowed, retry_after = _limiter.allow(f"global-user:{telegram_id}", 80, 60)
        if not allowed:
            return _rate_limit_response(retry_after)

    rule = _specific_rule(request.url.path)
    if rule:
        name, limit, window = rule
        subject = f"user:{telegram_id}" if telegram_id is not None else f"ip:{ip}"
        allowed, retry_after = _limiter.allow(f"{name}:{subject}", limit, window)
        if not allowed:
            return _rate_limit_response(retry_after)

    return await call_next(request)


def _serialize_cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, bytes):
        return value.hex()
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def _table_csv(table) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    columns = list(table.columns)
    writer.writerow([column.name for column in columns])

    stmt = select(table)
    pk_columns = list(table.primary_key.columns)
    if pk_columns:
        stmt = stmt.order_by(*pk_columns)

    with core.engine.connect() as connection:
        for row in connection.execute(stmt).mappings():
            writer.writerow([_serialize_cell(row[column.name]) for column in columns])

    return output.getvalue().encode("utf-8-sig")


def build_backup_zip() -> bytes:
    output = io.BytesIO()
    created_at = datetime.now(timezone.utc)
    tables = [table for table in core.Base.metadata.sorted_tables]

    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        manifest = [
            "Nyan Wallet automatic backup",
            f"created_at_utc={created_at.isoformat()}",
            "database=postgresql",
            f"tables={len(tables)}",
        ]
        archive.writestr("manifest.txt", "\n".join(manifest).encode("utf-8"))
        for table in tables:
            archive.writestr(f"tables/{table.name}.csv", _table_csv(table))

    return output.getvalue()


def _multipart_field(name: str, value: str, boundary: str) -> bytes:
    return (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="{name}"\r\n\r\n'
        f"{value}\r\n"
    ).encode("utf-8")


def send_backup_document(data: bytes, filename: str) -> None:
    if not core.BOT_TOKEN or not core.OWNER_TELEGRAM_ID:
        raise RuntimeError("BOT_TOKEN или OWNER_TELEGRAM_ID отсутствует")

    if len(data) > 45 * 1024 * 1024:
        raise RuntimeError("Автоматическая резервная копия превышает 45 МБ")

    boundary = f"----NyanWallet{uuid.uuid4().hex}"
    body = io.BytesIO()
    body.write(_multipart_field("chat_id", str(core.OWNER_TELEGRAM_ID), boundary))
    body.write(_multipart_field("caption", "Ежедневная резервная копия Nyan Wallet", boundary))
    body.write(f"--{boundary}\r\n".encode("utf-8"))
    body.write(
        (
            f'Content-Disposition: form-data; name="document"; filename="{filename}"\r\n'
            "Content-Type: application/zip\r\n\r\n"
        ).encode("utf-8")
    )
    body.write(data)
    body.write(b"\r\n")
    body.write(f"--{boundary}--\r\n".encode("utf-8"))

    request = urllib.request.Request(
        f"https://api.telegram.org/bot{core.BOT_TOKEN}/sendDocument",
        data=body.getvalue(),
        method="POST",
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    with urllib.request.urlopen(request, timeout=90) as response:
        payload = json.loads(response.read().decode("utf-8"))
        if not payload.get("ok"):
            raise RuntimeError("Telegram не подтвердил отправку резервной копии")


def run_daily_backup_if_needed() -> None:
    if not _backup_lock.acquire(blocking=False):
        return
    try:
        today = datetime.now(timezone.utc).date()
        with core.SessionLocal() as session:
            existing = session.get(BackupRun, today)
            if existing and existing.status == "sent":
                return

        attempted_at = datetime.now(timezone.utc)
        try:
            data = build_backup_zip()
            filename = f"nyan-wallet-backup-{today.isoformat()}.zip"
            send_backup_document(data, filename)
        except Exception as exc:
            with core.SessionLocal() as session:
                row = session.get(BackupRun, today)
                if row is None:
                    row = BackupRun(
                        backup_date=today,
                        status="failed",
                        attempted_at=attempted_at,
                        sent_at=None,
                        error=str(exc)[:2000],
                    )
                    session.add(row)
                else:
                    row.status = "failed"
                    row.attempted_at = attempted_at
                    row.error = str(exc)[:2000]
                session.commit()
            print(f"Nyan Wallet backup failed: {exc}")
            return

        with core.SessionLocal() as session:
            row = session.get(BackupRun, today)
            sent_at = datetime.now(timezone.utc)
            if row is None:
                row = BackupRun(
                    backup_date=today,
                    status="sent",
                    attempted_at=attempted_at,
                    sent_at=sent_at,
                    error=None,
                )
                session.add(row)
            else:
                row.status = "sent"
                row.attempted_at = attempted_at
                row.sent_at = sent_at
                row.error = None
            session.commit()
    finally:
        _backup_lock.release()


async def _backup_loop() -> None:
    while True:
        await asyncio.to_thread(run_daily_backup_if_needed)
        await asyncio.sleep(60 * 60)


async def _start_backup_loop() -> None:
    global _backup_task
    if _backup_task is None or _backup_task.done():
        _backup_task = asyncio.create_task(_backup_loop(), name="nyan-wallet-daily-backup")


async def backup_cron_trigger(
    x_backup_secret: str | None = Header(default=None, alias="X-Backup-Secret"),
):
    expected = os.getenv("BACKUP_CRON_SECRET", "")
    supplied = x_backup_secret or ""
    if not expected or not hmac.compare_digest(supplied, expected):
        raise HTTPException(status_code=404, detail="Not found")
    await asyncio.to_thread(run_daily_backup_if_needed)
    return {"ok": True}


def register_release_hardening(app) -> None:
    global _REGISTERED
    if _REGISTERED:
        return
    core.Base.metadata.create_all(core.engine)
    app.middleware("http")(rate_limit_middleware)
    app.add_api_route(
        "/internal/backup/run",
        backup_cron_trigger,
        methods=["POST"],
        include_in_schema=False,
    )
    app.add_event_handler("startup", _start_backup_loop)
    _REGISTERED = True
