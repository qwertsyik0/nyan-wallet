from fastapi import APIRouter, BackgroundTasks, Header

from server import backend_app as core
from server.extended_features import send_telegram_message

router = APIRouter()


@router.post("/api/promo/redeem-notify")
async def promo_redeem_notify(
    payload: core.PromoRedeemRequest,
    background_tasks: BackgroundTasks,
    x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data"),
):
    tg_user = core.verify_init_data(x_telegram_init_data or "")
    result = core.redeem_promo(tg_user, payload.code)
    code = payload.code.strip().upper()

    background_tasks.add_task(
        send_telegram_message,
        tg_user["id"],
        f"Промокод {code} активирован.\nНачислено +{result['reward']} 🐾.\nБаланс: {result['balance']} 🐾",
    )

    username = tg_user.get("username")
    first_name = tg_user.get("first_name") or "Пользователь"
    user_label = f"@{username}" if username else first_name
    background_tasks.add_task(
        send_telegram_message,
        core.OWNER_TELEGRAM_ID,
        (
            "🐾 Nyan Wallet\n"
            "Активирован промокод\n"
            f"Пользователь: {user_label}\n"
            f"Telegram ID: {tg_user['id']}\n"
            f"Промокод: {code}\n"
            f"Начислено: +{result['reward']} 🐾\n"
            f"Баланс: {result['balance']} 🐾"
        ),
    )

    return {"ok": True, **result}


def register_promo_notify(app) -> None:
    app.include_router(router)
