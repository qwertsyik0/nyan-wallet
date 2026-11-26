import importlib.util,sys,types,unittest,json
from unittest.mock import patch
from pathlib import Path
from datetime import datetime,timezone,timedelta
from uuid import uuid4
from fastapi import FastAPI,HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import select,Column,Integer,String
from test_prize_gifts import GiftTest
ROOT=Path(__file__).resolve().parents[1]
class PlusTest(GiftTest):
 def setUp(self):
  super().setUp();self.Session.configure(expire_on_commit=False);self.core=sys.modules['server.backend_app'];self.core.Base=self.Base;self.core.BOT_TOKEN='test'
  self.core.get_or_create_user=lambda tg:None
  ext=sys.modules['server.extended_features']
  class Audit(self.Base):
   __tablename__='test_audits';id=Column(Integer,primary_key=True);action=Column(String);details=Column(String)
  ext.audit=lambda session,action,target,details:session.add(Audit(action=action,details=details))
  if 'qrcode' not in sys.modules and importlib.util.find_spec('qrcode') is None:
   for n in ['qrcode','qrcode.image','qrcode.image.svg']:sys.modules[n]=types.ModuleType(n)
   sys.modules['qrcode'].image=sys.modules['qrcode.image'];sys.modules['qrcode.image'].svg=sys.modules['qrcode.image.svg']
  def load(name,path):
   sp=importlib.util.spec_from_file_location(name,ROOT/path);mod=importlib.util.module_from_spec(sp);sys.modules[name]=mod;sp.loader.exec_module(mod);return mod
  self.trans=load('server.transfers','server/transfers.py');self.Base.metadata.create_all(self.engine)
  self.p=load('server.wallet_plus','server/wallet_plus.py');app=FastAPI();self.p.register_wallet_plus(app);app.include_router(self.trans.router);self.pc=TestClient(app)
 def tearDown(self):
  self.pc.close();self.p.m.drop_all(self.engine);sys.modules.pop('server.wallet_plus',None);sys.modules.pop('server.transfers',None);super().tearDown()
 def api(self,path,data=None,uid='2',code=200):
  h={'X-Telegram-Init-Data':uid};r=self.pc.get('/api/wallet-plus'+path,headers=h) if data is None else self.pc.post('/api/wallet-plus'+path,json=data,headers=h)
  self.assertEqual(r.status_code,code,r.text);return r.json()
 def direct(self,key=None,code=200):
  r=self.pc.post('/api/transfers',json={'recipient':'3','amount':100,'idempotency_key':key or str(uuid4())},headers={'X-Telegram-Init-Data':'2'});self.assertEqual(r.status_code,code,r.text);return r.json()
 def test_request_payment_atomic_once(self):
  r=self.api('/request',{'amount':100,'reason':'Lunch'},uid='3')['request'];token=r['token']
  self.api('/request/'+token+'/pay',{'amount':101},code=409)
  self.api('/request/'+token+'/pay',{'amount':100});self.api('/request/'+token+'/pay',{'amount':100})
  self.assertEqual(self.balance(2),900);self.assertEqual(self.balance(3),1100)
  self.api('/request/'+token+'/pay',{'amount':100},uid='4',code=409)
  self.assertEqual(self.api('/request/'+token)['request']['status'],'paid')
 def test_freeze_direct_request_and_thaw(self):
  self.api('/freeze',{'frozen':True});self.direct(code=423)
  token=self.api('/request',{'amount':100,'reason':'Payment'},uid='3')['request']['token']
  self.api('/request/'+token+'/pay',{'amount':100},code=423);self.assertEqual(self.balance(2),1000)
  self.api('/freeze',{'frozen':False});self.direct();self.assertEqual(self.balance(2),900)
 def test_cancel_request_no_money(self):
  token=self.api('/request',{'amount':100,'reason':'Pay'},uid='3')['request']['token']
  self.api('/request/'+token+'/cancel',{},code=404)
  self.api('/request/'+token+'/cancel',{},uid='3');self.api('/request/'+token+'/pay',{'amount':100},code=409)
  self.assertEqual(self.balance(2),1000)
 def test_wishlist_public_only_selected(self):
  self.api('/wishlist',{'reward_ids':[1]});s=self.api('/state');token=s['wishlist_link'].split('wishlist_')[1]
  d=self.api('/wishlist/'+token,uid='3');self.assertEqual([r['id'] for r in d['rewards']],[1]);self.assertNotIn('balance',d)
  self.api('/wishlist',{'reward_ids':[]});self.assertEqual(self.api('/wishlist/'+token,uid='3')['rewards'],[])
 def test_sales_time_and_overlap_preserve_base(self):
  stamp=self.p.now();data={'reward_id':1,'percent':20,'starts_at':(stamp-timedelta(minutes=1)).isoformat(),'ends_at':(stamp+timedelta(hours=1)).isoformat()}
  self.api('/owner/sale',data,code=403);self.api('/owner/sale',data,uid='1');self.api('/owner/sale',data,uid='1',code=409)
  with self.engine.connect() as c:self.assertEqual(self.p.effective_cost(c,1,450),360)
  with patch.object(self.p,'now',return_value=stamp+timedelta(hours=2)):
   with self.engine.connect() as c:self.assertEqual(self.p.effective_cost(c,1,450),450)
  with self.Session() as session:self.assertEqual(session.get(sys.modules['server.extended_features'].Reward,1).cost,450)
 def test_grant_preview_confirm_idempotency(self):
  data={'operation_id':str(uuid4()),'rows':[{'user_id':2,'amount':200},{'user_id':3,'amount':300}],'reason':'Reward'}
  self.api('/owner/draft',data,code=403);did=self.api('/owner/draft',data,uid='1')['id'];self.api('/owner/draft',data,uid='1')
  self.assertEqual(self.balance(2),1000);self.assertEqual(self.api('/owner/draft/'+str(did),uid='1')['total'],500)
  self.api('/owner/draft/'+str(did)+'/confirm',{'total':499,'count':2},uid='1',code=409)
  for _ in range(2):self.api('/owner/draft/'+str(did)+'/confirm',{'total':500,'count':2},uid='1')
  self.assertEqual(self.balance(2),1200);self.assertEqual(self.balance(3),1300)
  data['operation_id']=str(uuid4());data['rows'].append(data['rows'][0]);self.api('/owner/draft',data,uid='1',code=400)
 def test_notes_personal_and_staff_visibility(self):
  self.direct()
  tx=self.api('/state')['transactions'][0]['id']
  self.api('/note',{'transaction_id':tx,'kind':'personal','body':'Lunch'})
  self.api('/note',{'transaction_id':tx,'kind':'personal','body':'Hack'},uid='3',code=404)
  self.api('/note',{'transaction_id':tx,'kind':'staff','body':'Investigation'},code=403)
  self.api('/note',{'transaction_id':tx,'kind':'staff','body':'Investigation'},uid='1')
  self.assertEqual([n['body'] for n in self.api('/state')['notes']],['Lunch'])
  self.api('/note',{'transaction_id':tx,'kind':'personal','body':''});self.assertEqual(self.api('/state')['notes'],[])
 def test_regular_reward_sale_price_and_stale_quote(self):
  import ast,asyncio,re
  from fastapi import BackgroundTasks,Header
  source=(ROOT/'server/extended_features.py').read_text();node=next(n for n in ast.parse(source).body if isinstance(n,ast.AsyncFunctionDef) and n.name=='create_spend_request');node.decorator_list=[]
  ext=sys.modules['server.extended_features'];vip=sys.modules['server.vip'];vip.check_renewal_capacity=lambda *a:None;vip.activate_vip=lambda *a:None;vip.VipPurchaseToken=object
  self.core.apply_telegram_profile=lambda *a:None
  scope={'__name__':'server.test_reward_endpoint','__package__':'server','core':self.core,'Reward':ext.Reward,'SpendRequest':ext.SpendRequest,'BackgroundTasks':BackgroundTasks,'Header':Header,'HTTPException':HTTPException,'select':select,'now_utc':self.p.now,'re':re,'audit':ext.audit,'send_telegram_message':lambda *a:None,'user_label':lambda u:u.username}
  exec(compile(ast.Module(body=[node],type_ignores=[]),'reward-endpoint','exec'),scope)
  stamp=self.p.now();self.api('/owner/sale',{'reward_id':1,'percent':20,'starts_at':(stamp-timedelta(minutes=1)).isoformat(),'ends_at':(stamp+timedelta(hours=1)).isoformat()},uid='1')
  async def buy(price):return await scope['create_spend_request'](reward_id=1,background_tasks=BackgroundTasks(),x_telegram_init_data='2',x_vip_purchase_key=None,vip_purchase_key=None,expected_cost=price)
  with self.assertRaises(HTTPException):asyncio.run(buy(450))
  self.assertEqual(self.balance(2),1000)
  result=asyncio.run(buy(360));self.assertEqual(result['request']['cost'],360);self.assertEqual(self.balance(2),640)
  with self.Session() as session:self.assertEqual(session.get(self.Request,result['request']['id']).cost,360)
 def test_concurrent_pay_different_people(self):
  if self.engine.dialect.name!='postgresql':self.skipTest('PostgreSQL concurrency')
  from concurrent.futures import ThreadPoolExecutor
  token=self.api('/request',{'amount':100,'reason':'Pay'},uid='3')['request']['token']
  def pay(uid):return self.pc.post('/api/wallet-plus/request/'+token+'/pay',json={'amount':100},headers={'X-Telegram-Init-Data':uid}).status_code
  with ThreadPoolExecutor(max_workers=2) as pool:self.assertEqual(sorted(pool.map(pay,['2','4'])),[200,409])
  self.assertEqual(self.balance(3),1100);self.assertEqual(self.balance(2)+self.balance(4),1900)
if __name__=='__main__':unittest.main()
