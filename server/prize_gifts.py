"""Gift purchases use the existing prize queue; refunds belong to the payer."""
from uuid import UUID
from fastapi import APIRouter,Header,HTTPException
from pydantic import BaseModel,Field,ConfigDict
from sqlalchemy import MetaData,Table,Column,Integer,BigInteger,String,Text,DateTime,UniqueConstraint,select,event,inspect
from sqlalchemy.exc import IntegrityError
from . import backend_app as core
from . import nyan_world as w
from .extended_features import Reward,SpendRequest
from .advanced_features import RequestMeta,catalog_item
from .vip import is_vip_reward
router=APIRouter(prefix='/api/prize-gifts',tags=['Prize gifts']);m=MetaData()
gifts=Table('prize_gifts',m,Column('request_id',Integer,primary_key=True),Column('sender_id',BigInteger,nullable=False),Column('recipient_id',BigInteger,nullable=False),Column('operation_id',String(36),nullable=False),Column('message',Text,nullable=False),Column('created_at',DateTime(timezone=True),nullable=False),UniqueConstraint('sender_id','operation_id',name='uq_prize_gift_operation'))
class Buy(BaseModel):
 model_config=ConfigDict(extra='forbid')
 operation_id:UUID
 reward_id:int=Field(gt=0,strict=True)
 recipient_id:int=Field(gt=0,strict=True)
 expected_cost:int=Field(gt=0,strict=True)
 message:str=Field(default='',max_length=500)
class Status(BaseModel):
 status:str
 comment:str=Field(default='',max_length=1000)
def raw(s):return core.verify_init_data(s or '')
def guard(mapper,c,target):
 if not inspect(target).attrs.status.history.has_changes():return
 g=c.execute(select(gifts).where(gifts.c.request_id==target.id)).mappings().first()
 if not g:return
 old=c.execute(select(SpendRequest.status).where(SpendRequest.id==target.id)).scalar_one()
 if old in {'fulfilled','cancelled'} and old!=target.status:raise HTTPException(409,'Выданный или отменённый подарок нельзя открыть повторно')
 if old=='processing' and target.status=='pending':raise HTTPException(409,'Подарок уже в работе')
def on_status(mapper,c,target):
 if not inspect(target).attrs.status.history.has_changes():return
 g=c.execute(select(gifts).where(gifts.c.request_id==target.id)).mappings().first()
 if not g:return
 labels={'pending':'создан','processing':'в работе','fulfilled':'выдан','cancelled':'отменён'}
 meta=c.execute(select(RequestMeta.owner_comment).where(RequestMeta.request_id==target.id)).scalar_one_or_none()
 w.notify(c,g['recipient_id'],f"Подарок #{target.id}: {target.reward_title}\nСтатус: {labels.get(target.status,target.status)}\n{meta or ''}",mirror=False)
@router.get('/state')
def state(x_telegram_init_data:str=Header(default='')):
 u=raw(x_telegram_init_data);uid=u['id'];owner=core.is_owner(uid)
 with core.SessionLocal() as session:
  catalog=[catalog_item(session,r) for r in session.scalars(select(Reward).where(Reward.is_active==True)).all() if not is_vip_reward(r.title)]
  with core.engine.connect() as c:
   q=select(gifts,SpendRequest.reward_title,SpendRequest.cost,SpendRequest.status,SpendRequest.processed_at,RequestMeta.owner_comment).join(SpendRequest,SpendRequest.id==gifts.c.request_id).outerjoin(RequestMeta,RequestMeta.request_id==gifts.c.request_id)
   if not owner:q=q.where((gifts.c.sender_id==uid)|(gifts.c.recipient_id==uid))
   rows=[dict(r) for r in c.execute(q.order_by(gifts.c.request_id.desc()).limit(300)).mappings()]
   for r in rows:
    r['sender']=w.identity(c,r['sender_id']);r['recipient']=w.identity(c,r['recipient_id'])
  user=session.get(core.User,uid)
  return {'ok':True,'is_owner':owner,'balance':user.balance if user else 0,'catalog':[x for x in catalog if x['available']],'gifts':rows}
@router.get('/recipient/{uid}')
def recipient(uid:int,x_telegram_init_data:str=Header(default='')):
 raw(x_telegram_init_data)
 with core.engine.connect() as c:
  user=c.execute(select(core.User.telegram_id).where(core.User.telegram_id==uid)).first()
  if not user:raise HTTPException(404,'Получатель должен сначала открыть кошелёк')
  return {'ok':True,'id':uid,'label':w.identity(c,uid)}
@router.post('/buy')
def buy(p:Buy,x_telegram_init_data:str=Header(default='')):
 u=raw(x_telegram_init_data);uid=u['id']
 if p.recipient_id==uid:raise HTTPException(400,'Выберите другого получателя')
 if core.is_owner(uid):raise HTTPException(400,'Подарки из каталога оплачиваются с обычного баланса. Выдайте подарок от владельца через управление наградами')
 try:
  with core.SessionLocal.begin() as session:
   locked=session.scalars(select(core.User).where(core.User.telegram_id.in_(sorted([uid,p.recipient_id]))).order_by(core.User.telegram_id).with_for_update()).all();users={x.telegram_id:x for x in locked}
   if len(users)!=2:raise HTTPException(404,'Получатель должен сначала открыть Nyan Wallet')
   c=session.connection();old=c.execute(select(gifts).where(gifts.c.sender_id==uid,gifts.c.operation_id==str(p.operation_id))).mappings().first()
   if old:
    req=session.get(SpendRequest,old['request_id'])
    if old['recipient_id']!=p.recipient_id or req.reward_id!=p.reward_id or req.cost!=p.expected_cost or old['message']!=p.message:raise HTTPException(409,'Ключ уже использован')
    return {'ok':True,'request_id':req.id,'repeated':True}
   reward=session.scalar(select(Reward).where(Reward.id==p.reward_id).with_for_update())
   if not reward or is_vip_reward(reward.title) or not catalog_item(session,reward)['available']:raise HTTPException(400,'Награда недоступна для подарка')
   effective_cost=getattr(core,'wallet_effective_cost',lambda c,rid,cost:cost)
   price=effective_cost(c,reward.id,reward.cost)
   if price!=p.expected_cost:raise HTTPException(409,'Цена изменилась. Обновите список и подтвердите новую стоимость')
   if users[uid].balance<price:raise HTTPException(409,'Недостаточно лапкоинов')
   users[uid].balance-=price
   req=SpendRequest(telegram_id=uid,reward_id=reward.id,reward_title=reward.title,cost=price,status='pending',created_at=w.now(),processed_at=None);session.add(req);session.flush()
   c.execute(gifts.insert().values(request_id=req.id,sender_id=uid,recipient_id=p.recipient_id,operation_id=str(p.operation_id),message=p.message,created_at=w.now()))
   session.add(RequestMeta(request_id=req.id,owner_comment=f"Подарок для {w.identity(c,p.recipient_id)} | ID: {p.recipient_id}. От: {w.identity(c,uid)}. {p.message}",updated_at=w.now()))
   session.add(core.Transaction(telegram_id=uid,amount=-price,operation_type='gift_purchase',description=f'Подарок #{req.id} для ID {p.recipient_id}: {reward.title}',created_at=w.now()));session.flush()
   for target,text in [(uid,f'Подарок #{req.id} оплачен. {reward.title}. Получатель: {w.identity(c,p.recipient_id)}'),(p.recipient_id,f'Вам заказан подарок #{req.id}: {reward.title}. От: {w.identity(c,uid)}\n{p.message}\nОжидайте выдачи продавцом.'),(core.OWNER_TELEGRAM_ID,f'Новый подарок #{req.id}: {reward.title}\nОтправитель: {w.identity(c,uid)} | ID {uid}\nПолучатель: {w.identity(c,p.recipient_id)} | ID {p.recipient_id}\nСтоимость: {price}\n{p.message}')]:
    if target:w.notify(c,target,text,mirror=False)
   return {'ok':True,'request_id':req.id,'balance':users[uid].balance}
 except IntegrityError:raise HTTPException(409,'Повтор операции. Проверьте список подарков')
@router.post('/{rid}/status')
def status(rid:int,p:Status,x_telegram_init_data:str=Header(default='')):
 u=raw(x_telegram_init_data);core.require_owner(u)
 if p.status not in {'processing','fulfilled','cancelled'}:raise HTTPException(400,'Неизвестный статус')
 with core.SessionLocal.begin() as session:
  c=session.connection();g=c.execute(select(gifts).where(gifts.c.request_id==rid)).mappings().one_or_none()
  if not g:raise HTTPException(404,'Подарок не найден')
  payer=session.scalar(select(core.User).where(core.User.telegram_id==g['sender_id']).with_for_update())
  req=session.scalar(select(SpendRequest).where(SpendRequest.id==rid).with_for_update())
  if req.status==p.status:return {'ok':True,'repeated':True}
  if req.status in {'fulfilled','cancelled'}:raise HTTPException(409,'Заявка завершена')
  meta=session.get(RequestMeta,rid)
  if meta:meta.owner_comment=(meta.owner_comment or '')+'\n'+p.comment;meta.updated_at=w.now()
  session.flush()
  if p.status=='cancelled':
   payer.balance+=req.cost;session.add(core.Transaction(telegram_id=payer.telegram_id,amount=req.cost,operation_type='reward_refund',description=f'Отмена подарка #{rid}',created_at=w.now()))
  req.status=p.status;req.processed_at=w.now() if p.status in {'fulfilled','cancelled'} else None;session.flush()
  w.notify(c,g['sender_id'],f"Подарок #{rid}: {dict(processing='в работе',fulfilled='выдан',cancelled='отменён')[p.status]}\n{p.comment}"+('\nЛапкоины возвращены отправителю.' if p.status=='cancelled' else ''),mirror=False)
  return {'ok':True}
def register_prize_gifts(app):
 m.create_all(core.engine);event.listen(SpendRequest,'before_update',guard);event.listen(SpendRequest,'after_update',on_status);app.include_router(router)

