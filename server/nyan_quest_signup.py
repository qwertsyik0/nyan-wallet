"""Separate Nyan Quest Mini App registration; independent of Nyan Games story rounds.

Verified Telegram initData identifies the player; only owner-signed commands
open/close a registration, and each new participant creates one relay outbox
notification in the same DB transaction. No bot token reaches the website.
"""
from __future__ import annotations

import hashlib
import hmac
import time
from datetime import datetime

from fastapi import APIRouter, Header, HTTPException, Response
from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, func, select, text
from sqlalchemy.orm import Mapped, mapped_column

from . import backend_app as core
from .telegram_relay import TelegramRelayMessage, relay_enabled

router = APIRouter()
_REGISTERED = False
_LOCK = 2026111514

class QuestRound(core.Base):
    __tablename__ = 'nyan_quest_rounds'
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    group_chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

class QuestSignup(core.Base):
    __tablename__ = 'nyan_quest_signups'
    round_id: Mapped[int] = mapped_column(Integer, ForeignKey('nyan_quest_rounds.id', ondelete='CASCADE'), primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('users.telegram_id', ondelete='CASCADE'), primary_key=True)
    username: Mapped[str] = mapped_column(String(64), nullable=False, default='')
    first_name: Mapped[str] = mapped_column(String(150), nullable=False, default='')
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

def _lock(session) -> None:
    session.execute(text('SELECT pg_advisory_xact_lock(:lock)'), {'lock': _LOCK})

def _latest(session):
    return session.scalar(select(QuestRound).order_by(QuestRound.id.desc()).limit(1))

def _verified_owner(action: str, chat: str | None, stamp: str | None, signature: str | None) -> int:
    try:
        chat_id = int(chat or '')
        timestamp = int(stamp or '')
    except ValueError as exc:
        raise HTTPException(401, 'Unauthorized') from exc
    if chat_id >= 0 or abs(int(time.time()) - timestamp) > 120:
        raise HTTPException(401, 'Unauthorized')
    token = (core.BOT_TOKEN or '').encode()
    payload = f'nyan-quest:{action}:v1:{chat_id}:{timestamp}'.encode()
    expected = hmac.new(token, payload, hashlib.sha256).hexdigest()
    if not signature or not hmac.compare_digest(signature, expected):
        raise HTTPException(401, 'Unauthorized')
    return chat_id

def _relay_ok() -> None:
    if not relay_enabled() or core.OWNER_TELEGRAM_ID is None:
        raise HTTPException(503, 'уведомления владельцу недоступны: проверь Telegram Relay')

@router.get('/api/nyan-quest/status')
def quest_status(response: Response, x_telegram_init_data: str | None = Header(default=None, alias='X-Telegram-Init-Data')):
    response.headers['Cache-Control'] = 'private, no-store'
    player = core.verify_init_data(x_telegram_init_data or '')
    user_id = int(player['id'])
    with core.SessionLocal() as session:
        round_ = _latest(session)
        if round_ is None:
            return {'ok': True, 'phase': 'idle', 'joined': False, 'round_id': None,
                    'players': 0, 'username': player.get('username'), 'first_name': player.get('first_name')}
        joined = session.get(QuestSignup, (round_.id, user_id)) is not None
        count = session.scalar(select(func.count(QuestSignup.telegram_id)).where(QuestSignup.round_id == round_.id)) or 0
        return {'ok': True, 'phase': round_.status, 'joined': joined,
                'round_id': round_.id, 'players': int(count),
                'username': player.get('username'), 'first_name': player.get('first_name')}

@router.post('/api/nyan-quest/join')
def quest_join(response: Response, x_telegram_init_data: str | None = Header(default=None, alias='X-Telegram-Init-Data')):
    response.headers['Cache-Control'] = 'private, no-store'
    player = core.verify_init_data(x_telegram_init_data or '')
    _relay_ok()
    core.get_or_create_user(player)
    user_id = int(player['id'])
    username = str(player.get('username') or '').strip()[:64]
    first_name = str(player.get('first_name') or 'Участник')[:150]
    created = False
    with core.SessionLocal.begin() as session:
        _lock(session)
        round_ = _latest(session)
        if not round_ or round_.status != 'registration':
            raise HTTPException(409, 'запись на квест закрыта')
        if session.get(QuestSignup, (round_.id, user_id)) is None:
            session.add(QuestSignup(round_id=round_.id, telegram_id=user_id, username=username,
                                    first_name=first_name, joined_at=core.now_utc()))
            who = f'@{username}' if username else f'{first_name} (без @username)'
            session.add(TelegramRelayMessage(
                source_key=f'nyan-quest-owner:{round_.id}:{user_id}',
                chat_id=int(core.OWNER_TELEGRAM_ID),
                body=f'🩸 НОВАЯ ЗАПИСЬ В NYAN QUEST\n\nучастник: {who}\ntelegram id: {user_id}\nнабор №{round_.id}',
                state='pending', attempts=0, created_at=core.now_utc(),
            ))
            created = True
        rid = round_.id
    return {'ok': True, 'joined': True, 'new': created, 'round_id': rid}

@router.post('/api/internal/nyan-quest/open')
def quest_open(x_nyan_quest_chat: str | None = Header(default=None, alias='X-Nyan-Quest-Chat'),
               x_nyan_quest_time: str | None = Header(default=None, alias='X-Nyan-Quest-Time'),
               x_nyan_quest_signature: str | None = Header(default=None, alias='X-Nyan-Quest-Signature')):
    chat_id = _verified_owner('open', x_nyan_quest_chat, x_nyan_quest_time, x_nyan_quest_signature)
    _relay_ok()
    with core.SessionLocal.begin() as session:
        _lock(session)
        current = _latest(session)
        if current and current.status == 'registration':
            raise HTTPException(409, f'набор №{current.id} уже открыт')
        item = QuestRound(group_chat_id=chat_id, status='registration', created_at=core.now_utc())
        session.add(item)
        session.flush()
        rid = item.id
    return {'ok': True, 'round_id': rid}

@router.post('/api/internal/nyan-quest/close')
def quest_close(x_nyan_quest_chat: str | None = Header(default=None, alias='X-Nyan-Quest-Chat'),
                x_nyan_quest_time: str | None = Header(default=None, alias='X-Nyan-Quest-Time'),
                x_nyan_quest_signature: str | None = Header(default=None, alias='X-Nyan-Quest-Signature')):
    chat_id = _verified_owner('close', x_nyan_quest_chat, x_nyan_quest_time, x_nyan_quest_signature)
    with core.SessionLocal.begin() as session:
        _lock(session)
        current = _latest(session)
        if not current or current.status != 'registration':
            raise HTTPException(409, 'сейчас нет открытого набора')
        if current.group_chat_id != chat_id:
            raise HTTPException(403, 'для закрытия укажи тот же чат, где набор был открыт')
        current.status = 'closed'
        current.closed_at = core.now_utc()
        count = session.scalar(select(func.count(QuestSignup.telegram_id)).where(QuestSignup.round_id == current.id)) or 0
        rid = current.id
    return {'ok': True, 'round_id': rid, 'players': int(count)}

def register_nyan_quest_signup(app) -> None:
    global _REGISTERED
    if _REGISTERED:
        return
    QuestRound.__table__.create(bind=core.engine, checkfirst=True)
    QuestSignup.__table__.create(bind=core.engine, checkfirst=True)
    app.include_router(router)
    _REGISTERED = True
