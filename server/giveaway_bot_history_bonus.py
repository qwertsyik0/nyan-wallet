from sqlalchemy import func, select

from . import backend_app as core
from .giveaways import Giveaway, GiveawayParticipant, GiveawayTicket, next_ticket_number, now_utc


BULK_SOURCE = "bot_history_bonus"


def grant_bot_history_ticket_to_active_giveaway() -> None:
    """Give one bonus ticket to every historical bot user for the latest active giveaway.

    Idempotency is provided by GiveawayTicket.source: each user can receive
    at most one ticket from this batch for a giveaway.
    """

    timestamp = now_utc()

    with core.SessionLocal() as session:
        with session.begin():
            giveaway = session.scalar(
                select(Giveaway)
                .where(Giveaway.status == "active")
                .order_by(Giveaway.started_at.desc().nullslast(), Giveaway.id.desc())
                .with_for_update()
            )

            if giveaway is None:
                print("[bot_history_bonus] no active giveaway; nothing granted")
                return

            users = session.scalars(
                select(core.User)
                .where(
                    core.User.telegram_id != (core.OWNER_TELEGRAM_ID or -1)
                )
                .order_by(core.User.telegram_id.asc())
            ).all()

            existing_bonus_ids = set(
                session.scalars(
                    select(GiveawayTicket.telegram_id).where(
                        GiveawayTicket.giveaway_id == giveaway.id,
                        GiveawayTicket.source == BULK_SOURCE,
                        GiveawayTicket.voided_at.is_(None),
                        GiveawayTicket.refunded_at.is_(None),
                    )
                ).all()
            )

            participant_rows = {
                row.telegram_id: row
                for row in session.scalars(
                    select(GiveawayParticipant).where(
                        GiveawayParticipant.giveaway_id == giveaway.id,
                        GiveawayParticipant.telegram_id.in_([u.telegram_id for u in users]),
                    )
                ).all()
            }

            next_number = next_ticket_number(session, giveaway.id)
            granted = 0
            already = 0
            skipped_inactive = 0
            created_participants = 0

            for user in users:
                telegram_id = int(user.telegram_id)

                if telegram_id in existing_bonus_ids:
                    already += 1
                    continue

                participant = participant_rows.get(telegram_id)
                if participant is not None and participant.status != "active":
                    skipped_inactive += 1
                    continue

                if participant is None:
                    participant = GiveawayParticipant(
                        giveaway_id=giveaway.id,
                        telegram_id=telegram_id,
                        source_chat_id=None,
                        status="active",
                        exclusion_reason=None,
                        joined_at=timestamp,
                        updated_at=timestamp,
                    )
                    session.add(participant)
                    session.flush()
                    participant_rows[telegram_id] = participant
                    created_participants += 1

                session.add(
                    GiveawayTicket(
                        giveaway_id=giveaway.id,
                        participant_id=participant.id,
                        telegram_id=telegram_id,
                        ticket_number=next_number,
                        source=BULK_SOURCE,
                        paid_amount=0,
                        transaction_id=None,
                        created_at=timestamp,
                        voided_at=None,
                        void_reason=None,
                        refunded_at=None,
                    )
                )
                next_number += 1
                granted += 1

            session.flush()

            total_users = len(users)
            total_tickets = int(
                session.scalar(
                    select(func.count()).select_from(GiveawayTicket).where(
                        GiveawayTicket.giveaway_id == giveaway.id,
                        GiveawayTicket.voided_at.is_(None),
                        GiveawayTicket.refunded_at.is_(None),
                    )
                ) or 0
            )
            total_participants = int(
                session.scalar(
                    select(func.count()).select_from(GiveawayParticipant).where(
                        GiveawayParticipant.giveaway_id == giveaway.id,
                        GiveawayParticipant.status == "active",
                    )
                ) or 0
            )

            print(
                "[bot_history_bonus] "
                f"giveaway={giveaway.public_id} title={giveaway.title!r} "
                f"historical_users={total_users} granted={granted} already={already} "
                f"skipped_inactive={skipped_inactive} created_participants={created_participants} "
                f"total_participants={total_participants} total_tickets={total_tickets} "
                f"participant_limit={giveaway.participant_limit} global_ticket_limit={giveaway.global_ticket_limit}"
            )
