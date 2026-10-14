"""Temporary, one-run user-approved candidate invite; remove after delivery verification."""
import json
import logging
import urllib.error
import urllib.parse
import urllib.request

from sqlalchemy import select

from . import backend_app as core
from .finance_recruitment import FinancialAdminApplication

log = logging.getLogger("nyan.wallet.finance.stage2.invite")
MARKER = "[FIN_STAGE2_INVITE_20261014]"


def deliver_invite():
    try:
        with core.SessionLocal() as session:
            candidate = session.scalar(select(FinancialAdminApplication).where(
                FinancialAdminApplication.id == 2,
                FinancialAdminApplication.telegram_id == 1129986805,
            ))
            if not candidate or candidate.status not in {"pending", "interview"}:
                log.warning("%s NOT_SENT application state disallows invitation", MARKER)
                return

        payload = {
            "chat_id": "1129986805",
            "text": (
                "🐾 Nyan Wallet | Второй этап отбора\n\n"
                "настя, мы рассмотрели твою анкету на должность финансового администратора "
                "и приглашаем пройти дополнительное тестирование.\n\n"
                "тебя ждут 7 вопросов по расчётам, безопасности и работе с пользователями. "
                "пожалуйста, отвечай внимательно и своими словами.\n\n"
                "нажми кнопку ниже, чтобы начать."
            ),
            "reply_markup": json.dumps({
                "inline_keyboard": [[{
                    "text": "🐾 Пройти второй этап",
                    "web_app": {"url": "https://qwertsyik0.github.io/nyan-wallet/finance-stage2.html"},
                }]]
            }, ensure_ascii=False),
        }
        request = urllib.request.Request(
            f"https://api.telegram.org/bot{core.BOT_TOKEN}/sendMessage",
            data=urllib.parse.urlencode(payload).encode("utf-8"),
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=8) as response:
            body = json.loads(response.read().decode("utf-8"))
        if body.get("ok") is True:
            log.warning("%s DELIVERED message_id=%s", MARKER, body.get("result", {}).get("message_id"))
        else:
            log.warning("%s FAILED Telegram rejected request", MARKER)
    except urllib.error.HTTPError as exc:
        try:
            description = json.loads(exc.read().decode("utf-8")).get("description", "Telegram API error")
        except Exception:
            description = "Telegram API error"
        log.warning("%s FAILED status=%s detail=%s", MARKER, exc.code, str(description)[:150])
    except Exception as exc:
        log.warning("%s FAILED reason=%s", MARKER, type(exc).__name__)
