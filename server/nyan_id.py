"""Read-only authenticated Nyan ID cards based on existing wallet data.

The public-facing card number is a non-authorizing, stable pseudonymous label.
It never grants access to wallet functions and deliberately omits balances,
raw Telegram IDs, transaction history and referral codes.
"""
from __future__ import annotations

import hashlib
import json
import logging
import secrets
import struct
import threading
import time
import urllib.error
import urllib.request
import zlib
import asyncio

from fastapi import APIRouter, Header, HTTPException, Request
from sqlalchemy import func, select

from . import backend_app as core
from .advanced_features import level_data, settings
from .achievements import (
    ACHIEVEMENT_BY_KEY,
    AchievementBadge,
    AchievementUnlock,
)

router = APIRouter()
_REGISTERED = False
_LOG = logging.getLogger("nyan_wallet.nyan_id")
_MAX_PNG_BYTES = 3 * 1024 * 1024
_SEND_COOLDOWN_SECONDS = 45
_send_attempts: dict[int, float] = {}
_send_attempts_lock = threading.Lock()


def make_nyan_id(telegram_id: int) -> str:
    """Stable public label; not an authentication token or proof of identity."""
    digest = hashlib.blake2s(
        f"nyan-id:v1:{int(telegram_id)}".encode("ascii"),
        digest_size=8,
    ).hexdigest().upper()
    return f"NW-{digest[:4]}-{digest[4:8]}-{digest[8:12]}-{digest[12:]}"


@router.get("/api/nyan-id")
async def nyan_id(
    x_telegram_init_data: str | None = Header(
        default=None, alias="X-Telegram-Init-Data"
    ),
):
    telegram = core.verify_init_data(x_telegram_init_data or "")
    core.get_or_create_user(telegram)
    with core.SessionLocal() as session:
        user = session.get(core.User, telegram["id"])
        if user is None:
            raise HTTPException(status_code=404, detail="Кошелёк не найден")

        earned = session.scalar(
            select(func.coalesce(func.sum(core.Transaction.amount), 0)).where(
                core.Transaction.telegram_id == user.telegram_id,
                core.Transaction.amount > 0,
                ~core.Transaction.operation_type.in_((
                    "reward_refund",
                    "giveaway_refund",
                    "giveaway_manual_refund",
                )),
            )
        ) or 0

        level = level_data(int(earned), settings(session))
        unlocked = session.scalars(
            select(AchievementUnlock)
            .where(AchievementUnlock.telegram_id == user.telegram_id)
            .order_by(AchievementUnlock.unlocked_at.desc())
        ).all()
        unlocked_keys = {row.achievement_key for row in unlocked}
        badge_row = session.get(AchievementBadge, user.telegram_id)
        badge_source = (
            ACHIEVEMENT_BY_KEY.get(badge_row.achievement_key)
            if badge_row and badge_row.achievement_key in unlocked_keys
            else None
        )

        titles = [
            ACHIEVEMENT_BY_KEY[row.achievement_key]["title"]
            for row in unlocked
            if row.achievement_key in ACHIEVEMENT_BY_KEY
        ][:3]
        display_name = " ".join(
            part.strip() for part in (user.first_name, user.last_name)
            if part and part.strip()
        )[:96] or "Пользователь"
        username = user.username if user.username and user.username.isascii() else None

        return {
            "ok": True,
            "number": make_nyan_id(user.telegram_id),
            "display_name": display_name,
            "username": username,
            "member_since": user.created_at.isoformat(),
            "rank": "Владелец" if core.is_owner(user.telegram_id) else level["name"],
            "owner": bool(core.is_owner(user.telegram_id)),
            "achievement_count": len(unlocked),
            "recent_achievements": titles,
            "badge": (
                {"title": badge_source["title"], "rarity": badge_source["rarity"]}
                if badge_source else None
            ),
        }

def _validate_exported_png(data: bytes) -> None:
    """Validate canvas PNG structure, dimensions and checksums; bound memory usage."""
    if len(data) < 70 or len(data) > _MAX_PNG_BYTES:
        raise HTTPException(status_code=413, detail="Размер PNG должен быть не больше 3 МБ")
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise HTTPException(status_code=415, detail="Нужен PNG-файл карточки")

    offset = 8
    chunks = 0
    idat_seen = False
    iend_seen = False
    while offset + 12 <= len(data):
        length = struct.unpack_from(">I", data, offset)[0]
        if length > _MAX_PNG_BYTES or offset + 12 + length > len(data):
            break
        chunk_type = data[offset + 4:offset + 8]
        chunk_data = data[offset + 8:offset + 8 + length]
        recorded_crc = struct.unpack_from(">I", data, offset + 8 + length)[0]
        calculated_crc = zlib.crc32(chunk_type + chunk_data) & 0xFFFFFFFF
        if calculated_crc != recorded_crc:
            break
        chunks += 1
        if chunks == 1:
            if chunk_type != b"IHDR" or length != 13:
                break
            width, height, bitdepth, color_type, compression, filtering, interlace = struct.unpack(
                ">IIBBBBB", chunk_data
            )
            if (
                (width, height) != (1200, 780)
                or bitdepth != 8
                or color_type not in (2, 6)
                or compression != 0
                or filtering != 0
                or interlace != 0
            ):
                break
        if chunk_type == b"IDAT":
            idat_seen = True
        if chunk_type == b"IEND":
            iend_seen = length == 0 and idat_seen and offset + 12 == len(data)
            break
        offset += 12 + length
    if not iend_seen:
        raise HTTPException(status_code=415, detail="PNG повреждён или имеет неверный формат")


async def _read_export_png(request: Request) -> bytes:
    content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if content_type != "image/png":
        raise HTTPException(status_code=415, detail="Ожидается изображение PNG")
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            size = int(content_length)
        except ValueError:
            raise HTTPException(status_code=400, detail="Некорректный размер файла")
        if size < 1 or size > _MAX_PNG_BYTES:
            raise HTTPException(status_code=413, detail="Файл слишком большой")

    parts = []
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > _MAX_PNG_BYTES:
            raise HTTPException(status_code=413, detail="PNG превышает 3 МБ")
        parts.append(chunk)
    data = b"".join(parts)
    _validate_exported_png(data)
    return data


def _telegram_send_png(chat_id: int, number: str, data: bytes) -> int:
    """Deliver a downloadable image/png document, not a compressed Telegram photo."""
    boundary = "NyanID-" + secrets.token_hex(16)
    prefix = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="chat_id"\r\n\r\n'
        f"{chat_id}\r\n"
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="caption"\r\n\r\n'
        "🐾 Твой Nyan ID готов!\n"
        "Карточка приложена как PNG-файл в оригинальном качестве. "
        "Открой документ и сохрани на устройство.\n"
        "Это карточка участника, не документ для подтверждения личности.\r\n"
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="document"; '
        f'filename="Nyan-ID-{number}.png"\r\n'
        "Content-Type: image/png\r\n\r\n"
    ).encode("utf-8")
    body = prefix + data + f"\r\n--{boundary}--\r\n".encode("ascii")
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{core.BOT_TOKEN}/sendDocument",
        data=body,
        headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "User-Agent": "NyanWallet-ID/1.0",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=18) as response:
        result = json.loads(response.read(65536).decode("utf-8"))
    if not result.get("ok") or not isinstance(result.get("result"), dict):
        raise RuntimeError("Telegram did not confirm document delivery")
    return int(result["result"]["message_id"])


def _reserve_delivery(telegram_id: int) -> float:
    now = time.monotonic()
    with _send_attempts_lock:
        previous = _send_attempts.get(telegram_id)
        if previous is not None and now - previous < _SEND_COOLDOWN_SECONDS:
            seconds = max(1, round(_SEND_COOLDOWN_SECONDS - (now - previous)))
            raise HTTPException(
                status_code=429,
                detail=f"Подождите {seconds} сек. перед повторной отправкой",
            )
        _send_attempts[telegram_id] = now
        if len(_send_attempts) > 2000:
            expired = [uid for uid, t in _send_attempts.items() if now - t > 180]
            for uid in expired:
                _send_attempts.pop(uid, None)
    return now


def _release_failed_delivery(telegram_id: int, reservation: float) -> None:
    with _send_attempts_lock:
        if _send_attempts.get(telegram_id) == reservation:
            _send_attempts.pop(telegram_id, None)


@router.post("/api/nyan-id/send-png")
async def send_nyan_id_png(
    request: Request,
    x_telegram_init_data: str | None = Header(
        default=None, alias="X-Telegram-Init-Data"
    ),
):
    """Send only to the authenticated user's own Telegram chat."""
    telegram = core.verify_init_data(x_telegram_init_data or "")
    if not core.BOT_TOKEN:
        raise HTTPException(status_code=503, detail="Отправка файлов временно недоступна")
    user_id = int(telegram["id"])
    with core.SessionLocal() as session:
        if session.get(core.User, user_id) is None:
            raise HTTPException(status_code=404, detail="Сначала откройте кошелёк")
    png = await _read_export_png(request)
    reservation = _reserve_delivery(user_id)
    try:
        message_id = await asyncio.to_thread(
            _telegram_send_png, user_id, make_nyan_id(user_id), png
        )
    except urllib.error.HTTPError as exc:
        _release_failed_delivery(user_id, reservation)
        if exc.code in (400, 403):
            raise HTTPException(
                status_code=409,
                detail=(
                    "Бот не может написать вам первым. "
                    "Откройте @nyancash_bot, нажмите «Старт», затем повторите отправку."
                ),
            ) from None
        if exc.code == 429:
            raise HTTPException(status_code=503, detail="Telegram временно ограничил отправку. Повторите через минуту.") from None
        _LOG.warning("Nyan ID Telegram document error: HTTP %d", exc.code)
        raise HTTPException(status_code=502, detail="Ошибка отправки Telegram. Попробуйте позже.") from None
    except (urllib.error.URLError, TimeoutError, OSError, ValueError, RuntimeError):
        _release_failed_delivery(user_id, reservation)
        _LOG.warning("Nyan ID document delivery did not complete", exc_info=True)
        raise HTTPException(status_code=502, detail="Не удалось отправить PNG. Повторите попытку.") from None

    _LOG.info("Nyan ID PNG document sent: message_id=%d", message_id)
    return {"ok": True, "sent": True, "message_id": message_id}




def register_nyan_id(app) -> None:
    global _REGISTERED
    if _REGISTERED:
        return
    app.include_router(router)
    _REGISTERED = True
