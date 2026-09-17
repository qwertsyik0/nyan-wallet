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
    background_tasks.add_task(
        send_telegram_message,
        tg_user["id"],
        f"Промокод {payload.code.strip().upper()} активирован.\nНачислено +{result['reward']} 🐾.\nБаланс: {result['balance']} 🐾",
    )
    return {"ok": True, **result}


def register_promo_notify(app) -> None:
    app.include_router(router)
