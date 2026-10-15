"""One-time candidate invitation to a private Telegram group.

The private invite URL is supplied from Render environment, never committed
to the source repository or printed to logs. No wallet state/roles are changed.
"""
from __future__ import annotations

import html
import json
import logging
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, Text, select
from sqlalchemy.orm import Mapped, mapped_column

from . import backend_app as core
from .finance_recruitment import FinancialAdminApplication
from .finance_stage2 import FinanceStage2Response

logger = logging.getLogger("nyan_wallet.candidate_invites")
MARK = "[CANDIDATE_GROUP_INVITES_20261015]"
TARGETS = ((2, "nasttchl", "Уважаемая"), (4, "zryvas", "Уважаемый"))


class CandidateGroupInviteDelivery(core.Base):
    __tablename__ = "finance_candidate_group_delivery_20261015"

    application_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("financial_admin_applications.id", ondelete="CASCADE"),
        primary_key=True,
    )
    telegram_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    message_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


def _deliver(telegram_id: int, username: str | None, display_name: str,
             salutation: str, invite_url: str) -> int:
    profile_url = (
        f"https://t.me/{username}"
        if username and re.fullmatch(r"[A-Za-z0-9_]{5,32}", username)
        else f"tg://user?id={telegram_id}"
    )
    name = html.escape(display_name or "кандидат")
    profile_url = html.escape(profile_url, quote=True)
    message_text = (
        f'{salutation} <a href="{profile_url}">{name}</a>!\n\n'
        "Ваша анкета и ответы на второй этап отбора на должность финансового "
        "администратора рассмотрены.\n\n"
        "Приглашаем вас присоединиться к закрытой группе «Кандидаты в администрацию». "
        "Там будут публиковаться дальнейшие инструкции, объявления и информация "
        "о следующих шагах отбора.\n\n"
        "Пожалуйста, нажмите кнопку ниже и вступите в группу. "
        "Просим не передавать ссылку третьим лицам.\n\n"
        "С уважением,\nНяник 🐾"
    )
    payload = {
        "chat_id": str(telegram_id),
        "text": message_text,
        "parse_mode": "HTML",
        "disable_web_page_preview": "true",
        "reply_markup": json.dumps({
            "inline_keyboard": [[{
                "text": "🐾 Вступить в группу кандидатов",
                "url": invite_url,
            }]],
        }, ensure_ascii=False),
    }
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{core.BOT_TOKEN}/sendMessage",
        data=urllib.parse.urlencode(payload).encode("utf-8"),
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=12) as response:
        data = json.loads(response.read().decode("utf-8"))
    if not data.get("ok"):
        raise RuntimeError("Telegram API did not confirm message")
    return int(data["result"]["message_id"])


def send_candidate_group_invites_once() -> None:
    import os

    invite_url = (os.getenv("NYAN_CANDIDATE_GROUP_INVITE_20261015") or "").strip()
    if not invite_url:
        logger.info("%s not_configured", MARK)
        return
    if not re.fullmatch(r"https://t\\.me/\\+[A-Za-z0-9_-]{8,80}", invite_url):
        # Handle the intended regex as a raw-string pattern below, too.
        if not re.fullmatch(r"https://t\.me/\+[A-Za-z0-9_-]{8,80}", invite_url):
            logger.error("%s invalid_invite_url", MARK)
            return
    if not core.BOT_TOKEN:
        logger.error("%s bot_token_missing", MARK)
        return

    CandidateGroupInviteDelivery.__table__.create(bind=core.engine, checkfirst=True)
    for application_id, expected_username, salutation in TARGETS:
        target_id = None
        username = None
        name = None
        with core.SessionLocal() as session:
            with session.begin():
                previous = session.get(CandidateGroupInviteDelivery, application_id)
                if previous is not None:
                    logger.warning("%s application=%s already_recorded status=%s",
                                   MARK, application_id, previous.status)
                    continue

                application = session.get(FinancialAdminApplication, application_id)
                if not application or application.status not in {"pending", "interview", "reserve"}:
                    logger.error("%s application=%s unavailable_or_closed", MARK, application_id)
                    continue
                candidate = session.get(core.User, application.telegram_id)
                test = session.scalar(select(FinanceStage2Response).where(
                    FinanceStage2Response.application_id == application_id
                ))
                if not candidate or not test:
                    logger.error("%s application=%s missing_user_or_stage2", MARK, application_id)
                    continue
                if (candidate.username or "").casefold() != expected_username.casefold():
                    logger.error("%s application=%s username_mismatch", MARK, application_id)
                    continue
                target_id = int(application.telegram_id)
                username = candidate.username
                name = " ".join(
                    x.strip() for x in (candidate.first_name, candidate.last_name)
                    if isinstance(x, str) and x.strip()
                )[:160]
                timestamp = core.now_utc()
                session.add(CandidateGroupInviteDelivery(
                    application_id=application_id,
                    telegram_id=target_id,
                    status="sending",
                    created_at=timestamp,
                    updated_at=timestamp,
                ))

        if target_id is None:
            continue
        status = "failed"
        error = None
        message_id = None
        try:
            message_id = _deliver(target_id, username, name, salutation, invite_url)
            status = "sent"
        except urllib.error.HTTPError as exc:
            status = "failed"
            error = f"Telegram HTTP {exc.code}"
        except Exception as exc:
            status = "failed"
            error = type(exc).__name__

        with core.SessionLocal() as session:
            with session.begin():
                record = session.get(CandidateGroupInviteDelivery, application_id)
                if record:
                    record.status = status
                    record.message_id = message_id
                    record.error = error
                    record.updated_at = core.now_utc()
        logger.warning("%s application=%s status=%s message_id=%s error=%s",
                       MARK, application_id, status, message_id, error)
