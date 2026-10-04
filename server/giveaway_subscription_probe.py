from sqlalchemy import select

from . import backend_app as core
from .giveaways import (
    Giveaway,
    GiveawayChannel,
    GiveawayParticipant,
    telegram_membership,
)


def probe_active_giveaway_subscription() -> None:
    with core.SessionLocal() as session:
        giveaway = session.scalar(
            select(Giveaway)
            .where(Giveaway.status.in_(("active", "awaiting_results")))
            .order_by(Giveaway.id.desc())
        )
        if giveaway is None:
            print("[giveaway_subscription_probe] no active/awaiting giveaway")
            return

        channel = session.scalar(
            select(GiveawayChannel)
            .where(
                GiveawayChannel.giveaway_id == giveaway.id,
                GiveawayChannel.required_subscription.is_(True),
            )
            .order_by(GiveawayChannel.id.asc())
        )
        if channel is None:
            print(
                f"[giveaway_subscription_probe] giveaway={giveaway.public_id} "
                "has no required subscription channel"
            )
            return

        participants = session.scalars(
            select(GiveawayParticipant)
            .where(
                GiveawayParticipant.giveaway_id == giveaway.id,
                GiveawayParticipant.status == "active",
            )
            .order_by(GiveawayParticipant.id.asc())
            .limit(3)
        ).all()

        label = f"@{channel.username}" if channel.username else channel.title
        print(
            "[giveaway_subscription_probe] "
            f"giveaway={giveaway.public_id} channel={label!r} chat_id={channel.chat_id} "
            f"participants={[int(p.telegram_id) for p in participants]}"
        )
        for participant in participants:
            member, error = telegram_membership(channel.chat_id, participant.telegram_id)
            print(
                "[giveaway_subscription_probe_result] "
                f"telegram_id={participant.telegram_id} member={member} error={error!r}"
            )
