import importlib.util, sys, types, unittest, os
from pathlib import Path
from datetime import datetime, timezone, timedelta
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, MetaData, Table, Column, Integer, BigInteger, String, Boolean, DateTime, Text, select
from sqlalchemy.pool import StaticPool
ROOT=Path(__file__).resolve().parents[1]
class ToolsTest(unittest.TestCase):
 def setUp(self):
  url=os.getenv('WALLET_TOOLS_TEST_DB')
  if url and not url.endswith('/tools_test'):raise RuntimeError('Dedicated test DB required')
  self.engine=create_engine(url) if url else create_engine('sqlite://',poolclass=StaticPool,connect_args={'check_same_thread':False})
  md=MetaData();self.md=md
  self.users=Table('users',md,Column('telegram_id',BigInteger,primary_key=True),Column('balance',Integer),Column('first_name',String),Column('username',String))
  self.cat=Table('reward_catalog',md,Column('id',Integer,primary_key=True),Column('title',String),Column('cost',Integer),Column('is_active',Boolean))
  self.req=Table('spend_requests',md,Column('id',Integer,primary_key=True),Column('telegram_id',BigInteger),Column('reward_title',String),Column('cost',Integer),Column('status',String),Column('created_at',DateTime(timezone=True)),Column('processed_at',DateTime(timezone=True)))
  self.meta=Table('spend_request_meta',md,Column('request_id',Integer,primary_key=True),Column('owner_comment',Text))
  self.tr=Table('wallet_transfers',md,Column('id',Integer,primary_key=True),Column('public_id',String),Column('sender_id',BigInteger),Column('recipient_id',BigInteger),Column('amount',Integer),Column('note',Text),Column('created_at',DateTime(timezone=True)))
  self.vip=Table('vip_subscriptions',md,Column('request_id',Integer,primary_key=True),Column('telegram_id',BigInteger),Column('starts_at',DateTime(timezone=True)),Column('ends_at',DateTime(timezone=True)))
  md.create_all(self.engine)
  core=types.ModuleType('server.backend_app');core.engine=self.engine
  def verify(raw):
   if raw not in ['1','2','3']:raise HTTPException(401,'auth')
   return {'id':int(raw)}
  def owner(u):
   if u['id']!=1:raise HTTPException(403,'owner')
  core.verify_init_data=verify;core.require_owner=owner;core.is_owner=lambda uid:uid==1
  parent=types.ModuleType('server');parent.backend_app=core
  self.old={k:sys.modules.get(k) for k in ['server','server.backend_app']};sys.modules['server']=parent;sys.modules['server.backend_app']=core
  spec=importlib.util.spec_from_file_location('tools_test_module',ROOT/'server/wallet_tools.py');self.w=importlib.util.module_from_spec(spec);sys.modules[spec.name]=self.w;spec.loader.exec_module(self.w)
  app=FastAPI();self.w.register_wallet_tools(app);self.client=TestClient(app)
  stamp=datetime.now(timezone.utc)
  with self.engine.begin() as c:
   c.execute(self.users.insert(),[{'telegram_id':i,'balance':200,'first_name':f'User {i}','username':f'u{i}'} for i in [1,2,3]])
   c.execute(self.cat.insert(),[{'id':1,'title':'Gift','cost':450,'is_active':True},{'id':2,'title':'Hidden','cost':900,'is_active':False}])
   c.execute(self.req.insert(),[{'id':1,'telegram_id':2,'reward_title':'Gift','cost':450,'status':'pending','created_at':stamp},{'id':2,'telegram_id':3,'reward_title':'Private','cost':900,'status':'fulfilled','created_at':stamp}])
   c.execute(self.meta.insert(),{'request_id':1,'owner_comment':'Waiting seller'})
   c.execute(self.tr.insert(),{'id':1,'public_id':'NWT_TEST','sender_id':2,'recipient_id':3,'amount':25,'note':'Thanks','created_at':stamp})
 def tearDown(self):
  self.client.close();self.w.m.drop_all(self.engine);self.md.drop_all(self.engine);self.engine.dispose()
  for k,v in self.old.items():
   if v is None:sys.modules.pop(k,None)
   else:sys.modules[k]=v
 def call(self,path,body=None,uid='2',code=200):
  h={'X-Telegram-Init-Data':uid};r=self.client.get('/api/wallet-tools'+path,headers=h) if body is None else self.client.post('/api/wallet-tools'+path,json=body,headers=h)
  self.assertEqual(r.status_code,code,r.text);return r.json()
 def test_auth_privacy_and_comments(self):
  self.call('/state',uid='',code=401);d=self.call('/state');self.assertEqual([r['id'] for r in d['requests']],[1]);self.assertEqual(d['requests'][0]['comment'],'Waiting seller');self.assertEqual(d['balance'],200)
 def test_calculator_rounding_and_validation(self):
  d=self.call('/calculate',{'rubles':'199.99','discount':'10'});self.assertEqual(d['paid'],'179.99');self.assertEqual(d['cashback'],8);self.assertEqual(d['rate'],5)
  self.call('/calculate',{'rubles':'-1'},code=422);self.call('/calculate',{'rubles':'100','discount':101},code=422)
  self.assertEqual(self.call('/calculate',{'rubles':'100','discount':'100'})['cashback'],0)
 def test_vip_active_future_and_expired(self):
  stamp=datetime.now(timezone.utc)
  with self.engine.begin() as c:c.execute(self.vip.insert(),{'request_id':1,'telegram_id':2,'starts_at':stamp-timedelta(days=1),'ends_at':stamp+timedelta(days=1)})
  self.assertEqual(self.call('/calculate',{'rubles':'100'})['cashback'],8);self.assertEqual(self.call('/state')['bonuses'][0]['title'],'Nyan VIP')
  with self.engine.begin() as c:c.execute(self.vip.update().values(starts_at=stamp+timedelta(days=1),ends_at=stamp+timedelta(days=2)))
  self.assertEqual(self.call('/calculate',{'rubles':'100'})['rate'],5)
 def test_goal_price_change_and_no_spending(self):
  self.call('/goal',{'reward_id':1});self.assertEqual(self.call('/state')['goal']['remaining'],250)
  with self.engine.begin() as c:c.execute(self.cat.update().where(self.cat.c.id==1).values(cost=500))
  self.assertEqual(self.call('/state')['goal']['remaining'],300);self.assertEqual(self.call('/state')['balance'],200)
  self.call('/goal',{'reward_id':2},code=400);self.assertIsNone(self.call('/state',uid='3')['goal'])
  self.call('/goal',{'reward_id':None});self.assertIsNone(self.call('/state')['goal'])
 def test_receipt_both_parties_and_privacy(self):
  self.assertIn('u2',self.call('/receipt/NWT_TEST')['text']);self.assertIn('u3',self.call('/receipt/NWT_TEST',uid='3')['text']);self.call('/receipt/NWT_TEST',uid='1',code=404);self.call('/receipt/FAKE',code=404)
 def test_poll_once_and_stale_day(self):
  p=self.call('/state')['poll'];self.assertIsNone(p['counts']);self.call('/poll/vote',{'day':p['day'],'answer':2});self.call('/poll/vote',{'day':p['day'],'answer':1},code=409)
  result=self.call('/state')['poll'];self.assertEqual(result['counts'][2],1);self.assertEqual(result['total'],1);self.assertEqual(self.call('/state')['balance'],200)
  self.call('/poll/vote',{'day':'2000-01-01','answer':1},code=409)
 def test_owner_bonus_expiry_auth(self):
  data={'user_id':2,'title':'Discount','description':'For accounts','expires_at':(datetime.now(timezone.utc)+timedelta(days=1)).isoformat()}
  self.call('/owner/bonus',data,code=403);self.call('/owner/bonus',data,uid='1');self.assertEqual(self.call('/state')['bonuses'][0]['title'],'Discount');self.assertEqual(self.call('/state')['balance'],200)
  data['expires_at']='2000-01-01T00:00:00Z';self.call('/owner/bonus',data,uid='1',code=400)
 def test_pagination(self):
  with self.engine.begin() as c:c.execute(self.req.insert(),[{'id':i,'telegram_id':2,'reward_title':'Gift','cost':450,'status':'pending','created_at':datetime.now(timezone.utc)} for i in range(3,60)])
  d=self.call('/state');self.assertTrue(d['more_requests']);ids={r['id'] for r in d['requests']};next=self.call('/state?before_request_id='+str(d['requests'][-1]['id']));self.assertFalse(ids.intersection(r['id'] for r in next['requests']))
 def test_concurrent_poll_vote(self):
  if self.engine.dialect.name!='postgresql':self.skipTest('PostgreSQL concurrency')
  from concurrent.futures import ThreadPoolExecutor
  key=self.w.day().isoformat()
  def vote(_):return self.client.post('/api/wallet-tools/poll/vote',json={'day':key,'answer':0},headers={'X-Telegram-Init-Data':'2'}).status_code
  with ThreadPoolExecutor(max_workers=2) as p:self.assertEqual(sorted(p.map(vote,range(2))),[200,409])
if __name__=='__main__':unittest.main()
