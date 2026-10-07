from __future__ import annotations

import json
import logging
import urllib.parse
import urllib.request

from sqlalchemy import select

from . import backend_app as core
from .user_bans import BlockedUser

logger = logging.getLogger("nyan_wallet.manual_multiaccount_enforcement_20261007")

MAIN_ID = 6258280739
DROP_IDS = (8608441519, 5656037848)
DEBIT_AMOUNT = 287
DESCRIPTION = (
    "Списание 287 🐾 за нарушение правил Nyan Wallet: использование связанных аккаунтов "
    "для фарма лапкоинов, реферальных наград и последующего перевода средств на основной аккаунт."
)
DROP_REASON = (
    "Мультиаккаунт / фарм лапкоинов. Использование связанного аккаунта для получения наград "
    "с последующим переводом средств на основной аккаунт."
)
TELEGRAM_TEXT = """⚠️ Нарушение правил Nyan Wallet

В ходе проверки активности вашего кошелька была выявлена сеть связанных аккаунтов, использовавшихся для получения дополнительных лапкоинов и последующего перевода средств на ваш основной аккаунт.

Проверкой зафиксированы:
— использование вашей реферальной ссылки связанными аккаунтами;
— получение ими наград и бонусов;
— последующий перевод лапкоинов на ваш кошелёк;
— технические совпадения и последовательная активность аккаунтов, подтверждающие их связь.

С вашего баланса списано 287 🐾 — сумма, полученная через выявленную схему, включая переводы и реферальные начисления.

Ваш основной аккаунт не заблокирован. Связанные аккаунты, использовавшиеся для фарма, заблокированы в Nyan Wallet.

Повторное использование дополнительных аккаунтов для получения промокодов, реферальных наград, ежедневных бонусов или иных преимуществ может привести к блокировке основного аккаунта.

Если вы считаете решение ошибочным, вы можете обратиться в поддержку и предоставить объяснение ситуации."""


def _send_telegram(chat_id: int, text: str) -> bool:
    if not core.BOT_TOKEN:
        logger.error("MULTIACCOUNT_ENFORCEMENT telegram_skipped reason=missing_bot_token")
        return False
    try:
        url = f"https://api.telegram.org/bot{core.BOT_TOKEN}/sendMessage"
        payload = urllib.parse.urlencode({"chat_id": str(chat_id), "text": text}).encode("utf-8")
        request = urllib.request.Request(url, data=payload, method="POST")
        with urllib.request.urlopen(request, timeout=8) as response:
            raw = response.read().decode("utf-8", errors="replace")
        ok = bool(json.loads(raw).get("ok"))
        logger.warning("MULTIACCOUNT_ENFORCEMENT telegram_sent=%s chat_id=%s", ok, chat_id)
        return ok
    except Exception:
        logger.exception("MULTIACCOUNT_ENFORCEMENT telegram_send_failed chat_id=%s", chat_id)
        return False


def apply_multiaccount_enforcement_20261007() -> None:
    newly_applied = False
    final_balance: int | None = None

    with core.SessionLocal() as session:
        with session.begin():
            main = session.scalar(
                select(core.User)
                .where(core.User.telegram_id == MAIN_ID)
                .with_for_update()
            )
            if main is None:
                logger.error("MULTIACCOUNT_ENFORCEMENT main_missing telegram_id=%s", MAIN_ID)
                return

            existing = session.scalar(
                select(core.Transaction.id).where(
                    core.Transaction.telegram_id == MAIN_ID,
                    core.Transaction.operation_type == "owner_debit",
                    core.Transaction.description == DESCRIPTION,
                )
            )

            if existing is None:
                if int(main.balance) < DEBIT_AMOUNT:
                    logger.error(
                        "MULTIACCOUNT_ENFORCEMENT insufficient_balance telegram_id=%s balance=%s required=%s",
                        MAIN_ID,
                        main.balance,
                        DEBIT_AMOUNT,
                    )
                    return

                main.balance -= DEBIT_AMOUNT
                session.add(
                    core.Transaction(
                        telegram_id=MAIN_ID,
                        amount=-DEBIT_AMOUNT,
                        operation_type="owner_debit",
                        description=DESCRIPTION,
                        created_at=core.now_utc(),
                    )
                )
                newly_applied = True

            timestamp = core.now_utc()
            for drop_id in DROP_IDS:
                drop = session.get(core.User, drop_id)
                if drop is None:
                    logger.error("MULTIACCOUNT_ENFORCEMENT drop_missing telegram_id=%s", drop_id)
                    continue
                ban = session.get(BlockedUser, drop_id)
                if ban is None:
                    session.add(
                        BlockedUser(
                            telegram_id=drop_id,
                            reason=DROP_REASON,
                            blocked_at=timestamp,
                        )
                    )
                else:
                    ban.reason = DROP_REASON
                    if newly_applied:
                        ban.blocked_at = timestamp

            session.flush()
            final_balance = int(main.balance)

    logger.warning(
        "MULTIACCOUNT_ENFORCEMENT applied=%s main_id=%s debit=%s final_balance=%s drops=%s",
        newly_applied,
        MAIN_ID,
        DEBIT_AMOUNT if newly_applied else 0,
        final_balance,
        ",".join(str(x) for x in DROP_IDS),
    )

    if newly_applied:
        _send_telegram(MAIN_ID, TELEGRAM_TEXT)
