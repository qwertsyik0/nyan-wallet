"""Offline integration checks for finance internship permissions and atomic approvals.

Creates only an in-memory SQLite database; no real wallet, Telegram or network.
"""
from __future__ import annotations

import asyncio
import importlib.util
import sys
import types
from datetime import datetime, timezone

from fastapi import BackgroundTasks, HTTPException
from sqlalchemy import BigInteger, Integer, String, Boolean, DateTime, event, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    telegram_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    username: Mapped[str | None] = mapped_column(String(64))
    first_name: Mapped[str] = mapped_column(String(64))
    last_name: Mapped[str | None] = mapped_column(String(64))
    balance: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class Transaction(Base):
    __tablename__ = "transactions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger)
    amount: Mapped[int] = mapped_column(Integer)
    operation_type: Mapped[str] = mapped_column(String(64))
    description: Mapped[str] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column()


class WalletNotification(Base):
    __tablename__ = "wallet_notifications"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger)
    kind: Mapped[str] = mapped_column(String(50))
    title: Mapped[str] = mapped_column(String(120))
    body: Mapped[str] = mapped_column(String(500))
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class WalletTransfer(Base):
    __tablename__ = "wallet_transfers"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    public_id: Mapped[str] = mapped_column(String(24), unique=True)
    sender_id: Mapped[int] = mapped_column(BigInteger)
    recipient_id: Mapped[int] = mapped_column(BigInteger)
    amount: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class WalletAlias(Base):
    __tablename__ = "wallet_aliases"
    telegram_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    alias: Mapped[str] = mapped_column(String(16))


class WalletAddress(Base):
    __tablename__ = "wallet_addresses"
    telegram_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    public_id: Mapped[str] = mapped_column(String(24), unique=True)


class Referral(Base):
    __tablename__ = "referrals"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    inviter_id: Mapped[int] = mapped_column(BigInteger)


class PromoRedemption(Base):
    __tablename__ = "promo_redemptions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger)
    reward_amount: Mapped[int] = mapped_column(Integer)


class FinancialAdminApplication(Base):
    __tablename__ = "financial_admin_applications"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(String(20))


engine = create_engine("sqlite:///:memory:")
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)

core = types.ModuleType("server.backend_app")
core.Base = Base
core.User = User
core.Transaction = Transaction
core.PromoRedemption = PromoRedemption
core.SessionLocal = SessionLocal
core.engine = engine
core.OWNER_TELEGRAM_ID = 1
core.BOT_TOKEN = None
core.now_utc = lambda: datetime.now(timezone.utc)
core.is_owner = lambda uid: uid == 1


def verify_init_data(value):
    identities = {"owner": 1, "trainee": 101, "target": 202, "stranger": 303}
    if value not in identities:
        raise HTTPException(status_code=401, detail="Недействительная подпись")
    return {"id": identities[value]}


def require_owner(identity):
    if identity["id"] != 1:
        raise HTTPException(status_code=403, detail="Только владелец")


def find_target_user(session, target, lock=False):
    stripped = target.lstrip("@")
    if stripped.isdigit():
        return session.get(User, int(stripped))
    return session.scalar(select(User).where(User.username == stripped))


core.verify_init_data = verify_init_data
core.require_owner = require_owner
core.find_target_user = find_target_user

package = types.ModuleType("server")
package.__path__ = ["server"]
extended = types.ModuleType("server.extended_features")
audit_events = []
extended.audit = lambda session, action, target, details: audit_events.append((action, target))
recruitment = types.ModuleType("server.finance_recruitment")
recruitment.FinancialAdminApplication = FinancialAdminApplication
advanced = types.ModuleType("server.advanced_features")
advanced.WalletNotification = WalletNotification
advanced.Referral = Referral
transfers = types.ModuleType("server.transfers")
transfers.WalletTransfer = WalletTransfer
transfers.WalletAlias = WalletAlias
transfers.WalletAddress = WalletAddress
transfers.format_wallet_alias = lambda alias: alias

def tx_notifier(mapper, connection, tx):
    if tx.operation_type not in {"owner_grant", "owner_debit"}:
        return
    connection.execute(WalletNotification.__table__.insert().values(
        telegram_id=tx.telegram_id,
        kind=tx.operation_type,
        title="Начисление" if tx.amount > 0 else "Списание",
        body=f"{tx.amount} 🐾\\n{tx.description}",
        is_read=False,
        created_at=tx.created_at,
    ))

event.listen(Transaction, "after_insert", tx_notifier)

sys.modules.update({
    "server": package,
    "server.backend_app": core,
    "server.extended_features": extended,
    "server.finance_recruitment": recruitment,
    "server.advanced_features": advanced,
    "server.transfers": transfers,
})

spec = importlib.util.spec_from_file_location("server.finance_workspace", "server/finance_workspace.py")
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)

Base.metadata.create_all(engine)
module.register_finance_workspace(types.SimpleNamespace(include_router=lambda _: None))

with SessionLocal() as session:
    session.add_all([
        User(telegram_id=1, username="owner", first_name="Owner", balance=0),
        User(telegram_id=101, username="nastya", first_name="Nastya", balance=0),
        User(telegram_id=202, username="customer", first_name="Customer", balance=500),
        User(telegram_id=303, username="stranger", first_name="Stranger", balance=0),
        FinancialAdminApplication(id=7, telegram_id=101, status="interview"),
        PromoRedemption(telegram_id=202, reward_amount=100),
        Referral(inviter_id=202),
        WalletAlias(telegram_id=202, alias="NYAN123456789012"),
        WalletTransfer(
            public_id="NWT0123456789ABCDEF", sender_id=202, recipient_id=303,
            amount=15, created_at=datetime.now(timezone.utc),
        ),
    ])
    session.commit()


async def expect_http_error(expected, operation):
    try:
        await operation
    except HTTPException as error:
        assert error.status_code == expected, (expected, error.status_code, error.detail)
    else:
        raise AssertionError(f"Expected HTTP {expected} error")


def proposal(token, action="grant", amount=50, target="202",
             reason="Служебная проверка расчёта, ссылка на платёж заказчика",
             public_reason="Кэшбэк за покупку Telegram Stars"):
    return module.ProposalPayload(
        request_token=token,
        action=action,
        amount=amount,
        target=target,
        reason=reason,
        public_reason=public_reason if action != "investigate" else None,
        evidence="Заявка на проверку",
    )


async def run_tests():
    denial = False
    try:
        await module.submit_request(
            proposal("nocredentials1234"), BackgroundTasks(),
            x_telegram_init_data="stranger"
        )
    except HTTPException as exc:
        denial = exc.status_code == 403
    assert denial, "Non-trainee was allowed to submit a request"

    appointed = await module.appoint_trainee(
        7, BackgroundTasks(), x_telegram_init_data="owner"
    )
    assert appointed["active"] is True
    access = await module.access(x_telegram_init_data="trainee")
    assert access["role"] == "trainee"
    await expect_http_error(422, module.submit_request(
        proposal("no_public_reason_12", public_reason=None),
        BackgroundTasks(), x_telegram_init_data="trainee"
    ))

    first = await module.submit_request(
        proposal("first_request_123"), BackgroundTasks(),
        x_telegram_init_data="trainee"
    )
    assert first["request"]["status"] == "pending"
    assert first["request"]["amount"] == 50
    with SessionLocal() as session:
        assert session.get(User, 202).balance == 500
        assert not session.scalars(select(Transaction)).all()

    identical = await module.submit_request(
        proposal("first_request_123"), BackgroundTasks(),
        x_telegram_init_data="trainee"
    )
    assert identical["already_submitted"] is True
    assert identical["request"]["id"] == first["request"]["id"]

    id_of_first = first["request"]["id"]
    await expect_http_error(403, module.decide_request(
        id_of_first, module.DecisionPayload(decision="approve"),
        BackgroundTasks(), x_telegram_init_data="stranger"
    ))
    await module.decide_request(
        id_of_first, module.DecisionPayload(decision="approve", note="Подтверждаю"),
        BackgroundTasks(), x_telegram_init_data="owner"
    )
    with SessionLocal() as session:
        assert session.get(User, 202).balance == 550
        transactions = session.scalars(select(Transaction)).all()
        assert len(transactions) == 1 and transactions[0].amount == 50
        assert transactions[0].description == "Кэшбэк за покупку Telegram Stars"
        assert "Служебная проверка" not in transactions[0].description
        notices = session.scalars(select(WalletNotification)).all()
        assert all("Служебная проверка" not in n.body for n in notices)
        delivery = session.get(module.FinanceTelegramDelivery, id_of_first)
        assert delivery and delivery.status == "pending"
        assert len(session.scalars(select(WalletNotification)).all()) == 1
    assert (await module.owner_verify_financial_result(
        id_of_first, x_telegram_init_data="owner"
    ))["ledger_match"] is True
    assert (await module.owner_verify_financial_result(
        id_of_first, x_telegram_init_data="owner"
    ))["in_app_notification"] is True
    # Telegram API itself is mocked, no messages are sent outside this test.
    delivered = []
    module._telegram_finance_notice = lambda chat_id, message: (
        delivered.append((chat_id, message)) or True, None
    )
    module._send_approved_finance_notice(id_of_first)
    assert delivered[0][0] == 202
    assert "Кэшбэк за покупку Telegram Stars" in delivered[0][1]
    assert not any(x in delivered[0][1].lower() for x in [
        "стажёр", "владелец", "одобрена", "заявка", "служебная проверка"
    ])
    with SessionLocal() as session:
        assert session.get(module.FinanceTelegramDelivery, id_of_first).status == "sent"
        assert session.get(module.FinanceTelegramDelivery, id_of_first).attempts == 1
    module._send_approved_finance_notice(id_of_first)
    with SessionLocal() as session:
        assert session.get(module.FinanceTelegramDelivery, id_of_first).attempts == 1
    await expect_http_error(409, module.retry_financial_notification(
        id_of_first, BackgroundTasks(), x_telegram_init_data="owner"
    ))
    await expect_http_error(409, module.decide_request(
        id_of_first, module.DecisionPayload(decision="approve"),
        BackgroundTasks(), x_telegram_init_data="owner"
    ))

    second = await module.submit_request(
        proposal("second_request12", "debit", 600),
        BackgroundTasks(), x_telegram_init_data="trainee"
    )
    await expect_http_error(409, module.decide_request(
        second["request"]["id"], module.DecisionPayload(decision="approve"),
        BackgroundTasks(), x_telegram_init_data="owner"
    ))
    await module.decide_request(
        second["request"]["id"],
        module.DecisionPayload(decision="reject", note="Баланс недостаточен"),
        BackgroundTasks(), x_telegram_init_data="owner"
    )
    with SessionLocal() as session:
        assert session.get(User, 202).balance == 550

    # Unknown transaction references are allowed for technical investigations.
    third = await module.submit_request(
        proposal("third_request_123", "investigate", 0, "TX-101"),
        BackgroundTasks(), x_telegram_init_data="trainee"
    )
    assert third["request"]["target_id"] is None
    assert third["request"]["target_reference"] == "TX-101"
    await expect_http_error(404, module.submit_request(
        proposal("bad_grant_user123", "grant", 5, "TX-101"),
        BackgroundTasks(), x_telegram_init_data="trainee"
    ))
    owner_reference = await module.submit_request(
        proposal("owner_inquiry_123", "investigate", 0, "1"),
        BackgroundTasks(), x_telegram_init_data="trainee"
    )
    assert owner_reference["request"]["target_id"] == 1
    no_reference = await module.submit_request(
        proposal("no_reference_123", "investigate", 0, ""),
        BackgroundTasks(), x_telegram_init_data="trainee"
    )
    assert no_reference["request"]["target_id"] is None
    assert no_reference["request"]["target_label"] == "без указанного кошелька"
    await module.decide_request(
        third["request"]["id"], module.DecisionPayload(decision="approve"),
        BackgroundTasks(), x_telegram_init_data="owner"
    )
    with SessionLocal() as session:
        assert session.get(User, 202).balance == 550
        assert len(session.scalars(select(Transaction)).all()) == 1

    # A technical investigation produces a private report even when
    # the transaction reference cannot be resolved.
    module._send_approved_finance_notice(third["request"]["id"])
    assert delivered[-1][0] == 101
    assert "Кошелёк по указанным данным не найден" in delivered[-1][1]

    report = await module.submit_request(
        proposal("known_wallet_123", "investigate", 0, "202"),
        BackgroundTasks(), x_telegram_init_data="trainee"
    )
    await module.decide_request(
        report["request"]["id"], module.DecisionPayload(decision="approve"),
        BackgroundTasks(), x_telegram_init_data="owner"
    )
    module._send_approved_finance_notice(report["request"]["id"])
    assert delivered[-1][0] == 101  # Only the trainee, never the customer
    assert "Баланс: 550 🐾" in delivered[-1][1]
    assert "Telegram ID: 202" in delivered[-1][1]
    assert "Промокоды: 1, получено 100 🐾" in delivered[-1][1]
    assert "NWT0123456789ABCDEF" in delivered[-1][1]
    assert "Служебная проверка" not in delivered[-1][1]
    with SessionLocal() as session:
        assert session.get(User, 202).balance == 550
        assert len(session.scalars(select(Transaction)).all()) == 1

    transfer_case = await module.submit_request(
        proposal("transfer_id_report", "investigate", 0, "NWT0123456789ABCDEF"),
        BackgroundTasks(), x_telegram_init_data="trainee"
    )
    await module.decide_request(
        transfer_case["request"]["id"], module.DecisionPayload(decision="approve"),
        BackgroundTasks(), x_telegram_init_data="owner"
    )
    module._send_approved_finance_notice(transfer_case["request"]["id"])
    assert delivered[-1][0] == 101
    assert "Telegram ID: 202" in delivered[-1][1]
    assert "Telegram ID: 303" in delivered[-1][1]
    with SessionLocal() as session:
        assert session.get(User, 202).balance == 550

    failed_delivery = await module.submit_request(
        proposal("failed_notice_123", "grant", 10),
        BackgroundTasks(), x_telegram_init_data="trainee"
    )
    failed_id = failed_delivery["request"]["id"]
    await module.decide_request(
        failed_id, module.DecisionPayload(decision="approve"),
        BackgroundTasks(), x_telegram_init_data="owner"
    )
    module._telegram_finance_notice = lambda chat_id, message: (
        False, "Forbidden: bot was blocked by the user"
    )
    module._send_approved_finance_notice(failed_id)
    with SessionLocal() as session:
        delivery = session.get(module.FinanceTelegramDelivery, failed_id)
        assert delivery.status == "failed"
        assert delivery.attempts == 1
        assert session.get(User, 202).balance == 560
    retry = await module.retry_financial_notification(
        failed_id, BackgroundTasks(), x_telegram_init_data="owner"
    )
    assert retry["queued"] is True
    module._telegram_finance_notice = lambda chat_id, message: (True, None)
    module._send_approved_finance_notice(failed_id)
    with SessionLocal() as session:
        delivery = session.get(module.FinanceTelegramDelivery, failed_id)
        assert delivery.status == "sent"
        assert delivery.attempts == 2
        assert session.get(User, 202).balance == 560
        assert len(session.scalars(select(Transaction)).all()) == 2

    fourth = await module.submit_request(
        proposal("fourth_request123", "debit", 25),
        BackgroundTasks(), x_telegram_init_data="trainee"
    )
    revocation_case = await module.submit_request(
        proposal("revoke_case_1234", "investigate", 0, "202"),
        BackgroundTasks(), x_telegram_init_data="trainee"
    )
    await module.decide_request(
        revocation_case["request"]["id"], module.DecisionPayload(decision="approve"),
        BackgroundTasks(), x_telegram_init_data="owner"
    )
    deliveries_before = len(delivered)
    await module.revoke_trainee(
        101, BackgroundTasks(), x_telegram_init_data="owner"
    )
    module._telegram_finance_notice = lambda chat_id, message: (
        delivered.append((chat_id, message)) or True, None
    )
    module._send_approved_finance_notice(revocation_case["request"]["id"])
    assert len(delivered) == deliveries_before
    with SessionLocal() as session:
        revoked_delivery = session.get(module.FinanceTelegramDelivery, revocation_case["request"]["id"])
        assert revoked_delivery.status == "failed"
        assert revoked_delivery.attempts == 0
    await expect_http_error(403, module.retry_financial_notification(
        revocation_case["request"]["id"], BackgroundTasks(),
        x_telegram_init_data="owner"
    ))
    await expect_http_error(403, module.submit_request(
        proposal("fifth_request123"), BackgroundTasks(),
        x_telegram_init_data="trainee"
    ))
    await expect_http_error(403, module.decide_request(
        fourth["request"]["id"], module.DecisionPayload(decision="approve"),
        BackgroundTasks(), x_telegram_init_data="owner"
    ))
    with SessionLocal() as session:
        assert session.get(User, 202).balance == 560

    # Old customer-visible descriptions are scrubbed while original
    # confidential owner rationale remains in the finance request table.
    with SessionLocal() as session:
        with session.begin():
            old = module.FinanceDecisionRequest(
                trainee_id=101, target_id=202, target_reference="202",
                action="grant", amount=7, reason="Конфиденциальная служебная проверка",
                public_reason=None, evidence="old evidence", request_token="legacy_scrub_123",
                status="approved", created_at=datetime.now(timezone.utc),
            )
            session.add(old)
            session.flush()
            legacy_transaction = Transaction(
                telegram_id=202, amount=7, operation_type="owner_grant",
                description=f"Конфиденциальная служебная проверка (стажёрская заявка №{old.id})",
                created_at=datetime.now(timezone.utc),
            )
            session.add(legacy_transaction)
            session.flush()
            old.transaction_id = legacy_transaction.id
            old_id = old.id
    module._scrub_legacy_public_finance_messages()
    with SessionLocal() as session:
        old = session.get(module.FinanceDecisionRequest, old_id)
        tx = session.get(Transaction, old.transaction_id)
        assert old.reason == "Конфиденциальная служебная проверка"
        assert tx.description == "Начисление лапкоинов"
        assert all(
            "Конфиденциальная" not in n.body
            for n in session.scalars(
                select(WalletNotification).where(
                    WalletNotification.telegram_id == 202,
                    WalletNotification.body.contains(f"заявка №{old_id}"),
                )
            ).all()
        )
    print("Finance internship integration: role gates, transaction ledger, in-app notice, Telegram delivery audit, technical investigations, no double execution, insufficient balance, rejection, revoke — OK")


if __name__ == "__main__":
    asyncio.run(run_tests())
