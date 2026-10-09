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



@router.get("/promo-400.html", response_class=HTMLResponse)
async def promo_400_teaser_page():
    return HTMLResponse(
        """<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0,viewport-fit=cover">
<title>Nyan Wallet · 400?</title>
<script src="https://telegram.org/js/telegram-web-app.js"></script>
<style>
:root{color-scheme:dark;font-family:Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
*{box-sizing:border-box}html,body{margin:0;min-height:100%;background:#070609;color:#fff}
body{min-height:100vh;min-height:100dvh;overflow:hidden;background:radial-gradient(circle at 50% 28%,rgba(194,48,109,.22),transparent 28%),radial-gradient(circle at 20% 75%,rgba(117,39,102,.16),transparent 30%),linear-gradient(180deg,#110a10 0%,#08070a 100%)}
.wrap{min-height:100vh;min-height:100dvh;display:grid;place-items:center;padding:max(24px,env(safe-area-inset-top)) 18px max(24px,env(safe-area-inset-bottom))}
.card{width:min(100%,430px);padding:30px 22px 22px;border:1px solid rgba(255,117,173,.16);border-radius:30px;background:rgba(20,12,18,.86);box-shadow:0 28px 80px rgba(0,0,0,.42);backdrop-filter:blur(22px);text-align:center}
.eyebrow{color:#c9789b;font-size:11px;font-weight:800;letter-spacing:.16em;text-transform:uppercase}
.orb{display:inline-flex;align-items:flex-end;gap:7px;margin-top:26px;color:#ffd7e8;font-size:clamp(62px,19vw,92px);line-height:.85;font-weight:950;letter-spacing:-.07em;text-shadow:0 0 28px rgba(231,79,145,.22)}
.orb span{padding-bottom:7px;font-size:30px}h1{margin:22px 0 0;font-size:clamp(27px,8vw,38px);line-height:1.02;letter-spacing:-.04em}
.lead{margin:12px auto 0;max-width:310px;color:#b99cab;font-size:14px;line-height:1.55}
.codebox{display:grid;gap:7px;margin-top:27px;text-align:left}.codebox span{color:#9c7d8c;font-size:11px;font-weight:700}
.codebox input{width:100%;min-height:54px;padding:0 16px;border:1px solid rgba(255,255,255,.08);border-radius:17px;outline:none;background:rgba(255,255,255,.035);color:#f8eaf0;font:inherit;font-size:16px;font-weight:850;letter-spacing:.08em}
button{width:100%;min-height:55px;margin-top:14px;border:0;border-radius:18px;background:linear-gradient(135deg,#df4b8b,#9d315f);color:white;font:inherit;font-weight:900;cursor:pointer;box-shadow:0 14px 36px rgba(201,59,120,.19)}
button:disabled{opacity:.58;cursor:default}.status{min-height:18px;margin:12px 0 0;color:#b99cab;font-size:12px;line-height:1.4}.status.error{color:#e49aa4}.small{margin:14px 0 0;color:#6f5964;font-size:11px}
.secret{display:none}.secret .signal{width:64px;height:64px;margin:0 auto 26px;border:1px solid rgba(255,255,255,.11);border-radius:50%;display:grid;place-items:center;color:#d95890;font-size:26px;box-shadow:0 0 40px rgba(217,88,144,.12)}
.secret .reward{display:inline-flex;gap:7px;align-items:center;margin-top:27px;padding:11px 16px;border:1px solid rgba(217,88,144,.16);border-radius:999px;background:rgba(217,88,144,.06);color:#e9c6d5;font-size:13px;font-weight:800}
.secret p{margin:15px auto 0;max-width:340px;color:#b49aa7;font-size:15px;line-height:1.62}.hint{margin-top:34px!important;color:#6e5963!important;font-size:12px!important}
</style>
</head>
<body>
<main class="wrap">
<section class="card" id="promo">
<div class="eyebrow">секретный промокод</div>
<div class="orb">400<span>🐾</span></div>
<h1>забрать 400 лапкоинов?</h1>
<p class="lead">нажми «активировать». дальше всё станет чуть страннее.</p>
<label class="codebox"><span>промокод</span><input value="NYAN400" readonly></label>
<button id="activate" disabled>подготавливаем…</button>
<p id="status" class="status"></p>
<p class="small">1 раз на аккаунт</p>
</section>
<section class="card secret" id="secret">
<div class="signal">?</div>
<div class="eyebrow">соединение установлено</div>
<h1>а ты готов раскрыть тайну и получить больше?</h1>
<p>это была только первая часть. следи за событиями в Nyan Wallet. скоро появится то, что изменит значение цифры <strong>400</strong>.</p>
<div class="reward" id="reward">+50 🐾 уже на балансе</div>
<p class="hint">не закрывай для себя эту историю слишком рано.</p>
</section>
</main>
<script>
(()=>{"use strict";
const tg=window.Telegram?.WebApp,API="https://nyan-wallet-api.onrender.com",btn=document.getElementById("activate"),status=document.getElementById("status"),promo=document.getElementById("promo"),secret=document.getElementById("secret"),reward=document.getElementById("reward");
let busy=false;tg?.ready?.();tg?.expand?.();
function showSecret(used=false){promo.style.display="none";secret.style.display="block";if(used)reward.textContent="этот сигнал вы уже получали";tg?.MainButton?.hide?.();}
function setStatus(t,e=false){status.textContent=t||"";status.className="status"+(e?" error":"");}
function ready(){if(!tg?.initData){btn.disabled=true;btn.textContent="откройте через Telegram";setStatus("эта страница работает только внутри Telegram.",true);return}btn.disabled=false;btn.textContent="активировать";tg?.MainButton?.setText?.("АКТИВИРОВАТЬ");tg?.MainButton?.enable?.();tg?.MainButton?.show?.();}
async function activate(){if(busy||!tg?.initData)return;busy=true;btn.disabled=true;btn.textContent="активируем…";tg?.MainButton?.disable?.();tg?.MainButton?.showProgress?.();setStatus("");
try{const r=await fetch(API+"/api/promo/redeem",{method:"POST",headers:{"Content-Type":"application/json","X-Telegram-Init-Data":tg.initData},body:JSON.stringify({code:"NYAN400"})});let d={};try{d=await r.json()}catch(_){}
if(!r.ok){if(r.status===409){showSecret(true);return}throw new Error(d?.detail||"не удалось активировать промокод")}
tg?.HapticFeedback?.notificationOccurred?.("success");showSecret(false);
}catch(e){btn.disabled=false;btn.textContent="повторить";tg?.MainButton?.enable?.();setStatus(e?.message||"что-то пошло не так.",true);tg?.HapticFeedback?.notificationOccurred?.("error")}
finally{busy=false;tg?.MainButton?.hideProgress?.()}}
btn.addEventListener("click",activate);tg?.MainButton?.onClick?.(activate);ready();
})();
</script>
</body>
</html>"""
    )

def register_limited_promos(app) -> None:
    global _REGISTERED
    if _REGISTERED:
        return
    app.include_router(router)
    _REGISTERED = True
