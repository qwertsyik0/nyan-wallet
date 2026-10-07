from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import HTMLResponse
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from server import backend_app as core

router = APIRouter()
_REGISTERED = False

LIMITED_PROMOS: dict[str, dict[str, Any]] = {
    "nyan109": {
        "code": "NYAN109",
        "title": "Лимитированный бонус 109 🐾",
        "description": "Разовый бонус Nyan Wallet для первых 10 успешных активаций.",
        "reward_amount": 109,
        "max_uses": 10,
    },
    "nyan200": {
        "code": "NYAN200",
        "title": "Лимитированный бонус 200 🐾",
        "description": "Разовый бонус Nyan Wallet для первых 10 успешных активаций.",
        "reward_amount": 200,
        "max_uses": 10,
    },
}


def _normalize_slug(value: str) -> str:
    slug = str(value or "").strip().lower().replace("_", "-")
    if slug == "promo-nyan109":
        return "nyan109"
    if slug in {"promo-nyan200", "promo-200"}:
        return "nyan200"
    return slug


def _spec(slug: str) -> dict[str, Any]:
    normalized = _normalize_slug(slug)
    data = LIMITED_PROMOS.get(normalized)
    if data is None:
        raise HTTPException(status_code=404, detail="Промо не найдено")
    return {"slug": normalized, **data}


def _status(promo: core.PromoCode | None, timestamp: datetime) -> str:
    if promo is None:
        return "inactive"
    expires_at = core.normalize_datetime(promo.expires_at)
    if promo.max_uses is not None and promo.uses_count >= promo.max_uses:
        return "exhausted"
    if not promo.is_active or (expires_at is not None and expires_at <= timestamp):
        return "inactive"
    return "active"


def _redemption_count(session, promo_id: int) -> int:
    return int(
        session.scalar(
            select(func.count()).select_from(core.PromoRedemption).where(
                core.PromoRedemption.promo_id == promo_id,
            )
        )
        or 0
    )


def _serialize(*, promo: core.PromoCode | None, spec: dict[str, Any], already_used: bool, timestamp: datetime, effective_uses: int | None = None) -> dict[str, Any]:
    max_uses = int(spec["max_uses"])
    uses_count = int(effective_uses if effective_uses is not None else (promo.uses_count if promo else 0))
    uses_count = max(0, uses_count)
    remaining = max(0, max_uses - uses_count)
    status = _status(promo, timestamp)
    if remaining <= 0:
        status = "exhausted"
    return {
        "id": promo.id if promo else None,
        "slug": spec["slug"],
        "code": spec["code"],
        "title": spec["title"],
        "description": spec["description"],
        "reward_amount": int(spec["reward_amount"]),
        "max_uses": max_uses,
        "uses_count": uses_count,
        "remaining": remaining,
        "status": status,
        "already_used": bool(already_used),
        "created_at": promo.created_at.isoformat() if promo else None,
        "expires_at": promo.expires_at.isoformat() if promo and promo.expires_at else None,
    }


def ensure_limited_promos() -> None:
    timestamp = core.now_utc()
    try:
        with core.SessionLocal() as session:
            with session.begin():
                for slug, data in LIMITED_PROMOS.items():
                    code = core.normalize_promo_code(str(data["code"]))
                    if not core.PROMO_PATTERN.fullmatch(code):
                        raise RuntimeError(f"Некорректный код лимитированного промо: {code}")
                    reward_amount = int(data["reward_amount"])
                    max_uses = int(data["max_uses"])
                    if reward_amount <= 0 or max_uses <= 0:
                        raise RuntimeError(f"Некорректные параметры лимитированного промо: {slug}")
                    promo = session.scalar(select(core.PromoCode).where(core.PromoCode.code == code))
                    if promo is None:
                        session.add(core.PromoCode(code=code, reward_amount=reward_amount, max_uses=max_uses, uses_count=0, is_active=True, description=str(data["description"]), created_at=timestamp, expires_at=None))
                        continue
                    real_uses = _redemption_count(session, promo.id)
                    promo.reward_amount = reward_amount
                    promo.max_uses = max_uses
                    promo.uses_count = max(int(promo.uses_count or 0), real_uses)
                    promo.description = str(data["description"])
                    promo.expires_at = None
                    promo.is_active = promo.uses_count < max_uses
    except IntegrityError:
        # Another request may have created the fixed promo at the same time.
        return


@router.get("/api/limited-promos/{slug}")
async def limited_promo_status(slug: str, x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data")):
    tg_user = core.verify_init_data(x_telegram_init_data or "")
    spec = _spec(slug)
    ensure_limited_promos()
    timestamp = core.now_utc()
    with core.SessionLocal() as session:
        promo = session.scalar(select(core.PromoCode).where(core.PromoCode.code == spec["code"]))
        already_used = False
        real_uses = 0
        if promo is not None:
            real_uses = max(int(promo.uses_count or 0), _redemption_count(session, promo.id))
            already_used = session.scalar(select(core.PromoRedemption.id).where(core.PromoRedemption.promo_id == promo.id, core.PromoRedemption.telegram_id == tg_user["id"])) is not None
        return {"ok": True, "promo": _serialize(promo=promo, spec=spec, already_used=already_used, timestamp=timestamp, effective_uses=real_uses)}


@router.post("/api/limited-promos/{slug}/activate")
async def limited_promo_activate(slug: str, x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data")):
    tg_user = core.verify_init_data(x_telegram_init_data or "")
    spec = _spec(slug)
    ensure_limited_promos()
    telegram_id = int(tg_user["id"])
    timestamp = core.now_utc()
    try:
        with core.SessionLocal() as session:
            with session.begin():
                user = session.scalar(select(core.User).where(core.User.telegram_id == telegram_id).with_for_update())
                if user is None:
                    user = core.User(telegram_id=telegram_id, username=tg_user.get("username"), first_name=tg_user.get("first_name") or "Пользователь", last_name=tg_user.get("last_name"), balance=0, created_at=timestamp, last_seen_at=timestamp)
                    session.add(user)
                    session.flush()
                else:
                    core.apply_telegram_profile(user, tg_user, timestamp)
                promo = session.scalar(select(core.PromoCode).where(core.PromoCode.code == spec["code"]).with_for_update())
                if promo is None:
                    raise HTTPException(status_code=404, detail="Промо не найдено")
                real_uses = _redemption_count(session, promo.id)
                if real_uses > promo.uses_count:
                    promo.uses_count = real_uses
                already_used = session.scalar(select(core.PromoRedemption.id).where(core.PromoRedemption.promo_id == promo.id, core.PromoRedemption.telegram_id == telegram_id)) is not None
                if already_used:
                    raise HTTPException(status_code=409, detail="Вы уже активировали это промо")
                max_uses = int(spec["max_uses"])
                if promo.uses_count >= max_uses:
                    promo.is_active = False
                    raise HTTPException(status_code=410, detail="Все активации уже забраны")
                expires_at = core.normalize_datetime(promo.expires_at)
                if not promo.is_active or (expires_at is not None and expires_at <= timestamp):
                    raise HTTPException(status_code=410, detail="Промо больше недоступно")
                reward = int(spec["reward_amount"])
                if reward <= 0:
                    raise HTTPException(status_code=500, detail="Промо настроено некорректно")
                user.balance += reward
                promo.uses_count += 1
                if promo.uses_count >= max_uses:
                    promo.is_active = False
                tx = core.Transaction(telegram_id=telegram_id, amount=reward, operation_type="promo", description=spec["title"], created_at=timestamp)
                session.add(tx)
                session.flush()
                session.add(core.PromoRedemption(promo_id=promo.id, telegram_id=telegram_id, reward_amount=reward, created_at=timestamp))
                result = {"reward": reward, "balance": user.balance, "transaction": core.serialize_transaction(tx), "promo": _serialize(promo=promo, spec=spec, already_used=True, timestamp=timestamp, effective_uses=promo.uses_count)}
        return {"ok": True, **result}
    except IntegrityError as exc:
        raise HTTPException(status_code=409, detail="Вы уже активировали это промо") from exc



@router.get("/promo-50.html", response_class=HTMLResponse)
async def promo_50_page():
    return HTMLResponse(
        """<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
    <title>Nyan Wallet · 50 лапкоинов</title>
    <script src="https://telegram.org/js/telegram-web-app.js"></script>
    <link rel="stylesheet" href="https://qwertsyik0.github.io/nyan-wallet/style.css?v=20260918-8">
    <link rel="stylesheet" href="https://qwertsyik0.github.io/nyan-wallet/promo.css?v=20260921-3">
</head>
<body
    data-default-promo-code="NYAN50"
    data-promo-reward="50"
    data-promo-limit="0"
    data-promo-lock-code="true"
>
<div class="promo-app">
    <main class="promo-shell">
        <section class="promo-hero">
            <div class="promo-paw">🐾</div>
            <div>
                <div class="promo-brand">Nyan Wallet</div>
                <div class="promo-kicker">безлимитный промокод</div>
            </div>
        </section>
        <section class="promo-bonus-card" aria-labelledby="promo-title">
            <div class="promo-badge">без общего лимита</div>
            <div id="promo-title" class="promo-title">50 лапкоинов</div>
            <div class="promo-subtitle">
                Заберите +50 🐾 на баланс Nyan Wallet. Промокод доступен без общего лимита активаций.
            </div>
            <div class="promo-reward-box" aria-hidden="true">
                <div class="promo-reward-amount">50</div>
                <div class="promo-reward-currency">🐾</div>
            </div>
            <div class="promo-facts" aria-label="Условия промокода">
                <div class="promo-fact"><span>лимит</span><strong>без лимита</strong></div>
                <div class="promo-fact"><span>награда</span><strong>+50 🐾</strong></div>
                <div class="promo-fact"><span>активация</span><strong>1 раз на аккаунт</strong></div>
            </div>
            <label class="promo-field">
                <span>Промокод</span>
                <input id="promo-code" type="text" readonly>
            </label>
            <button id="promo-activate" class="promo-activate" type="button" disabled>Подготавливаем…</button>
            <div id="promo-status" class="promo-status" aria-live="polite"></div>
        </section>
        <button id="promo-wallet" class="promo-wallet" type="button">Открыть Nyan Wallet</button>
        <div class="promo-note">без общего лимита · +50 🐾 · один аккаунт может активировать промокод один раз</div>
    </main>
</div>
<script src="https://qwertsyik0.github.io/nyan-wallet/promo.js?v=20261007-2"></script>
</body>
</html>"""
    )


def register_limited_promos(app) -> None:
    global _REGISTERED
    if _REGISTERED:
        return
    app.include_router(router)
    _REGISTERED = True
