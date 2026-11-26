"""Payment requests, wishlists, scheduled catalog prices and owner grant drafts."""
import json,secrets
from datetime import datetime,timezone,timedelta
from uuid import UUID
from fastapi import APIRouter,Header,HTTPException
from pydantic import BaseModel,Field,ConfigDict
from sqlalchemy import MetaData,Table,Column,Integer,BigInteger,String,Text,DateTime,UniqueConstraint,select,func
from sqlalchemy.exc import IntegrityError
from . import backend_app as core
from . import nyan_world as w
from .extended_features import Reward,SpendRequest,audit
router=APIRouter(prefix='/api/wallet-plus',tags=['Wallet plus']);m=MetaData()
profiles=Table('wp_profiles',m,Column('user_id',BigInteger,primary_key=True),Column('wishlist_token',String(40),nullable=False,unique=True),Column('frozen',Integer,nullable=False,default=0))
wishes=Table('wp_wishes',m,Column('user_id',BigInteger,primary_key=True),Column('reward_id',Integer,primary_key=True))
requests=Table('wp_payment_requests',m,Column('token',String(40),primary_key=True),Column('user_id',BigInteger,nullable=False),Column('amount',Integer,nullable=False),Column('reason',String(200),nullable=False),Column('status',String(16),nullable=False),Column('paid_by',BigInteger),Column('transfer_id',String(40)),Column('created_at',DateTime(timezone=True),nullable=False),Column('expires_at',DateTime(timezone=True),nullable=False))
sales=Table('wp_sales',m,Column('id',Integer,primary_key=True),Column('reward_id',Integer,nullable=False),Column('percent',Integer,nullable=False),Column('starts_at',DateTime(timezone=True),nullable=False),Column('ends_at',DateTime(timezone=True),nullable=False),Column('cancelled',Integer,nullable=False,default=0),Column('created_by',BigInteger,nullable=False))
drafts=Table('wp_grant_drafts',m,Column('id',Integer,primary_key=True),Column('operation_id',String(36),unique=True,nullable=False),Column('created_by',BigInteger,nullable=False),Column('data',Text,nullable=False),Column('reason',String(200),nullable=False),Column('state',String(16),nullable=False),Column('created_at',DateTime(timezone=True),nullable=False),Column('executed_at',DateTime(timezone=True)))
notes=Table('wp_operation_notes',m,Column('user_id',BigInteger,primary_key=True),Column('transaction_id',Integer,primary_key=True),Column('kind',String(16),primary_key=True),Column('body',String(1000),nullable=False),Column('updated_at',DateTime(timezone=True),nullable=False))
def auth(raw):return core.verify_init_data(raw or '')
def now():return datetime.now(timezone.utc)
def aware(d):return d.replace(tzinfo=timezone.utc) if d.tzinfo is None else d

def profile(c,uid,lock=True):
 if lock:
  if not c.execute(select(core.User.telegram_id).where(core.User.telegram_id==uid).with_for_update()).first():w.fail('Сначала откройте главный экран',404)
 row=c.execute(select(profiles).where(profiles.c.user_id==uid)).mappings().one_or_none()
 if not row:
  c.execute(profiles.insert().values(user_id=uid,wishlist_token=secrets.token_urlsafe(18),frozen=0));row=c.execute(select(profiles).where(profiles.c.user_id==uid)).mappings().one()
 return row

def effective_cost(c,reward_id,base):
 active=c.execute(select(sales.c.percent).where(sales.c.reward_id==reward_id,sales.c.cancelled==0,sales.c.starts_at<=now(),sales.c.ends_at>now()).order_by(sales.c.percent.desc()).limit(1)).scalar_one_or_none()
 return max(1,int(base)*(100-active)//100) if active else int(base)
def check_frozen(session,uid):
 if session.connection().execute(select(profiles.c.frozen).where(profiles.c.user_id==uid)).scalar_one_or_none():w.fail('Исходящие переводы заморожены. Снимите ограничение в настройках кошелька',423)
def payment_guard(session,token,payer,payload):
 r=session.connection().execute(select(requests).where(requests.c.token==token).with_for_update()).mappings().one_or_none()
 if not r:w.fail('Запрос не найден',404)
 if r['status']=='paid' and r['paid_by']!=payer:w.fail('Запрос уже оплачен',409)
 if r['status'] not in {'pending','paid'} or (r['status']=='pending' and aware(r['expires_at'])<=now()):w.fail('Запрос отменён или истёк',409)
 if str(r['user_id'])!=payload.recipient or r['amount']!=payload.amount:w.fail('Данные запроса изменились',409)
 return r

def payment_finish(session,token,payer,transfer_id):
 if token:session.connection().execute(requests.update().where(requests.c.token==token).values(status='paid',paid_by=payer,transfer_id=transfer_id))

class Frozen(BaseModel):
 frozen:bool
class Wish(BaseModel):
 reward_ids:list[int]=Field(max_length=50)
class Request(BaseModel):
 amount:int=Field(ge=1,le=100000,strict=True)
 reason:str=Field(min_length=1,max_length=200)
class ConfirmPay(BaseModel):
 amount:int=Field(ge=1,strict=True)
class Sale(BaseModel):
 reward_id:int=Field(gt=0,strict=True)
 percent:int=Field(ge=1,le=95,strict=True)
 starts_at:datetime
 ends_at:datetime
class GrantRow(BaseModel):
 user_id:int=Field(gt=0,strict=True)
 amount:int=Field(ge=1,le=1000000,strict=True)
class Draft(BaseModel):
 operation_id:UUID
 rows:list[GrantRow]=Field(min_length=1,max_length=100)
 reason:str=Field(min_length=1,max_length=200)
class ConfirmDraft(BaseModel):
 total:int=Field(ge=1,strict=True)
 count:int=Field(ge=1,strict=True)
class Note(BaseModel):
 transaction_id:int=Field(gt=0,strict=True)
 kind:str=Field(pattern='^(personal|staff)$')
 body:str=Field(max_length=1000)

def request_view(c,r,viewer):
 return {'token':r['token'],'user_id':r['user_id'],'label':w.identity(c,r['user_id']),'amount':r['amount'],'reason':r['reason'],'status':'expired' if r['status']=='pending' and aware(r['expires_at'])<=now() else r['status'],'expires_at':r['expires_at'],'is_own':r['user_id']==viewer,'transfer_id':r['transfer_id'],'link':'https://t.me/nyancash_bot?startapp=payreq_'+r['token']}

@router.get('/state')
def state(x_telegram_init_data:str=Header(default='')):
 u=auth(x_telegram_init_data);uid=u['id'];owner=core.is_owner(uid)
 with core.engine.begin() as c:
  p=profile(c,uid);rw=Reward.__table__;catalog=[dict(r) for r in c.execute(select(rw.c.id,rw.c.title,rw.c.cost,rw.c.is_active).order_by(rw.c.id)).mappings()]
  for r in catalog:r['base_cost']=r['cost'];r['cost']=effective_cost(c,r['id'],r['cost'])
  tx=core.Transaction.__table__;rows=[dict(r) for r in c.execute(select(tx).where(tx.c.telegram_id==uid).order_by(tx.c.id.desc()).limit(100)).mappings()]
  ownnotes=[dict(r) for r in c.execute(select(notes).where(notes.c.user_id==uid)).mappings()]
  myrequests=[request_view(c,r,uid) for r in c.execute(select(requests).where(requests.c.user_id==uid).order_by(requests.c.created_at.desc()).limit(100)).mappings()]
  return {'ok':True,'is_owner':owner,'frozen':bool(p['frozen']),'wishlist_link':'https://t.me/nyancash_bot?startapp=wishlist_'+p['wishlist_token'],'wish_ids':list(c.execute(select(wishes.c.reward_id).where(wishes.c.user_id==uid)).scalars()),'catalog':catalog,'requests':myrequests,'transactions':rows,'notes':ownnotes,'sales':[dict(r) for r in c.execute(select(sales).order_by(sales.c.starts_at.desc())).mappings()] if owner else [],'drafts':[dict(r) for r in c.execute(select(drafts).order_by(drafts.c.id.desc()).limit(100)).mappings()] if owner else [],'server_time':now()}
@router.post('/freeze')
def freeze(p:Frozen,x_telegram_init_data:str=Header(default='')):
 u=auth(x_telegram_init_data)
 with core.engine.begin() as c:
  profile(c,u['id']);c.execute(profiles.update().where(profiles.c.user_id==u['id']).values(frozen=int(p.frozen)))
  w.notify(c,u['id'],'Исходящие переводы '+('заморожены' if p.frozen else 'снова доступны'),mirror=False)
 return {'ok':True}
@router.post('/wishlist')
def wishlist(p:Wish,x_telegram_init_data:str=Header(default='')):
 u=auth(x_telegram_init_data)
 if any(type(x)is not int or x<=0 for x in p.reward_ids):w.fail('Некорректная награда')
 ids=set(p.reward_ids)
 with core.engine.begin() as c:
  profile(c,u['id'])
  if len(list(c.execute(select(Reward.id).where(Reward.id.in_(ids))).scalars()))!=len(ids):w.fail('Награда не найдена')
  c.execute(wishes.delete().where(wishes.c.user_id==u['id']))
  if ids:c.execute(wishes.insert(),[{'user_id':u['id'],'reward_id':x} for x in ids])
 return {'ok':True}
@router.get('/wishlist/{token}')
def shared_wishlist(token:str,x_telegram_init_data:str=Header(default='')):
 auth(x_telegram_init_data)
 with core.engine.connect() as c:
  uid=c.execute(select(profiles.c.user_id).where(profiles.c.wishlist_token==token)).scalar_one_or_none()
  if not uid:w.fail('Список не найден',404)
  rw=Reward.__table__;rows=[dict(r) for r in c.execute(select(rw.c.id,rw.c.title,rw.c.cost,rw.c.is_active).join(wishes,wishes.c.reward_id==rw.c.id).where(wishes.c.user_id==uid)).mappings()]
  for r in rows:r['cost']=effective_cost(c,r['id'],r['cost'])
  return {'ok':True,'user_id':uid,'label':w.identity(c,uid),'rewards':rows}
@router.post('/request')
def create_request(p:Request,x_telegram_init_data:str=Header(default='')):
 u=auth(x_telegram_init_data)
 if not p.reason.strip():w.fail('Укажите причину')
 with core.engine.begin() as c:
  profile(c,u['id']);pending=c.execute(select(func.count()).select_from(requests).where(requests.c.user_id==u['id'],requests.c.status=='pending',requests.c.expires_at>now())).scalar_one()
  if pending>=30:w.fail('Сначала закройте предыдущие запросы')
  token=secrets.token_urlsafe(18);c.execute(requests.insert().values(token=token,user_id=u['id'],amount=p.amount,reason=p.reason.strip(),status='pending',created_at=now(),expires_at=now()+timedelta(days=7)))
  return {'ok':True,'request':request_view(c,c.execute(select(requests).where(requests.c.token==token)).mappings().one(),u['id'])}
@router.get('/request/{token}')
def get_request(token:str,x_telegram_init_data:str=Header(default='')):
 uid=auth(x_telegram_init_data)['id']
 with core.engine.connect() as c:
  r=c.execute(select(requests).where(requests.c.token==token)).mappings().one_or_none()
  if not r:w.fail('Запрос не найден',404)
  return {'ok':True,'request':request_view(c,r,uid)}
@router.post('/request/{token}/cancel')
def cancel_request(token:str,x_telegram_init_data:str=Header(default='')):
 uid=auth(x_telegram_init_data)['id']
 with core.engine.begin() as c:
  r=c.execute(select(requests).where(requests.c.token==token,requests.c.user_id==uid).with_for_update()).mappings().one_or_none()
  if not r:w.fail('Запрос не найден',404)
  if r['status']=='paid':w.fail('Запрос уже оплачен',409)
  c.execute(requests.update().where(requests.c.token==token).values(status='cancelled'))
 return {'ok':True}
@router.post('/request/{token}/pay')
def pay(token:str,p:ConfirmPay,x_telegram_init_data:str=Header(default='')):
 user=auth(x_telegram_init_data)
 with core.engine.connect() as c:
  r=c.execute(select(requests).where(requests.c.token==token)).mappings().one_or_none()
  if not r:w.fail('Запрос не найден',404)
  if r['amount']!=p.amount:w.fail('Сумма запроса не совпадает',409)
 from .transfers import TransferRequest,transfer_lapcoins
 payload=TransferRequest(recipient=str(r['user_id']),amount=r['amount'],note='Запрос лапкоинов',idempotency_key='payreq_'+token)
 result=transfer_lapcoins(user,payload,payment_token=token)
 return {'ok':True,'transfer':result}
@router.post('/owner/sale')
def sale(p:Sale,x_telegram_init_data:str=Header(default='')):
 user=auth(x_telegram_init_data);core.require_owner(user)
 if p.starts_at.tzinfo is None or p.ends_at.tzinfo is None or p.ends_at<=p.starts_at or p.ends_at<=now() or p.ends_at-p.starts_at>timedelta(days=180):w.fail('Проверьте сроки акции и часовой пояс')
 with core.engine.begin() as c:
  if not c.execute(select(Reward.id).where(Reward.id==p.reward_id).with_for_update()).first():w.fail('Награда не найдена',404)
  if c.execute(select(sales.c.id).where(sales.c.reward_id==p.reward_id,sales.c.cancelled==0,sales.c.starts_at<p.ends_at,sales.c.ends_at>p.starts_at)).first():w.fail('Для награды уже есть акция в это время',409)
  c.execute(sales.insert().values(reward_id=p.reward_id,percent=p.percent,starts_at=p.starts_at,ends_at=p.ends_at,cancelled=0,created_by=user['id']))
 return {'ok':True}
@router.post('/owner/sale/{sid}/cancel')
def cancel_sale(sid:int,x_telegram_init_data:str=Header(default='')):
 user=auth(x_telegram_init_data);core.require_owner(user)
 with core.engine.begin() as c:
  row=c.execute(select(sales).where(sales.c.id==sid)).mappings().one_or_none()
  if not row:w.fail('Акция не найдена',404)
  c.execute(select(Reward.id).where(Reward.id==row['reward_id']).with_for_update()).first();c.execute(sales.update().where(sales.c.id==sid).values(cancelled=1))
 return {'ok':True}
@router.post('/owner/draft')
def prepare(p:Draft,x_telegram_init_data:str=Header(default='')):
 user=auth(x_telegram_init_data);core.require_owner(user);ids=[x.user_id for x in p.rows]
 if len(set(ids))!=len(ids):w.fail('Повторяющиеся ID. Удалите дубли')
 if any(core.is_owner(x) for x in ids):w.fail('Баланс владельца безлимитный, исключите его из списка')
 if not p.reason.strip():w.fail('Укажите причину')
 data=[{'user_id':r.user_id,'amount':r.amount} for r in p.rows]
 if sum(r.amount for r in p.rows)>50000000:w.fail('Слишком большая сумма одной выдачи')
 try:
  with core.engine.begin() as c:
   old=c.execute(select(drafts).where(drafts.c.operation_id==str(p.operation_id))).mappings().one_or_none()
   if old:
    if old['data']!=w.pack(data) or old['reason']!=p.reason.strip() or old['created_by']!=user['id']:w.fail('Ключ использован',409)
    return {'ok':True,'id':old['id']}
   if len(list(c.execute(select(core.User.telegram_id).where(core.User.telegram_id.in_(ids))).scalars()))!=len(ids):w.fail('Не все пользователи найдены. Ничего не сохранено',404)
   did=c.execute(drafts.insert().values(operation_id=str(p.operation_id),created_by=user['id'],data=w.pack(data),reason=p.reason.strip(),state='draft',created_at=now())).inserted_primary_key[0]
   return {'ok':True,'id':did}
 except IntegrityError:w.fail('Повтор операции. Обновите список',409)
@router.get('/owner/draft/{did}')
def draft_preview(did:int,x_telegram_init_data:str=Header(default='')):
 user=auth(x_telegram_init_data);core.require_owner(user)
 with core.engine.connect() as c:
  d=c.execute(select(drafts).where(drafts.c.id==did)).mappings().one_or_none()
  if not d:w.fail('Черновик не найден',404)
  rows=json.loads(d['data'])
  for r in rows:r['label']=w.identity(c,r['user_id'])
  return {'ok':True,'id':did,'rows':rows,'total':sum(r['amount'] for r in rows),'count':len(rows),'reason':d['reason'],'state':d['state']}
@router.post('/owner/draft/{did}/confirm')
def execute_draft(did:int,p:ConfirmDraft,x_telegram_init_data:str=Header(default='')):
 user=auth(x_telegram_init_data);core.require_owner(user)
 with core.SessionLocal.begin() as session:
  c=session.connection();d=c.execute(select(drafts).where(drafts.c.id==did).with_for_update()).mappings().one_or_none()
  if not d:w.fail('Черновик не найден',404)
  rows=json.loads(d['data']);total=sum(r['amount'] for r in rows)
  if p.total!=total or p.count!=len(rows):w.fail('Параметры подтверждения не совпадают',409)
  if d['state']=='executed':return {'ok':True,'repeated':True}
  if d['state']!='draft':w.fail('Черновик отменён',409)
  users={u.telegram_id:u for u in session.scalars(select(core.User).where(core.User.telegram_id.in_([r['user_id'] for r in rows])).order_by(core.User.telegram_id).with_for_update()).all()}
  if len(users)!=len(rows):w.fail('Пользователь больше недоступен',409)
  for r in rows:
   users[r['user_id']].balance+=r['amount'];session.add(core.Transaction(telegram_id=r['user_id'],amount=r['amount'],operation_type='mass_grant',description=f"Черновик #{did}: {d['reason']}",created_at=now()))
  audit(session,'draft_mass_grant',None,f'Черновик #{did}: {len(rows)} пользователей, {total} лапкоинов');session.flush()
  c.execute(drafts.update().where(drafts.c.id==did).values(state='executed',executed_at=now()))
 return {'ok':True,'total':total,'count':len(rows)}
@router.post('/owner/draft/{did}/cancel')
def cancel_draft(did:int,x_telegram_init_data:str=Header(default='')):
 user=auth(x_telegram_init_data);core.require_owner(user)
 with core.engine.begin() as c:
  d=c.execute(select(drafts).where(drafts.c.id==did).with_for_update()).mappings().one_or_none()
  if not d:w.fail('Черновик не найден',404)
  if d['state']=='executed':w.fail('Начисление уже выполнено',409)
  c.execute(drafts.update().where(drafts.c.id==did).values(state='cancelled'))
 return {'ok':True}
@router.post('/note')
def note(p:Note,x_telegram_init_data:str=Header(default='')):
 user=auth(x_telegram_init_data);uid=user['id']
 if p.kind=='staff':core.require_owner(user)
 with core.engine.begin() as c:
  profile(c,uid);tx=c.execute(select(core.Transaction.__table__).where(core.Transaction.id==p.transaction_id)).mappings().one_or_none()
  if not tx or (p.kind=='personal' and tx['telegram_id']!=uid):w.fail('Операция не найдена',404)
  c.execute(notes.delete().where(notes.c.user_id==uid,notes.c.transaction_id==p.transaction_id,notes.c.kind==p.kind))
  if p.body.strip():c.execute(notes.insert().values(user_id=uid,transaction_id=p.transaction_id,kind=p.kind,body=p.body.strip(),updated_at=now()))
 return {'ok':True}
def register_wallet_plus(app):
 m.create_all(core.engine)
 core.wallet_effective_cost=effective_cost;core.wallet_check_frozen=check_frozen;core.wallet_payment_guard=payment_guard;core.wallet_payment_finish=payment_finish
 app.include_router(router)
