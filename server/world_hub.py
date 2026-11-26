"""Season workspace. Budgets and outcomes remain controlled by the organizer."""
import asyncio,json,logging
from datetime import datetime,timezone,timedelta
from uuid import UUID
from fastapi import APIRouter,Header,HTTPException
from pydantic import BaseModel,Field,ConfigDict
from sqlalchemy import MetaData,Table,Column,Integer,BigInteger,String,Text,DateTime,UniqueConstraint,select
from sqlalchemy.exc import IntegrityError
from . import backend_app as core
from . import nyan_world as w
router=APIRouter(prefix='/api/world/hub',tags=['World hub']);m=MetaData()
records=Table('nw_hub_records',m,Column('id',Integer,primary_key=True),Column('season_id',Integer,nullable=False),Column('kind',String(24),nullable=False),Column('country_id',Integer,nullable=False),Column('author_id',BigInteger,nullable=False),Column('title',String(160),nullable=False),Column('body',Text,nullable=False),Column('status',String(24),nullable=False),Column('data',Text,nullable=False),Column('created_at',DateTime(timezone=True),nullable=False),Column('updated_at',DateTime(timezone=True),nullable=False))
confirmations=Table('nw_treaty_confirmations',m,Column('record_id',Integer,primary_key=True),Column('country_id',Integer,primary_key=True),Column('player_id',BigInteger,nullable=False))
messages=Table('nw_request_messages',m,Column('id',Integer,primary_key=True),Column('request_id',Integer,nullable=False),Column('author_id',BigInteger,nullable=False),Column('body',Text,nullable=False),Column('created_at',DateTime(timezone=True),nullable=False))
seen=Table('nw_player_presence',m,Column('user_id',BigInteger,primary_key=True),Column('seen_at',DateTime(timezone=True),nullable=False))
reminded=Table('nw_meeting_reminders',m,Column('record_id',Integer,primary_key=True),Column('player_id',BigInteger,primary_key=True),Column('starts_at',String(40),nullable=False))
KINDS={'project','treaty','meeting','plan','template','criteria','assessment'}
class Action(BaseModel):
 model_config=ConfigDict(extra='forbid')
 operation_id:UUID
 kind:str=Field(max_length=30)
 data:dict=Field(default_factory=dict)
def auth(raw):return core.verify_init_data(raw or '')
def own(c,uid,sid):return c.execute(select(w.countries).where(w.countries.c.season_id==sid,w.countries.c.player_id==uid)).mappings().one_or_none()
def country(c,cid,sid):
 co=w.row(c,w.countries,w.integer(cid,'страна',1))
 if co['season_id']!=sid:w.fail('Страна из другого сезона')
 return co
def date(value,required=False):
 if not value and not required:return ''
 try:
  d=datetime.fromisoformat(str(value).replace('Z','+00:00'))
  if d.tzinfo is None:raise ValueError()
  return d.astimezone(timezone.utc).isoformat()
 except ValueError:w.fail('Нужна дата с часовым поясом')
def allowed(c,r,uid,admin):
 if admin:return True
 co=own(c,uid,r['season_id'])
 if r['kind']=='criteria':return True
 if not co:return False
 return r['country_id']==co['id'] or (r['kind'] in {'treaty','meeting'} and co['id'] in json.loads(r['data']).get('parties',[]))
def notify_parties(c,r,text):
 data=json.loads(r['data']);ids=set(data.get('parties',[])+[r['country_id']])
 uids={country(c,cid,r['season_id'])['player_id'] for cid in ids};uids.add(core.OWNER_TELEGRAM_ID)
 for uid in uids:
  if uid:w.notify(c,uid,text,mirror=False)
def perform(c,user,p,sid):
 uid=int(user['id']);admin=core.is_owner(uid);d=p.data
 if p.kind=='message':
  req=w.row(c,w.requests,w.integer(d.get('request_id'),'заявка',1))
  if req['season_id']!=sid or (not admin and req['author_id']!=uid):w.fail('Нет доступа',403)
  text=w.string(d.get('body'),'сообщение',4000)
  c.execute(messages.insert().values(request_id=req['id'],author_id=uid,body=text,created_at=w.now()))
  target=req['author_id'] if admin else core.OWNER_TELEGRAM_ID
  w.notify(c,target,f"Уточнение по заявке #{req['id']}: {req['title']}\n{text}",mirror=False);return
 if p.kind in {'confirm','meeting_reply'}:
  r=w.row(c,records,w.integer(d.get('id'),'запись',1));data=json.loads(r['data'])
  if r['season_id']!=sid or not allowed(c,r,uid,admin):w.fail('Нет доступа',403)
  co=own(c,uid,sid)
  if not co or co['id'] not in data.get('parties',[]):w.fail('Вы не сторона соглашения',403)
  if r['status']!='proposed':w.fail('Приём ответов завершён')
  if p.kind=='confirm':
   if r['kind']!='treaty':w.fail('Это не договор')
   if not c.execute(select(confirmations).where(confirmations.c.record_id==r['id'],confirmations.c.country_id==co['id'])).first():
    c.execute(confirmations.insert().values(record_id=r['id'],country_id=co['id'],player_id=uid))
  else:
   if r['kind']!='meeting' or d.get('reply') not in {'accepted','declined'}:w.fail('Некорректный ответ')
   data.setdefault('responses',{})[str(co['id'])]=d['reply'];c.execute(records.update().where(records.c.id==r['id']).values(data=w.pack(data),updated_at=w.now()))
  notify_parties(c,r,f"Ответ по {r['title']}: {co['name']} — {d.get('reply','подтверждено')}");return
 if p.kind=='save':
  kind=d.get('kind');rid=d.get('id');old=w.row(c,records,w.integer(rid,'запись',1)) if rid else None
  if kind not in KINDS or (old and (old['kind']!=kind or old['season_id']!=sid)):w.fail('Некорректная запись')
  if old and old['country_id']!=d.get('country_id'):w.fail('Нельзя переносить запись между странами')
  if kind in {'project','template','criteria','assessment'} and not admin:w.fail('Только организатор',403)
  co=country(c,d.get('country_id'),sid)
  if not admin:
   mine=own(c,uid,sid)
   if not mine or mine['id']!=co['id'] or co['frozen']:w.fail('Это не ваша страна или действия приостановлены',403)
   if old and (old['author_id']!=uid or old['status']!='proposed'):w.fail('Запись уже рассматривается')
  status=d.get('status','proposed') if admin else 'proposed'
  states={'project':{'planned','active','completed','cancelled'},'treaty':{'proposed','approved','rejected','expired'},'meeting':{'proposed','cancelled','completed'},'plan':{'proposed','archived'},'template':{'active','archived'},'criteria':{'active','archived'},'assessment':{'proposed','completed'}}
  if status not in states[kind]:w.fail('Некорректный статус')
  data=d.get('details',{})
  if not isinstance(data,dict):w.fail('Проверьте параметры')
  if kind in {'treaty','meeting'}:
   parties=data.get('parties',[])
   if not isinstance(parties,list):w.fail('Выберите страны')
   parties=[w.integer(x,'страна',1) for x in parties]
   if not isinstance(parties,list) or not 2<=len(set(parties))<=15 or co['id'] not in parties:w.fail('Укажите минимум две страны, включая свою')
   for cid in parties:
    if not country(c,cid,sid)['player_id']:w.fail('Страна ещё без игрока')
   data={'parties':sorted(set(parties)),'starts_at':date(data.get('starts_at'),kind=='meeting'),'ends_at':date(data.get('ends_at')),'responses':{str(co['id']):'accepted'} if kind=='meeting' and co['player_id']==uid else {}}
   if data['ends_at'] and data['starts_at'] and datetime.fromisoformat(data['ends_at'])<=datetime.fromisoformat(data['starts_at']):w.fail('Окончание должно быть после начала')
   if kind=='meeting' and datetime.fromisoformat(data['starts_at'])<=w.now():w.fail('Выберите будущее время')
   # Revised agreements must collect fresh signatures; never carry signatures across edits.
   if old:
    c.execute(confirmations.delete().where(confirmations.c.record_id==old['id']))
    if kind=='meeting':c.execute(reminded.delete().where(reminded.c.record_id==old['id']))
   if status=='approved':w.fail('Сначала соберите подтверждения, затем утвердите отдельной кнопкой')
  elif kind=='project':
   reqid=data.get('request_id');invested=0
   if reqid:
    req=w.row(c,w.requests,w.integer(reqid,'заявка',1))
    if req['country_id']!=co['id'] or req['season_id']!=sid:w.fail('Заявка другой страны')
    if req['status']=='completed':invested=max(0,-json.loads(req['effects']).get('budget_delta',0))
   data={'request_id':reqid,'invested':invested,'stage':w.string(data.get('stage','Подготовка'),'этап',500),'due_at':date(data.get('due_at'))}
  elif kind=='plan':
   items=data.get('items',[])
   if not isinstance(items,list) or len(items)>30:w.fail('До 30 строк плана')
   data={'items':[{'title':w.string(i.get('title'),'название',120),'amount':w.integer(i.get('amount'),'сумма',0)} for i in items]}
  elif kind=='template':data=w.effects(data)
  elif kind=='criteria':
   points=data.get('points',[])
   if not isinstance(points,list) or not 1<=len(points)<=20:w.fail('Укажите от 1 до 20 критериев')
   data={'points':[w.string(t,'критерий',300) for t in points]}
  elif kind=='assessment':
   cid=w.integer(data.get('criteria_id'),'условия',1);criteria=w.row(c,records,cid)
   if criteria['kind']!='criteria' or criteria['season_id']!=sid:w.fail('Условия другого сезона')
   checks=data.get('checks',[])
   if not isinstance(checks,list) or any(type(x)is not bool for x in checks) or len(checks)!=len(json.loads(criteria['data'])['points']):w.fail('Отметьте каждый критерий')
   data={'criteria_id':cid,'points':json.loads(criteria['data'])['points'],'checks':checks,'reward':w.string(data.get('reward',''),'итоговая награда',300,False),'paid':bool(data.get('paid',False))}
  values=dict(season_id=sid,kind=kind,country_id=co['id'],author_id=old['author_id'] if old else uid,title=w.string(d.get('title'),'название',160),body=w.string(d.get('body',''),'описание',8000,False),status=status,data=w.pack(data),updated_at=w.now())
  if old:c.execute(records.update().where(records.c.id==old['id']).values(**values));rid=old['id']
  else:rid=c.execute(records.insert().values(**values,created_at=w.now())).inserted_primary_key[0]
  r=w.row(c,records,rid)
  labels={'project':'Проект','treaty':'Договор','meeting':'Переговоры','plan':'План бюджета','template':'Шаблон последствий','criteria':'Условия наград','assessment':'Итоги участия'}
  status_labels={'proposed':'Предложено','planned':'Запланировано','active':'В работе','completed':'Завершено','cancelled':'Отменено','approved':'Утверждено','rejected':'Отклонено','expired':'Истёк','archived':'В архиве'}
  notify_parties(c,r,f"{labels[kind]}: {r['title']}\nСтатус: {status_labels[status]}\n{r['body']}")
  return {'id':rid}
 if p.kind=='approve_treaty':
  core.require_owner(user);r=w.row(c,records,w.integer(d.get('id'),'договор',1))
  if r['season_id']!=sid or r['kind']!='treaty' or r['status']!='proposed':w.fail('Договор недоступен')
  data=json.loads(r['data'])
  if data.get('ends_at') and datetime.fromisoformat(data['ends_at'])<=w.now():w.fail('Срок договора уже истёк')
  signed={x.country_id:x.player_id for x in c.execute(select(confirmations).where(confirmations.c.record_id==r['id']))}
  if any(signed.get(cid)!=country(c,cid,sid)['player_id'] for cid in data['parties']):w.fail('Нет подтверждения действующего руководителя каждой страны')
  c.execute(records.update().where(records.c.id==r['id']).values(status='approved',updated_at=w.now()));notify_parties(c,r,'Договор утверждён: '+r['title']);return
 w.fail('Неизвестное действие')
@router.post('/actions')
def action(p:Action,x_telegram_init_data:str=Header(default='')):
 user=auth(x_telegram_init_data)
 if len(w.pack(p.data))>30000:w.fail('Слишком большой запрос')
 try:
  with core.engine.begin() as c:
   sid=c.execute(select(w.settings.c.active_season_id).where(w.settings.c.id==1).with_for_update()).scalar_one()
   if not sid:w.fail('Сезон не выбран')
   se=w.row(c,w.seasons,sid)
   if se['status'] not in {'active','registration'} and not core.is_owner(user['id']):w.fail('Сезон приостановлен')
   key=str(p.operation_id);kind='hub:'+p.kind
   previous=c.execute(select(w.audit).where(w.audit.c.operation_id==key)).mappings().one_or_none()
   if previous:
    if previous['actor_id']!=user['id'] or previous['kind']!=kind or previous['payload']!=w.pack(p.data):w.fail('Ключ уже использован',409)
    return {'ok':True,'repeated':True}
   result=perform(c,user,p,sid)
   c.execute(w.audit.insert().values(operation_id=key,actor_id=user['id'],kind=kind,payload=w.pack(p.data),created_at=w.now()))
   return {'ok':True,'result':result}
 except IntegrityError:w.fail('Конфликт записи',409)
@router.get('/state')
def state(x_telegram_init_data:str=Header(default='')):
 user=auth(x_telegram_init_data);uid=user['id'];admin=core.is_owner(uid)
 with core.engine.begin() as c:
  users=w.core.User.__table__;c.execute(select(users.c.telegram_id).where(users.c.telegram_id==uid).with_for_update()).first()
  c.execute(seen.delete().where(seen.c.user_id==uid));c.execute(seen.insert().values(user_id=uid,seen_at=w.now()))
  sid=c.execute(select(w.settings.c.active_season_id)).scalar_one();co=own(c,uid,sid)
  cs=[dict(r) for r in c.execute(select(w.countries).where(w.countries.c.season_id==sid)).mappings()]
  visible=[]
  for r in c.execute(select(records).where(records.c.season_id==sid).order_by(records.c.id.desc())).mappings():
   r=dict(r)
   if allowed(c,r,uid,admin):
    r['details']=json.loads(r.pop('data'))
    r['confirmations']=[dict(x) for x in c.execute(select(confirmations).where(confirmations.c.record_id==r['id'])).mappings()] if r['kind']=='treaty' else []
    visible.append(r)
  reqq=select(w.requests).where(w.requests.c.season_id==sid)
  if not admin:reqq=reqq.where(w.requests.c.author_id==uid)
  reqs=[dict(r) for r in c.execute(reqq.order_by(w.requests.c.id.desc())).mappings()]
  msg=[dict(r) for r in c.execute(select(messages).where(messages.c.request_id.in_([r['id'] for r in reqs] or [-1])).order_by(messages.c.id)).mappings()]
  activity=[]
  if admin:
   presence={r.user_id:r.seen_at for r in c.execute(select(seen))}
   for countryrow in cs:
    pid=countryrow['player_id']
    if not pid:continue
    last=presence.get(pid)
    userlast=c.execute(select(users.c.last_seen_at).where(users.c.telegram_id==pid)).scalar_one_or_none() if 'last_seen_at' in users.c else None
    dates=[x.replace(tzinfo=timezone.utc) if x.tzinfo is None else x for x in (last,userlast) if x]
    last=max(dates) if dates else None
    activity.append({'country':countryrow['name'],'player_id':pid,'last_seen':last,'hours':round((w.now()-last).total_seconds()/3600,1) if last else None})
  ledger=select(w.ledger).where(w.ledger.c.season_id==sid)
  if not admin:ledger=ledger.where(w.ledger.c.country_id==co['id'] if co else w.ledger.c.id==-1)
  return {'ok':True,'is_owner':admin,'season_id':sid,'my_country_id':co['id'] if co else None,'countries':[{'id':r['id'],'name':r['name'],'player_id':r['player_id'],**({'budget':r['budget']} if admin or (co and co['id']==r['id']) else {})} for r in cs],'records':visible,'requests':reqs,'messages':msg,'activity':activity,'ledger':[dict(r) for r in c.execute(ledger.order_by(w.ledger.c.id.desc()).limit(500)).mappings()]}
class Summary(BaseModel):
 ids:list[int]=Field(max_length=50)
@router.post('/summary')
def summary(p:Summary,x_telegram_init_data:str=Header(default='')):
 user=auth(x_telegram_init_data);core.require_owner(user)
 with core.engine.connect() as c:
  sid=c.execute(select(w.settings.c.active_season_id)).scalar_one()
  rows=c.execute(select(w.requests).where(w.requests.c.id.in_(p.ids),w.requests.c.season_id==sid,w.requests.c.status=='completed').order_by(w.requests.c.id)).mappings().all()
  if len(rows)!=len(set(p.ids)):w.fail('Выберите только выполненные заявки текущего сезона')
  parts=['Мировые новости · '+w.now().astimezone(timezone(timedelta(hours=3))).strftime('%d.%m.%Y')]
  for r in rows:parts.append(country(c,r['country_id'],sid)['name']+': '+r['title']+'\n'+r['comment'])
  return {'ok':True,'text':'\n\n'.join(parts)}
def send_reminders():
 with core.engine.begin() as c:
  sid=c.execute(select(w.settings.c.active_season_id).where(w.settings.c.id==1).with_for_update()).scalar_one()
  if not sid or w.row(c,w.seasons,sid)['status']!='active':return
  for r in c.execute(select(records).where(records.c.kind=='meeting',records.c.season_id==sid,records.c.status=='proposed')).mappings():
   data=json.loads(r['data']);starts=datetime.fromisoformat(data['starts_at'])
   if not w.now()<starts<=w.now()+timedelta(minutes=15):continue
   for cid in data['parties']:
    if data.get('responses',{}).get(str(cid))!='accepted':continue
    uid=country(c,cid,sid)['player_id']
    if not uid:continue
    prior=c.execute(select(reminded).where(reminded.c.record_id==r['id'],reminded.c.player_id==uid)).first()
    if prior:continue
    w.notify(c,uid,'Через 15 минут или раньше переговоры: '+r['title']+'\nНачало: '+data['starts_at'],mirror=False)
    c.execute(reminded.insert().values(record_id=r['id'],player_id=uid,starts_at=data['starts_at']))
async def reminders():
 while True:
  try:await asyncio.to_thread(send_reminders)
  except asyncio.CancelledError:raise
  except Exception:logging.getLogger(__name__).exception('Meeting reminders failed')
  await asyncio.sleep(60)
def register_world_hub(app):
 m.create_all(core.engine);app.include_router(router)
 @app.on_event('startup')
 async def start():app.state.world_hub_reminders=asyncio.create_task(reminders())
 @app.on_event('shutdown')
 async def stop():
  task=getattr(app.state,'world_hub_reminders',None)
  if task:
   task.cancel()
   try:await task
   except asyncio.CancelledError:pass
