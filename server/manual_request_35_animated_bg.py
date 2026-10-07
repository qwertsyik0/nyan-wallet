from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select

from server import backend_app as core
from server.advanced_features import UserCosmetic, RequestMeta, WalletNotification
from server.extended_features import SpendRequest, AdminAudit

ACTION = "fulfill_animated_profile_bg_request_35"


def apply_request_35_animated_profile_background() -> None:
    timestamp = datetime.now(timezone.utc)
    with core.SessionLocal() as session:
        with session.begin():
            done = session.scalar(
                select(AdminAudit.id).where(AdminAudit.action == ACTION).limit(1)
            )
            if done:
                return

            request = session.scalar(
                select(SpendRequest).where(
                    SpendRequest.id == 35,
                    SpendRequest.telegram_id == 6665456961,
                ).with_for_update()
            )
            if request is None:
                return

            cosmetic = session.get(UserCosmetic, request.telegram_id)
            if cosmetic is None:
                cosmetic = UserCosmetic(
                    telegram_id=request.telegram_id,
                    profile_background="aurora_pink",
                    updated_at=timestamp,
                )
                session.add(cosmetic)
            else:
                cosmetic.profile_background = "aurora_pink"
                cosmetic.updated_at = timestamp

            request.status = "fulfilled"
            request.processed_at = timestamp

            meta = session.get(RequestMeta, request.id)
            if meta is None:
                meta = RequestMeta(
                    request_id=request.id,
                    owner_comment="Анимированный фон профиля активирован.",
                    updated_at=timestamp,
                )
                session.add(meta)
            else:
                meta.owner_comment = "Анимированный фон профиля активирован."
                meta.updated_at = timestamp

            session.add(
                WalletNotification(
                    telegram_id=request.telegram_id,
                    kind="reward_status",
                    title="Заявка выполнена",
                    body="Заявка #35 выполнена. Анимированный фон профиля активирован.",
                    is_read=False,
                    created_at=timestamp,
                )
            )
            session.add(
                AdminAudit(
                    action=ACTION,
                    target_telegram_id=request.telegram_id,
                    details="Заявка #35: активирован профильный фон aurora_pink",
                    created_at=timestamp,
                )
            )
