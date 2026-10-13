from sqlalchemy import func, or_, select

from . import backend_app as core
from .advanced_features import Referral
from .activity import ActivityCheckIn, ActivityStreak
from .daily_tasks import UserTaskProgress
from .transfers import WalletTransfer

TARGETS = (6453256342, 5806003261)


def print_farm_check_floriannq_weevtt_20261014() -> None:
    print("[FARMCHK] BEGIN")
    with core.SessionLocal() as session:
        for telegram_id in TARGETS:
            user = session.get(core.User, telegram_id)
            if user is None:
                print(f"[FARMCHK] USER id={telegram_id} missing")
                continue

            print(
                "[FARMCHK] USER "
                f"id={telegram_id} username={user.username!r} balance={user.balance} "
                f"created_at={user.created_at.isoformat()} last_seen_at={user.last_seen_at.isoformat()}"
            )

            aggs = session.execute(
                select(
                    core.Transaction.operation_type,
                    func.count(core.Transaction.id),
                    func.coalesce(func.sum(core.Transaction.amount), 0),
                )
                .where(core.Transaction.telegram_id == telegram_id)
                .group_by(core.Transaction.operation_type)
                .order_by(core.Transaction.operation_type)
            ).all()
            for op, count, total in aggs:
                print(f"[FARMCHK] TXSUM id={telegram_id} op={op} count={count} total={total}")

            txs = session.scalars(
                select(core.Transaction)
                .where(core.Transaction.telegram_id == telegram_id)
                .order_by(core.Transaction.created_at.asc(), core.Transaction.id.asc())
            ).all()
            for tx in txs:
                print(
                    "[FARMCHK] TX "
                    f"id={telegram_id} txid={tx.id} amount={tx.amount} op={tx.operation_type} "
                    f"created_at={tx.created_at.isoformat()} description={tx.description!r}"
                )

            streak = session.get(ActivityStreak, telegram_id)
            if streak:
                print(
                    "[FARMCHK] STREAK "
                    f"id={telegram_id} current={streak.current_streak} best={streak.best_streak} "
                    f"total={streak.total_checkins} last={streak.last_checkin_date} "
                    f"last_reward={streak.last_reward_amount}"
                )

            checks = session.scalars(
                select(ActivityCheckIn)
                .where(ActivityCheckIn.telegram_id == telegram_id)
                .order_by(ActivityCheckIn.created_at.asc())
            ).all()
            for row in checks:
                print(
                    "[FARMCHK] CHECKIN "
                    f"id={telegram_id} date={row.checkin_date} streak_day={row.streak_day} "
                    f"reward={row.reward_amount} created_at={row.created_at.isoformat()}"
                )

            tasks = session.scalars(
                select(UserTaskProgress)
                .where(UserTaskProgress.telegram_id == telegram_id)
                .order_by(UserTaskProgress.id.asc())
            ).all()
            for row in tasks:
                print(
                    "[FARMCHK] TASK "
                    f"id={telegram_id} task_id={row.task_id} period={row.period_key} "
                    f"progress={row.progress} completed={row.completed} "
                    f"claimed={row.reward_claimed} reward={row.claimed_reward_amount} "
                    f"claimed_at={row.reward_claimed_at.isoformat() if row.reward_claimed_at else None}"
                )

        refs = session.scalars(
            select(Referral)
            .where(
                or_(
                    Referral.inviter_id.in_(TARGETS),
                    Referral.invited_id.in_(TARGETS),
                )
            )
            .order_by(Referral.created_at.asc(), Referral.id.asc())
        ).all()
        for ref in refs:
            print(
                "[FARMCHK] REF "
                f"refid={ref.id} inviter={ref.inviter_id} invited={ref.invited_id} "
                f"inviter_reward={ref.inviter_reward} invited_reward={ref.invited_reward} "
                f"created_at={ref.created_at.isoformat()}"
            )

        transfers = session.scalars(
            select(WalletTransfer)
            .where(
                or_(
                    WalletTransfer.sender_id.in_(TARGETS),
                    WalletTransfer.recipient_id.in_(TARGETS),
                )
            )
            .order_by(WalletTransfer.created_at.asc(), WalletTransfer.id.asc())
        ).all()
        for tr in transfers:
            print(
                "[FARMCHK] TRANSFER "
                f"transfer_id={tr.id} sender={tr.sender_id} recipient={tr.recipient_id} "
                f"amount={tr.amount} created_at={tr.created_at.isoformat()} note={tr.note!r}"
            )

        promos = session.execute(
            select(
                core.PromoRedemption.telegram_id,
                core.PromoCode.code,
                core.PromoRedemption.reward_amount,
                core.PromoRedemption.created_at,
            )
            .join(core.PromoCode, core.PromoCode.id == core.PromoRedemption.promo_id)
            .where(core.PromoRedemption.telegram_id.in_(TARGETS))
            .order_by(core.PromoRedemption.created_at.asc())
        ).all()
        for telegram_id, code, reward, created_at in promos:
            print(
                "[FARMCHK] PROMO "
                f"id={telegram_id} code={code} reward={reward} created_at={created_at.isoformat()}"
            )

    print("[FARMCHK] END")
