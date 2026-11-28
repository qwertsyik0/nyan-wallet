"""Isolated reward tests; never imports production server startup."""
import sys, types, importlib.util
from pathlib import Path
from datetime import datetime, timezone
from sqlalchemy import create_engine,MetaData,Table,Column,BigInteger,Integer,String,DateTime,Text,select,func
root=Path(__file__).resolve().parents[1]
core=types.ModuleType('server.backend_app');core.engine=create_engine('sqlite://');md=MetaData()
u=Table('users',md,Column('telegram_id',BigInteger,primary_key=True),Column('balance',Integer))
t=Table('transactions',md,Column('id',Integer,primary_key=True),Column('telegram_id',BigInteger),Column('amount',Integer),Column('operation_type',String),Column('description',Text),Column('created_at',DateTime))
class User:
    __table__=u;telegram_id=u.c.telegram_id;balance=u.c.balance
class Transaction:
    __table__=t
core.User=User;core.Transaction=Transaction;core.now_utc=lambda:datetime.now(timezone.utc)
def verify(raw):
    if not raw: raise ValueError('auth required')
    return {'id':int(raw)}
core.verify_init_data=verify

def create(tg):
    with core.engine.begin() as c:
        if not c.execute(select(u).where(u.c.telegram_id==tg['id'])).first():
            c.execute(u.insert().values(telegram_id=tg['id'],balance=0))
core.get_or_create_user=create
pkg=types.ModuleType('server');pkg.__path__=[str(root/'server')];sys.modules['server']=pkg;sys.modules['server.backend_app']=core
spec=importlib.util.spec_from_file_location('server.world_intro',root/'server/world_intro.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
md.create_all(core.engine);module.m.create_all(core.engine)
for uid,answer in [(1,'yes'),(2,'no'),(3,'partly'),(4,'what')]:
    r=module.answer(module.Answer(answer=answer),str(uid))
    assert r['rewarded']==(answer=='yes')
    assert module.answer(module.Answer(answer='yes'),str(uid))['answer']==answer
    if uid!=1:
        try:
            module.claim(module.Claim(acknowledged=False),str(uid));assert False
        except Exception as e: assert getattr(e,'status_code',None)==400
    for _ in range(3): module.claim(module.Claim(acknowledged=True),str(uid))
with core.engine.connect() as c:
    assert c.execute(select(u.c.balance).order_by(u.c.telegram_id)).scalars().all()==[370]*4
    assert c.execute(select(func.count()).select_from(t)).scalar_one()==4
try:
    module.claim(module.Claim(acknowledged=True),'5');assert False
except Exception as e: assert getattr(e,'status_code',None)==400
try:
    module.Answer(answer='invalid');assert False
except ValueError: pass
print('PASS: all answers, immutable response, acknowledgement, claim before answer, exactly one reward and history entry')
