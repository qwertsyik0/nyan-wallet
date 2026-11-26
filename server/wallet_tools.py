"""Wallet utilities: no balance mutations or automatic prize promises."""
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP
from zoneinfo import ZoneInfo
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field, ConfigDict
from sqlalchemy import Table, MetaData, Column, Integer, BigInteger, String, Text, DateTime, select, func
from sqlalchemy.exc import IntegrityError, NoSuchTableError
from server import backend_app as core

router=APIRouter(prefix='/api/wallet-tools',tags=['Wallet tools'])
m=MetaData()
goals=Table('wt_goals',m,Column('user_id',BigInteger,primary_key=True),Column('reward_id',Integer,nullable=False))
votes=Table('wt_votes',m,Column('day',String(10),primary_key=True),Column('user_id',BigInteger,primary_key=True),Column('answer',Integer,nullable=False),Column('created_at',DateTime(timezone=True),nullable=False))
bonuses=Table('wt_bonus_terms',m,Column('id',Integer,primary_key=True),Column('user_id',BigInteger,nullable=False,index=True),Column('title',String(120),nullable=False),Column('description',Text,nullable=False),Column('expires_at',DateTime(timezone=True),nullable=False),Column('created_at',DateTime(timezone=True),nullable=False))
QUESTIONS=[
 ('Что для вас важнее при покупке?', ['Цена','Гарантия','Скорость выдачи','Поддержка']),
 ('Как чаще используете лапкоины?', ['Коплю','Покупаю награды','Перевожу друзьям','Пока изучаю']),
 ('Какие награды интереснее?', ['Скидки','Оформления','Подарки','VIP']),
 ('Что удобнее получать от кошелька?', ['Короткие новости','Статус заявок','Напоминания','Ничего лишнего']),
 ('Как выбираете награду?', ['По цене','По пользе','По оформлению','По настроению']),
 ('Что помогает разобраться в новой функции?', ['Короткий пример','Описание','Подсказки внутри','Ответ поддержки']),
 ('Какой срок акции удобнее?', ['Один день','Три дня','Неделя','Без срока']),
 ('Как часто проверяете кошелёк?', ['Каждый день','Несколько раз в неделю','По уведомлению','Когда нужна награда']),
 ('Что интереснее в событиях Nyan?', ['Соревнования','Общение','Совместные задачи','Награды']),
 ('Каким должен быть идеальный подарок?', ['Практичным','Неожиданным','Редким','На выбор']),
 ('Как удобнее следить за накоплениями?', ['Цель на экране','История операций','Прогресс в процентах','Без напоминаний']),
 ('Когда пользуетесь скидками?', ['Сразу','Перед большой покупкой','По необходимости','Редко']),
 ('Что предпочитаете в интерфейсе?', ['Минимум кнопок','Все функции под рукой','Крупный текст','Больше подсказок']),
 ('Что хочется узнать о Nyan?', ['Новые функции','Как устроены награды','Будущие события','Историю проекта'])]
def now():return datetime.now(timezone.utc)
def day():return datetime.now(ZoneInfo('Europe/Moscow')).date()
def question():return QUESTIONS[day().toordinal()%len(QUESTIONS)]
def auth(raw):return int(core.verify_init_data(raw or '')['id'])
def table(c,name,optional=False):
 try:return Table(name,MetaData(),autoload_with=c)
 except NoSuchTableError:
  if optional:return None
  raise HTTPException(503,'Раздел пока не установлен: '+name)
def user(c,uid):
 t=table(c,'users');r=c.execute(select(t).where(t.c.telegram_id==uid)).mappings().one_or_none()
 if not r:raise HTTPException(404,'Сначала откройте главный экран кошелька')
 return r
def aware(d):return d.replace(tzinfo=timezone.utc) if d.tzinfo is None else d

def rate(c,uid):
 t=table(c,'vip_subscriptions',True)
 if t is not None and c.execute(select(t.c.request_id).where(t.c.telegram_id==uid,t.c.starts_at<=now(),t.c.ends_at>now()).limit(1)).first():return 8
 return 5

def poll(c,uid):
 q,options=question();key=day().isoformat()
 selected=c.execute(select(votes.c.answer).where(votes.c.day==key,votes.c.user_id==uid)).scalar_one_or_none()
 counts=[0]*len(options)
 if selected is not None:
  for answer,count in c.execute(select(votes.c.answer,func.count()).where(votes.c.day==key).group_by(votes.c.answer)):
   if 0<=answer<len(counts):counts[answer]=count
 return {'day':key,'question':q,'options':options,'answer':selected,'counts':counts if selected is not None else None,'total':sum(counts) if selected is not None else None}

class Goal(BaseModel):
 model_config=ConfigDict(extra='forbid')
 reward_id:int|None=Field(default=None,ge=1)
class Vote(BaseModel):
 model_config=ConfigDict(extra='forbid')
 day:str=Field(pattern=r'^\d{4}-\d{2}-\d{2}$')
 answer:int=Field(ge=0,le=3,strict=True)
class Purchase(BaseModel):
 model_config=ConfigDict(extra='forbid')
 rubles:Decimal=Field(gt=0,le=10000000,max_digits=10,decimal_places=2)
 discount:Decimal=Field(default=Decimal(0),ge=0,le=100,decimal_places=2)
class Bonus(BaseModel):
 model_config=ConfigDict(extra='forbid')
 user_id:int=Field(gt=0,strict=True)
 title:str=Field(min_length=1,max_length=120)
 description:str=Field(default='',max_length=2000)
 expires_at:datetime

@router.post('/calculate')
def calculate(p:Purchase,x_telegram_init_data:str=Header(default='')):
 uid=auth(x_telegram_init_data)
 with core.engine.connect() as c:
  user(c,uid);percent=rate(c,uid)
 paid=(p.rubles*(100-p.discount)/100).quantize(Decimal('.01'),rounding=ROUND_HALF_UP)
 cashback=int(paid*percent/100)
 return {'ok':True,'paid':str(paid),'saved':str(p.rubles-paid),'cashback':cashback,'rate':percent}

@router.get('/state')
def state(before_request_id:int|None=None,before_transfer_id:int|None=None,x_telegram_init_data:str=Header(default='')):
 uid=auth(x_telegram_init_data)
 with core.engine.connect() as c:
  u=user(c,uid);catalog=table(c,'reward_catalog');req=table(c,'spend_requests');meta=table(c,'spend_request_meta',True)
  rewards=[dict(r) for r in c.execute(select(catalog.c.id,catalog.c.title,catalog.c.cost,catalog.c.is_active).order_by(catalog.c.cost,catalog.c.id)).mappings()]
  gid=c.execute(select(goals.c.reward_id).where(goals.c.user_id==uid)).scalar_one_or_none()
  goal=next((r.copy() for r in rewards if r['id']==gid),None)
  if goal:
   goal['remaining']=max(0,goal['cost']-u['balance']);goal['progress']=min(100,max(0,round(u['balance']*100/max(1,goal['cost']))))
   if core.is_owner(uid):goal['remaining']=0;goal['progress']=100
  q=select(req).where(req.c.telegram_id==uid)
  if before_request_id:q=q.where(req.c.id<before_request_id)
  rows=[dict(r) for r in c.execute(q.order_by(req.c.id.desc()).limit(51)).mappings()];more_requests=len(rows)>50;rows=rows[:50]
  comments={}
  if meta is not None and rows:
   comments=dict(c.execute(select(meta.c.request_id,meta.c.owner_comment).where(meta.c.request_id.in_([r['id'] for r in rows]))).all())
  for r in rows:r['comment']=comments.get(r['id']) or ''
  tr=table(c,'wallet_transfers',True);transfers=[];more_transfers=False
  if tr is not None:
   q=select(tr).where((tr.c.sender_id==uid)|(tr.c.recipient_id==uid))
   if before_transfer_id:q=q.where(tr.c.id<before_transfer_id)
   transfers=[dict(r) for r in c.execute(q.order_by(tr.c.id.desc()).limit(51)).mappings()];more_transfers=len(transfers)>50;transfers=transfers[:50]
  terms=[dict(r) for r in c.execute(select(bonuses).where(bonuses.c.user_id==uid).order_by(bonuses.c.expires_at.desc()).limit(100)).mappings()]
  vip=table(c,'vip_subscriptions',True)
  if vip is not None:
   end=c.execute(select(func.max(vip.c.ends_at)).where(vip.c.telegram_id==uid)).scalar_one_or_none()
   if end:terms.insert(0,{'id':'vip','title':'Nyan VIP','description':'Статус VIP и его привилегии','expires_at':end})
  for r in terms:r['expired']=aware(r['expires_at'])<=now()
  return {'ok':True,'is_owner':core.is_owner(uid),'balance':u['balance'],'unlimited':core.is_owner(uid),'cashback_rate':rate(c,uid),'rewards':rewards,'goal':goal,'requests':rows,'transfers':transfers,'bonuses':terms,'poll':poll(c,uid),'server_time':now(),'more_requests':more_requests,'more_transfers':more_transfers}

@router.post('/goal')
def save_goal(p:Goal,x_telegram_init_data:str=Header(default='')):
 uid=auth(x_telegram_init_data)
 with core.engine.begin() as c:
  users=table(c,'users');c.execute(select(users.c.telegram_id).where(users.c.telegram_id==uid).with_for_update()).first();user(c,uid)
  if p.reward_id is not None:
   cat=table(c,'reward_catalog')
   if not c.execute(select(cat.c.id).where(cat.c.id==p.reward_id,cat.c.is_active==True)).first():raise HTTPException(400,'Выберите доступную награду')
  c.execute(goals.delete().where(goals.c.user_id==uid))
  if p.reward_id is not None:c.execute(goals.insert().values(user_id=uid,reward_id=p.reward_id))
 return {'ok':True}

@router.post('/poll/vote')
def vote(p:Vote,x_telegram_init_data:str=Header(default='')):
 uid=auth(x_telegram_init_data)
 if p.day!=day().isoformat():raise HTTPException(409,'Вопрос сменился. Обновите страницу')
 try:
  with core.engine.begin() as c:
   user(c,uid);c.execute(votes.insert().values(day=p.day,user_id=uid,answer=p.answer,created_at=now()))
 except IntegrityError:raise HTTPException(409,'Вы уже ответили на сегодняшний вопрос')
 with core.engine.connect() as c:return {'ok':True,'poll':poll(c,uid)}

@router.get('/receipt/{public_id}')
def receipt(public_id:str,x_telegram_init_data:str=Header(default='')):
 uid=auth(x_telegram_init_data)
 with core.engine.connect() as c:
  tr=table(c,'wallet_transfers');r=c.execute(select(tr).where(tr.c.public_id==public_id,((tr.c.sender_id==uid)|(tr.c.recipient_id==uid)))).mappings().one_or_none()
  if not r:raise HTTPException(404,'Перевод не найден')
  def label(pid):
   u=user(c,pid);return '@'+u['username'] if u.get('username') else u['first_name'] or str(pid)
  date=aware(r['created_at']).astimezone(ZoneInfo('Europe/Moscow')).strftime('%d.%m.%Y %H:%M:%S мск')
  body=f"Nyan Wallet\nЧек перевода {r['public_id']}\nОтправитель: {label(r['sender_id'])}\nПолучатель: {label(r['recipient_id'])}\nСумма: {r['amount']} лапкоинов\nДата: {date}\nСтатус: выполнен"
  if r['note']:body+='\nКомментарий: '+r['note']
  return {'ok':True,'text':body,'public_id':r['public_id']}

@router.post('/owner/bonus')
def add_bonus(p:Bonus,x_telegram_init_data:str=Header(default='')):
 raw=core.verify_init_data(x_telegram_init_data or '');core.require_owner(raw)
 if p.expires_at.tzinfo is None or p.expires_at<=now():raise HTTPException(400,'Укажите будущий срок с часовым поясом')
 if not p.title.strip():raise HTTPException(400,'Введите название')
 with core.engine.begin() as c:
  user(c,p.user_id);c.execute(bonuses.insert().values(user_id=p.user_id,title=p.title.strip(),description=p.description,expires_at=p.expires_at,created_at=now()))
 return {'ok':True}

def register_wallet_tools(app):
 m.create_all(core.engine);app.include_router(router)
