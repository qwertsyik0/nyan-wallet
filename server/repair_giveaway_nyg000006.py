from sqlalchemy import func, select

from . import backend_app as core
from .giveaways import (
    Giveaway,
    GiveawayParticipant,
    GiveawayResult,
    GiveawayResultPost,
    GiveawayTicket,
    _cleanup_telegram_messages,
    now_utc,
    sync_giveaway_buttons,
)


TARGET_PUBLIC_ID = "NYG-000006"
BAD_SOURCE = "bot_history_bonus"
REASON = "Исправление ошибочной массовой выдачи билетов"


def repair_nyg_000006_bonus_tickets() -> None:
    timestamp = now_utc()
    published_messages: list[tuple[int, list[int]]] = []

    with core.SessionLocal() as session:
        with session.begin():
            giveaway = session.scalar(
                select(Giveaway)
                .where(Giveaway.public_id == TARGET_PUBLIC_ID)
                .with_for_update()
            )
            if giveaway is None:
                print("[repair_nyg_000006] giveaway not found")
                return

            bad_tickets = session.scalars(
                select(GiveawayTicket).where(
                    GiveawayTicket.giveaway_id == giveaway.id,
                    GiveawayTicket.source == BAD_SOURCE,
                    GiveawayTicket.voided_at.is_(None),
                    GiveawayTicket.refunded_at.is_(None),
                )
            ).all()

            if not bad_tickets:
                print("[repair_nyg_000006] already repaired; no active bad tickets")
                return

            affected_participant_ids = {int(ticket.participant_id) for ticket in bad_tickets}
            for ticket in bad_tickets:
                ticket.voided_at = timestamp
                ticket.void_reason = REASON

            session.flush()

            removed_participants = 0
            for participant_id in affected_participant_ids:
                participant = session.get(GiveawayParticipant, participant_id)
                if participant is None:
                    continue
                remaining = int(
                    session.scalar(
                        select(func.count())
                        .select_from(GiveawayTicket)
                        .where(
                            GiveawayTicket.giveaway_id == giveaway.id,
                            GiveawayTicket.participant_id == participant_id,
                            GiveawayTicket.voided_at.is_(None),
                            GiveawayTicket.refunded_at.is_(None),
                        )
                    )
                    or 0
                )
                if remaining == 0 and participant.status == "active":
                    participant.status = "excluded"
                    participant.exclusion_reason = REASON
                    participant.updated_at = timestamp
                    removed_participants += 1

            active_results = session.scalars(
                select(GiveawayResult)
                .where(
                    GiveawayResult.giveaway_id == giveaway.id,
                    GiveawayResult.status == "active",
                )
                .with_for_update()
            ).all()
            for result in active_results:
                result.status = "annulled"
                result.reason = REASON

            result_posts = session.scalars(
                select(GiveawayResultPost).where(
                    GiveawayResultPost.giveaway_id == giveaway.id,
                    GiveawayResultPost.status.in_(("published", "stale")),
                )
            ).all()
            for post in result_posts:
                published_messages.append((int(post.chat_id), [int(post.message_id)]))
                post.status = "invalidated"

            giveaway.status = "awaiting_results"
            giveaway.completed_at = None
            giveaway.updated_at = timestamp
            sync_giveaway_buttons(session, giveaway, closed=True)

            active_tickets_after = int(
                session.scalar(
                    select(func.count())
                    .select_from(GiveawayTicket)
                    .where(
                        GiveawayTicket.giveaway_id == giveaway.id,
                        GiveawayTicket.voided_at.is_(None),
                        GiveawayTicket.refunded_at.is_(None),
                    )
                )
                or 0
            )
            active_participants_after = int(
                session.scalar(
                    select(func.count())
                    .select_from(GiveawayParticipant)
                    .where(
                        GiveawayParticipant.giveaway_id == giveaway.id,
                        GiveawayParticipant.status == "active",
                    )
                )
                or 0
            )

            print(
                "[repair_nyg_000006] "
                f"voided_bonus_tickets={len(bad_tickets)} "
                f"annulled_results={len(active_results)} "
                f"invalidated_result_posts={len(result_posts)} "
                f"excluded_bonus_only_participants={removed_participants} "
                f"active_tickets_after={active_tickets_after} "
                f"active_participants_after={active_participants_after}"
            )

    if published_messages:
        _cleanup_telegram_messages(published_messages)
