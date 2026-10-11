from __future__ import annotations

import html
import json
import urllib.parse
import urllib.request

from sqlalchemy import BigInteger, DateTime, Integer, String, UniqueConstraint, select
from sqlalchemy.orm import Mapped, mapped_column

from . import backend_app as core
from .wallet_survey import SURVEY_KEY, WalletSurveyResponse


class SurveyChannelFollowup(core.Base):
    __tablename__ = "survey_channel_followups"
    __table_args__ = (
        UniqueConstraint("survey_key", "telegram_id", name="uq_survey_channel_followup"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    survey_key: Mapped[str] = mapped_column(String(64), nullable=False)
    telegram_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    choice: Mapped[str] = mapped_column(String(16), nullable=False)
    sent_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)


def _display_name(user: core.User) -> str:
    if user.first_name:
        return user.first_name
    if user.username:
        return f"@{user.username}"
    return "пользователь"


def _message(user: core.User, choice: str) -> str:
    name = html.escape(_display_name(user))
    mention = f'<a href="tg://user?id={int(user.telegram_id)}">{name}</a>'

    if choice == "maybe":
        extra = (
            "\n\nособенно интересно, что именно мешает вам сказать «да» или «нет». "
            "что должно быть в отдельном канале Nyan Wallet, чтобы вы считали его действительно нужным?"
        )
        chosen = "«не уверен(а)»"
    else:
        extra = ""
        chosen = "«отдельный канал не нужен»"

    return (
        f"многоуважаемый {mention}, у меня к вам один очень простой вопрос.\n\n"
        f"вы в опросе Nyan Wallet выбрали вариант {chosen}.\n\n"
        "мне теперь правда интересно: почему?\n\n"
        "потому что Nyan Wallet уже давно не является одной кнопкой с балансом. "
        "там выходят обновления, промокоды, розыгрыши, новые функции, награды, ивенты, "
        "изменения экономики и куча другого, что сейчас приходится пихать вперемешку с постами Нян Шопа.\n\n"
        "поэтому хотелось бы услышать не просто нажатую кнопку, а нормальную причину.\n\n"
        "что именно вас смущает в отдельном канале? "
        "вы считаете его бесполезным? "
        "не хотите ещё одну подписку? "
        "думаете, что контента для него мало? "
        "или причина вообще в другом?"
        f"{extra}\n\n"
        "ответьте нормально и желательно подробно.\n\n"
        "— Кверт"
    )


def _send(chat_id: int, text: str) -> None:
    payload = urllib.parse.urlencode({
        "chat_id": str(chat_id),
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": "true",
    }).encode()
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{core.BOT_TOKEN}/sendMessage",
        data=payload,
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=8) as response:
        body = json.loads(response.read().decode("utf-8"))
        if not body.get("ok"):
            raise RuntimeError(body.get("description") or "Telegram send failed")


def send_survey_channel_followups_20261011() -> None:
    core.Base.metadata.create_all(core.engine)
    timestamp = core.now_utc()
    sent = []
    skipped = []
    failed = []

    with core.SessionLocal() as session:
        rows = session.execute(
            select(WalletSurveyResponse, core.User)
            .join(core.User, core.User.telegram_id == WalletSurveyResponse.telegram_id)
            .where(WalletSurveyResponse.survey_key == SURVEY_KEY)
            .order_by(WalletSurveyResponse.created_at.asc())
        ).all()

        for response, user in rows:
            try:
                answers = json.loads(response.answers_json or "{}")
            except json.JSONDecodeError:
                continue

            choice = answers.get("separate_channel")
            if choice not in {"no", "maybe"}:
                continue

            exists = session.scalar(
                select(SurveyChannelFollowup.id).where(
                    SurveyChannelFollowup.survey_key == SURVEY_KEY,
                    SurveyChannelFollowup.telegram_id == user.telegram_id,
                )
            )
            if exists is not None:
                skipped.append(int(user.telegram_id))
                continue

            try:
                _send(int(user.telegram_id), _message(user, choice))
                session.add(
                    SurveyChannelFollowup(
                        survey_key=SURVEY_KEY,
                        telegram_id=int(user.telegram_id),
                        choice=choice,
                        sent_at=timestamp,
                    )
                )
                session.commit()
                sent.append({
                    "telegram_id": int(user.telegram_id),
                    "username": user.username,
                    "choice": choice,
                })
            except Exception as exc:
                session.rollback()
                failed.append({
                    "telegram_id": int(user.telegram_id),
                    "username": user.username,
                    "choice": choice,
                    "error": type(exc).__name__,
                })

    print("[survey_channel_followups_20261011] " + json.dumps(
        {"sent": sent, "skipped": skipped, "failed": failed},
        ensure_ascii=False,
    ))
