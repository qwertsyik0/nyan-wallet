"""One survey bonus per Telegram user, credited atomically with wallet history."""
from typing import Literal
from fastapi import APIRouter, Header, HTTPException, Response
from pydantic import BaseModel, ConfigDict
from sqlalchemy import BigInteger, Boolean, Column, DateTime, MetaData, String, Table, select
from . import backend_app as core

m = MetaData()
responses = Table('world_intro_responses', m,
    Column('telegram_id', BigInteger, primary_key=True),
    Column('answer', String(16), nullable=False),
    Column('read_intro', Boolean, nullable=False, default=False),
    Column('rewarded', Boolean, nullable=False, default=False),
    Column('created_at', DateTime(timezone=True), nullable=False))
router = APIRouter(prefix='/api/world-intro', tags=['World introduction'])
REWARD = 370
class Answer(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    answer: Literal['yes','no','partly','what']
class Claim(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    acknowledged: bool

def identity(raw):
    tg = core.verify_init_data(raw or '')
    core.get_or_create_user(tg)
    return int(tg['id'])

def award(conn, uid):
    conn.execute(core.User.__table__.update().where(core.User.telegram_id == uid)
                 .values(balance=core.User.balance + REWARD))
    conn.execute(core.Transaction.__table__.insert().values(
        telegram_id=uid, amount=REWARD, operation_type='world_intro_reward',
        description='Знакомство с Nyan World', created_at=core.now_utc()))
    conn.execute(responses.update().where(responses.c.telegram_id == uid).values(rewarded=True))

@router.get('/status')
def status(response: Response, x_telegram_init_data: str = Header(default='')):
    uid = identity(x_telegram_init_data)
    response.headers['Cache-Control'] = 'no-store'
    with core.engine.connect() as conn:
        row = conn.execute(select(responses).where(responses.c.telegram_id == uid)).mappings().first()
        return {'ok': True, 'answer': row['answer'] if row else None,
                'rewarded': bool(row and row['rewarded']), 'reward': REWARD}

@router.post('/answer')
def answer(p: Answer, x_telegram_init_data: str = Header(default='')):
    uid = identity(x_telegram_init_data)
    with core.engine.begin() as conn:
        # Lock an existing user row before checking the unique response: concurrent
        # first answers and claims serialize without a missing-row race.
        conn.execute(select(core.User.telegram_id).where(core.User.telegram_id == uid).with_for_update()).one()
        row = conn.execute(select(responses).where(responses.c.telegram_id == uid)).mappings().first()
        if row:
            return {'ok': True, 'answer': row['answer'], 'rewarded': row['rewarded'], 'reward': REWARD}
        conn.execute(responses.insert().values(telegram_id=uid, answer=p.answer,
            read_intro=False, rewarded=False, created_at=core.now_utc()))
        if p.answer == 'yes':
            award(conn, uid)
        return {'ok': True, 'answer': p.answer, 'rewarded': p.answer == 'yes', 'reward': REWARD}

@router.post('/claim')
def claim(p: Claim, x_telegram_init_data: str = Header(default='')):
    uid = identity(x_telegram_init_data)
    if not p.acknowledged:
        raise HTTPException(400, 'Поставь галочку «ознакомился»')
    with core.engine.begin() as conn:
        conn.execute(select(core.User.telegram_id).where(core.User.telegram_id == uid).with_for_update()).one()
        row = conn.execute(select(responses).where(responses.c.telegram_id == uid)).mappings().first()
        if not row:
            raise HTTPException(400, 'Сначала ответь на вопрос')
        if not row['rewarded']:
            conn.execute(responses.update().where(responses.c.telegram_id == uid).values(read_intro=True))
            award(conn, uid)
        return {'ok': True, 'rewarded': True, 'reward': REWARD}

def register_world_intro(app):
    m.create_all(core.engine)
    app.include_router(router)
