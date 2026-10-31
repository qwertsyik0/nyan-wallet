"""Local financial invariants test: SQLite only, no live database or Telegram."""

from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import BackgroundTasks, HTTPException
from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, LargeBinary, String, Text, UniqueConstraint, func, select
from sqlalchemy.orm import Mapped, mapped_column

ROOT = Path(__file__).resolve().parents[1]
temporary = tempfile.TemporaryDirectory(prefix="takeover-test-")
os.environ["BOT_TOKEN"] = "takeover-test-token"
os.environ["OWNER_TELEGRAM_ID"] = "900000"
os.environ["DATABASE_URL"] = "sqlite:///" + str(Path(temporary.name) / "wallet.sqlite")
os.environ["NYAN_TAKEOVER_CHAT_ID"] = "-10012345678"

pkg = types.ModuleType("server")
pkg.__path__ = [str(ROOT / "server")]
sys.modules["server"] = pkg


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / "server" / filename)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


core = load("server.backend_app", "backend_app.py")


class LimitedProfileBadge(core.Base):
    __tablename__ = "limited_profile_badges"
    __table_args__ = (UniqueConstraint("badge_key", "edition", name="uq_test_limited_badge_edition"),)
    telegram_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.telegram_id"), primary_key=True)
    badge_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    title: Mapped[str] = mapped_column(String(80))
    edition: Mapped[int] = mapped_column(Integer)
    acquired_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class WalletSkin(core.Base):
    __tablename__ = "wallet_skins"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(120))
    description: Mapped[str | None] = mapped_column(Text)
    text_theme: Mapped[str] = mapped_column(String(12))
    image_mime: Mapped[str] = mapped_column(String(32))
    image_data: Mapped[bytes] = mapped_column(LargeBinary)
    image_sha256: Mapped[str] = mapped_column(String(64))
    image_width: Mapped[int] = mapped_column(Integer)
    image_height: Mapped[int] = mapped_column(Integer)
    is_template: Mapped[bool] = mapped_column(Boolean)
    is_active: Mapped[bool] = mapped_column(Boolean)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class UserWalletSkin(core.Base):
    __tablename__ = "user_wallet_skins"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.telegram_id"))
    skin_id: Mapped[int] = mapped_column(Integer, ForeignKey("wallet_skins.id"))
    is_active: Mapped[bool] = mapped_column(Boolean)
    acquired_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


def assign_skin_to_user(session, uid, skin, timestamp):
    for owned in session.scalars(select(UserWalletSkin).where(UserWalletSkin.telegram_id == uid)):
        owned.is_active = False
    row = UserWalletSkin(telegram_id=uid, skin_id=skin.id, is_active=True, acquired_at=timestamp)
    session.add(row)
    return row


class BlockedUser(core.Base):
    __tablename__ = "blocked_users"
    telegram_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.telegram_id"), primary_key=True)
    reason: Mapped[str] = mapped_column(Text)
    blocked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


achievements = types.ModuleType("server.achievements")
achievements.LimitedProfileBadge = LimitedProfileBadge
sys.modules["server.achievements"] = achievements
appeals = types.ModuleType("server.appeals")
appeals.WalletSkin = WalletSkin
appeals.assign_skin_to_user = assign_skin_to_user
sys.modules["server.appeals"] = appeals
bans = types.ModuleType("server.user_bans")
bans.BlockedUser = BlockedUser
sys.modules["server.user_bans"] = bans
extended = types.ModuleType("server.extended_features")
extended.send_telegram_message = lambda *args, **kwargs: None
sys.modules["server.extended_features"] = extended

group = load("server.nyan_takeover_group", "nyan_takeover_group.py")
def fake_bot_api(method, payload, **_):
    if method == "getChat":
        return {"type":"supergroup", "id":-10012345678, "title":"Тестовый закрытый флуд"}
    if method == "getMe":
        return {"id":777000}
    if method == "getChatMember":
        if payload["user_id"] == 777000:
            return {"status":"administrator"}
        return {"status":"member" if payload["user_id"] in (10001,10002,10003) else "left"}
    if method == "sendMessage":
        return {"message_id":87}
    raise AssertionError(method)
group.bot_api = fake_bot_api
takeover = load("server.nyan_takeover", "nyan_takeover.py")
auction = load("server.nyan_takeover_auction", "nyan_takeover_auction.py")
drops = load("server.nyan_takeover_drops", "nyan_takeover_drops.py")
clock = takeover.START + timedelta(minutes=5)
takeover.now = lambda: clock
auction.now = lambda: clock
drops.now = lambda: clock
core.verify_init_data = lambda token: {"id": int(token), "first_name": "Тест", "username": f"test{token}"}
core.get_or_create_user = lambda tg: None
core.Base.metadata.create_all(core.engine)
with core.SessionLocal.begin() as session:
    for uid in (10001,10002,10003,10004,10005,900000):
        session.add(core.User(telegram_id=uid, first_name="Тест", username=f"test{uid}",
                              last_name=None, balance=3000 if uid != 900000 else 0,
                              created_at=clock, last_seen_at=clock))
    session.add(BlockedUser(telegram_id=10005, reason="test", blocked_at=clock))

group.register_nyan_takeover_group(core.app)
takeover.register_nyan_takeover(core.app)
auction.register_nyan_takeover_auction(core.app)
drops.register_nyan_takeover_drops(core.app)
takeover._seed()  # idempotent re-register, no stock replenishment


def fails(call, code):
    try:
        call()
    except HTTPException as exc:
        assert exc.status_code == code, (exc.status_code, code)
    else:
        raise AssertionError(f"Expected HTTP {code}")


def apply(uid):
    return takeover.register(BackgroundTasks(), x_telegram_init_data=str(uid))


def decide(uid, approved=True):
    return takeover.owner_decision(takeover.DecisionRequest(telegram_id=uid,approved=approved),
                                   BackgroundTasks(), x_telegram_init_data="900000")


def buy(uid, sku, key):
    return takeover.buy(takeover.PurchaseRequest(sku=sku, request_key=key), x_telegram_init_data=str(uid))


assert group.owner_group(x_telegram_init_data="900000")["chat_id"] == -10012345678
bound = group.owner_bind(group.BindRequest(chat_link_or_id="https://t.me/c/12345678/99"),x_telegram_init_data="900000")
assert bound["chat_id"] == -10012345678
assert group.owner_publish(group.PublishRequest(text="Открытие NYAN TAKEOVER",request_key="publish_aaaaaaaaaaaaaa"),
                           x_telegram_init_data="900000")["message_id"] == 87
assert group.owner_publish(group.PublishRequest(text="Открытие NYAN TAKEOVER",request_key="publish_aaaaaaaaaaaaaa"),
                           x_telegram_init_data="900000")["repeated"] is True
for uid in (10001,10002,10003):
    assert apply(uid)["status"] == "approved"
assert takeover.status(x_telegram_init_data="10001")["access"] == "approved"
assert takeover.status(x_telegram_init_data="10004")["access"] == "none"
assert "name" not in takeover.status(x_telegram_init_data="10004")
fails(lambda: takeover.claim(x_telegram_init_data="10004"),403)
fails(lambda: buy(10004,"limited_badge","request_key_aaaaaaaaaaaa"),403)
fails(lambda: apply(10005),403)
fails(lambda: apply(10004),403)

assert takeover.claim(x_telegram_init_data="10001")["balance"] == 3500
assert takeover.claim(x_telegram_init_data="10001")["repeated"] is True
assert buy(10001,"resident_skin","request_key_skin_aaaaaaa")["balance"] == 2000
assert buy(10001,"resident_skin","request_key_skin_aaaaaaa")["repeated"] is True
fails(lambda: buy(10001,"resident_skin","request_key_skin_bbbbbbb"),409)
assert buy(10001,"limited_badge","request_key_badge_aaaaaa")["balance"] == 1000
assert buy(10002,"limited_badge","request_key_badge_bbbbbb")["remaining"] == 1
assert buy(10003,"limited_badge","request_key_badge_cccccc")["remaining"] == 0
fails(lambda: buy(10002,"limited_badge","request_key_badge_dddddd"),409)

with core.SessionLocal() as session:
    assert session.scalar(select(func.count()).select_from(takeover.TakeoverGrant)) == 1
    assert session.scalar(select(func.count()).select_from(takeover.TakeoverPurchase)) == 4
    assert session.scalar(select(func.count()).select_from(LimitedProfileBadge).where(
        LimitedProfileBadge.badge_key == "takeover_2026_founding")) == 1

opened = auction.owner_control(auction.AuctionControl(lot_key="exclusive_badge",action="open"),x_telegram_init_data="900000")
assert opened["status"] == "open"
assert auction.bid(auction.BidPayload(lot_key="exclusive_badge",amount=900,request_key="bid_aaaaaaaaaaaaaaaa"),
                   x_telegram_init_data="10002")["leading"] is True
assert auction.bid(auction.BidPayload(lot_key="exclusive_badge",amount=1000,request_key="bid_bbbbbbbbbbbbbbbb"),
                   x_telegram_init_data="10003")["leading"] is True
assert auction.bid(auction.BidPayload(lot_key="exclusive_badge",amount=1000,request_key="bid_bbbbbbbbbbbbbbbb"),
                   x_telegram_init_data="10003")["repeated"] is True
assert auction.owner_control(auction.AuctionControl(lot_key="exclusive_badge",action="settle"),
                             x_telegram_init_data="900000")["winner_id"] == 10003
fails(lambda: auction.bid(auction.BidPayload(lot_key="exclusive_badge",amount=1200,request_key="bid_cccccccccccccccc"),
                          x_telegram_init_data="10002"),409)

drop = drops.owner_create_drop(drops.CreateDrop(amount=100,capacity=1,minutes=15),x_telegram_init_data="900000")
assert drops.claim_drop(drops.DropId(drop_id=drop["id"]),x_telegram_init_data="10002")["reward"] == 100
assert drops.claim_drop(drops.DropId(drop_id=drop["id"]),x_telegram_init_data="10002")["repeated"] is True
fails(lambda: drops.claim_drop(drops.DropId(drop_id=drop["id"]),x_telegram_init_data="10003"),409)

with core.SessionLocal.begin() as session:
    for op in ("fortune_spin", "lottery_ticket", "promo"):
        session.add(core.Transaction(telegram_id=10002, amount=-1, operation_type=op,
                                     description="test", created_at=clock))
assert takeover.mission(x_telegram_init_data="10002")["progress"] == 3
assert takeover.mission_claim(x_telegram_init_data="10002")["reward"] == 150
assert takeover.mission_claim(x_telegram_init_data="10002")["repeated"] is True

with core.SessionLocal() as session:
    assert session.get(core.User,10002).balance == 3000 - 1000 + 100 + 150  # 900 bid refunded
    assert session.get(core.User,10003).balance == 1000  # 1000 badge + 1000 winning bid
    assert session.scalar(select(func.count()).select_from(takeover.TakeoverMissionClaim)) == 1

clock = takeover.END + timedelta(seconds=1)
fails(lambda: takeover.claim(x_telegram_init_data="10002"),409)
fails(lambda: buy(10002,"title_24h","request_key_expired_abc"),409)
print("NYAN TAKEOVER: private access, grants, stock, skins, bids/refunds, drops, missions, deadlines OK")
temporary.cleanup()
