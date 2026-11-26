import importlib.util,sys,types,unittest,os
from pathlib import Path
from datetime import datetime,timezone
from uuid import uuid4
from fastapi import FastAPI,HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine,Column,Integer,BigInteger,String,Text,DateTime,Table,MetaData,select
from sqlalchemy.orm import declarative_base,sessionmaker
from sqlalchemy.pool import StaticPool
ROOT=Path(__file__).resolve().parents[1]
class GiftTest(unittest.TestCase):
 def setUp(self):
  url=os.getenv('GIFT_TEST_DB')
  if url and not url.endswith('/gifts_test'):raise RuntimeError('Dedicated gifts_test DB required')
  self.engine=create_engine(url) if url else create_engine('sqlite://',connect_args={'check_same_thread':False},poolclass=StaticPool)
  Base=declarative_base()
  class User(Base):
   __tablename__='users';telegram_id=Column(BigInteger,primary_key=True);balance=Column(Integer);first_name=Column(String);last_name=Column(String);username=Column(String)
  class Reward(Base):
   __tablename__='reward_catalog';id=Column(Integer,primary_key=True);title=Column(String);cost=Column(Integer);is_active=Column(Integer)
  class Request(Base):
   __tablename__='spend_requests';id=Column(Integer,primary_key=True);telegram_id=Column(BigInteger);reward_id=Column(Integer);reward_title=Column(String);cost=Column(Integer);status=Column(String);created_at=Column(DateTime(timezone=True));processed_at=Column(DateTime(timezone=True))
  class Meta(Base):
   __tablename__='spend_request_meta';request_id=Column(Integer,primary_key=True);owner_comment=Column(Text);updated_at=Column(DateTime(timezone=True))
  class Transaction(Base):
   __tablename__='transactions';id=Column(Integer,primary_key=True);telegram_id=Column(BigInteger);amount=Column(Integer);operation_type=Column(String);description=Column(Text);created_at=Column(DateTime(timezone=True))
  Base.metadata.create_all(self.engine);self.Base=Base;self.User=User;self.Request=Request
  self.Session=sessionmaker(bind=self.engine)
  core=types.ModuleType('server.backend_app');core.engine=self.engine;core.SessionLocal=self.Session;core.User=User;core.Transaction=Transaction;core.OWNER_TELEGRAM_ID=1;core.is_owner=lambda uid:uid==1
  def auth(raw):
   if raw not in ['1','2','3','4']:raise HTTPException(401,'auth')
   return {'id':int(raw)}
  def owner(u):
   if u['id']!=1:raise HTTPException(403,'owner')
  core.verify_init_data=auth;core.require_owner=owner
  parent=types.ModuleType('server');parent.backend_app=core
  ext=types.ModuleType('server.extended_features');ext.Reward=Reward;ext.SpendRequest=Request
  adv=types.ModuleType('server.advanced_features');adv.RequestMeta=Meta;adv.catalog_item=lambda s,r:{'id':r.id,'title':r.title,'cost':r.cost,'available':bool(r.is_active)}
  vip=types.ModuleType('server.vip');vip.is_vip_reward=lambda title:'VIP' in title
  self.old={k:sys.modules.get(k) for k in ['server','server.backend_app','server.extended_features','server.advanced_features','server.vip','server.nyan_world','server.prize_gifts']}
  for name,module in [('server',parent),('server.backend_app',core),('server.extended_features',ext),('server.advanced_features',adv),('server.vip',vip)]:sys.modules[name]=module
  def load(name,path):
   spec=importlib.util.spec_from_file_location(name,ROOT/path);module=importlib.util.module_from_spec(spec);sys.modules[name]=module;spec.loader.exec_module(module);return module
  self.w=load('server.nyan_world','server/nyan_world.py');parent.nyan_world=self.w;self.w.m.create_all(self.engine)
  self.outbox=Table('telegram_relay_outbox',Base.metadata,Column('id',Integer,primary_key=True),Column('source_key',String,unique=True),Column('chat_id',BigInteger),Column('body',Text),Column('state',String),Column('attempts',Integer),Column('created_at',DateTime(timezone=True)));self.outbox.create(self.engine)
  self.g=load('server.prize_gifts','server/prize_gifts.py');app=FastAPI();self.g.register_prize_gifts(app);self.client=TestClient(app)
  with self.Session.begin() as s:
   for i in [1,2,3,4]:s.add(User(telegram_id=i,balance=1000,first_name=str(i),username='user'+str(i)))
   s.add_all([Reward(id=1,title='Random gift',cost=450,is_active=1),Reward(id=2,title='VIP',cost=3250,is_active=1),Reward(id=3,title='Hidden',cost=100,is_active=0)])
 def tearDown(self):
  self.client.close();self.g.m.drop_all(self.engine);self.w.m.drop_all(self.engine);self.Base.metadata.drop_all(self.engine);self.engine.dispose()
  for k,v in self.old.items():
   if v is None:sys.modules.pop(k,None)
   else:sys.modules[k]=v
 def call(self,path,data=None,uid='2',code=200):
  r=self.client.get('/api/prize-gifts'+path,headers={'X-Telegram-Init-Data':uid}) if data is None else self.client.post('/api/prize-gifts'+path,json=data,headers={'X-Telegram-Init-Data':uid})
  self.assertEqual(r.status_code,code,r.text);return r.json()
 def purchase(self,key=None):return self.call('/buy',{'operation_id':key or str(uuid4()),'reward_id':1,'recipient_id':3,'message':'For you'})
 def balance(self,uid):
  with self.Session() as s:return s.get(self.User,uid).balance
 def test_purchase_retry_and_refund_payer_only(self):
  key=str(uuid4());rid=self.purchase(key)['request_id'];self.purchase(key)
  self.assertEqual(self.balance(2),550);self.assertEqual(self.balance(3),1000)
  self.call('/'+str(rid)+'/status',{'status':'cancelled','comment':'Unavailable'},uid='1');self.call('/'+str(rid)+'/status',{'status':'cancelled'},uid='1')
  self.assertEqual(self.balance(2),1000);self.assertEqual(self.balance(3),1000)
  self.call('/'+str(rid)+'/status',{'status':'fulfilled'},uid='1',code=409)
 def test_privacy_and_access(self):
  self.purchase();self.assertEqual(len(self.call('/state',uid='3')['gifts']),1);self.assertEqual(self.call('/state',uid='4')['gifts'],[]);self.call('/1/status',{'status':'fulfilled'},code=403)
 def test_hidden_vip_self_missing_recipient(self):
  for rid,recipient,code in [(2,3,400),(3,3,400),(1,2,400),(1,999,404)]:self.call('/buy',{'operation_id':str(uuid4()),'reward_id':rid,'recipient_id':recipient},code=code)
  self.assertEqual(self.balance(2),1000)
 def test_failed_notification_rolls_back_payment(self):
  self.outbox.drop(self.engine);self.call('/buy',{'operation_id':str(uuid4()),'reward_id':1,'recipient_id':3},code=503);self.assertEqual(self.balance(2),1000)
 def test_legacy_admin_cannot_reopen_cancelled_gift(self):
  rid=self.purchase()['request_id'];self.call('/'+str(rid)+'/status',{'status':'cancelled'},uid='1')
  with self.assertRaises(HTTPException):
   with self.Session.begin() as s:s.get(self.Request,rid).status='fulfilled'
  self.assertEqual(self.balance(2),1000)
 def test_concurrent_purchase_same_key(self):
  if self.engine.dialect.name!='postgresql':self.skipTest('PostgreSQL concurrency')
  from concurrent.futures import ThreadPoolExecutor
  key=str(uuid4())
  def buy(_):return self.client.post('/api/prize-gifts/buy',json={'operation_id':key,'reward_id':1,'recipient_id':3,'message':'For you'},headers={'X-Telegram-Init-Data':'2'}).status_code
  with ThreadPoolExecutor(max_workers=2) as pool:self.assertEqual(list(pool.map(buy,range(2))),[200,200])
  self.assertEqual(self.balance(2),550)
if __name__=='__main__':unittest.main()
