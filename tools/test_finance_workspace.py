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

def tx_notifier(mapper, connection, tx):
    if tx.operation_type not in {"owner_grant", "owner_debit"}:
        return
    connection.execute(WalletNotification.__table__.insert().values(
        telegram_id=tx.telegram_id,
        kind=tx.operation_type,
        title="Начисление" if tx.amount > 0 else "Списание",
        body=str(tx.amount),
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
    ])
    session.commit()


async def expect_http_error(expected, operation):
    try:
        await operation
    except HTTPException as error:
        assert error.status_code == expected, (expected, error.status_code, error.detail)
    else:
        raise AssertionError(f"Expected HTTP {expected} error")


def proposal(token, action="grant", amount=50, target="202", reason="Кэшбэк за покупку 162 Stars"):
    return module.ProposalPayload(
        request_token=token,
        action=action,
        amount=amount,
        target=target,
        reason=reason,
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
    module._telegram_finance_notice = lambda chat_id, message: (True, None)
    module._send_approved_finance_notice(id_of_first)
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

    fourth = await module.submit_request(
        proposal("fourth_request123", "debit", 25),
        BackgroundTasks(), x_telegram_init_data="trainee"
    )
    await module.revoke_trainee(
        101, BackgroundTasks(), x_telegram_init_data="owner"
    )
    await expect_http_error(403, module.submit_request(
        proposal("fifth_request123"), BackgroundTasks(),
        x_telegram_init_data="trainee"
    ))
    await expect_http_error(403, module.decide_request(
        fourth["request"]["id"], module.DecisionPayload(decision="approve"),
        BackgroundTasks(), x_telegram_init_data="owner"
    ))
    with SessionLocal() as session:
        assert session.get(User, 202).balance == 550
    print("Finance internship integration: role gates, transaction ledger, in-app notice, Telegram delivery audit, technical investigations, no double execution, insufficient balance, rejection, revoke — OK")


if __name__ == "__main__":
    asyncio.run(run_tests())
