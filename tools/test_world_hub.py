import importlib.util,sys,unittest,json
from pathlib import Path
from datetime import timedelta
from uuid import uuid4
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from test_nyan_world import WorldTest
ROOT=Path(__file__).resolve().parents[1]
class HubTest(WorldTest):
 def setUp(self):
  super().setUp();sys.modules['server.nyan_world']=self.w
  spec=importlib.util.spec_from_file_location('server.world_hub',ROOT/'server/world_hub.py');self.h=importlib.util.module_from_spec(spec);sys.modules[spec.name]=self.h;spec.loader.exec_module(self.h)
  app=FastAPI();self.h.register_world_hub(app);self.hclient=TestClient(app)
 def tearDown(self):
  self.hclient.close();self.h.m.drop_all(self.engine);sys.modules.pop('server.world_hub',None);sys.modules.pop('server.nyan_world',None);super().tearDown()
 def hub(self,kind,data,role='owner',code=200,key=None):
  r=self.hclient.post('/api/world/hub/actions',json={'kind':kind,'data':data,'operation_id':key or str(uuid4())},headers={'X-Telegram-Init-Data':role});self.assertEqual(r.status_code,code,r.text);return r.json()
 def hs(self,role='owner'):
  r=self.hclient.get('/api/world/hub/state',headers={'X-Telegram-Init-Data':role});self.assertEqual(r.status_code,200,r.text);return r.json()
 def save(self,kind,details={},role='owner',code=200,**extra):
  states={'project':'planned','treaty':'proposed','meeting':'proposed','plan':'proposed','template':'active','criteria':'active','assessment':'proposed'}
  return self.hub('save',{'kind':kind,'title':'Test '+kind,'body':'Details','country_id':1,'status':states[kind],'details':details,**extra},role,code)
 def test_project_and_budget_plan_no_money_mutation(self):
  rid=self.submit();self.do('review',{'id':rid,'status':'approved','effects':{'budget_delta':-200}});self.do('apply',{'id':rid})
  result=self.save('project',{'request_id':rid,'stage':'Construction'})['result']['id']
  self.save('plan',{'items':[{'title':'Road','amount':500}]},'player')
  self.assertEqual(self.hs('player')['records'][0]['kind'],'plan')
  project=next(r for r in self.hs('player')['records'] if r['id']==result);self.assertEqual(project['details']['invested'],200)
  self.assertEqual(self.state()['countries'][0]['budget'],800)
  self.save('project',role='player',code=403)
 def test_treaty_signatures_and_revision(self):
  rid=self.save('treaty',{'parties':[1,2]},'player')['result']['id']
  self.hub('approve_treaty',{'id':rid},code=400)
  self.hub('confirm',{'id':rid},'player');self.hub('confirm',{'id':rid},'other')
  self.hub('confirm',{'id':rid},'third',code=403)
  self.save('treaty',{'parties':[1,2]},'player',id=rid)
  self.assertEqual(self.hs()['records'][0]['confirmations'],[])
  self.hub('confirm',{'id':rid},'player');self.hub('confirm',{'id':rid},'other');self.hub('approve_treaty',{'id':rid})
  self.assertEqual(self.hs()['records'][0]['status'],'approved')
 def test_messages_privacy_and_retry(self):
  rid=self.submit();key=str(uuid4());data={'request_id':rid,'body':'Need cost'}
  self.hub('message',data,key=key);self.hub('message',data,key=key)
  self.assertEqual(len(self.hs('player')['messages']),1);self.assertEqual(self.hs('other')['messages'],[])
  self.hub('message',data,'other',code=403)
 def test_criteria_snapshot_assessment_no_payout(self):
  cid=self.save('criteria',{'points':['Participate','Finish']})['result']['id']
  self.save('assessment',{'criteria_id':cid,'checks':[True,False],'reward':'3000 лапкоинов','paid':False})
  self.assertEqual(len(self.hs('player')['records']),2)
  self.assertEqual(self.hs('other')['records'][0]['kind'],'criteria')
 def test_meeting_response_and_reminder_once(self):
  start=(self.w.now()+timedelta(minutes=10)).isoformat();rid=self.save('meeting',{'parties':[1,2],'starts_at':start},'player')['result']['id']
  self.hub('meeting_reply',{'id':rid,'reply':'accepted'},'other')
  self.clear_queued();self.h.send_reminders();first=len(self.queued());self.assertEqual(first,2);self.h.send_reminders();self.assertEqual(len(self.queued()),first)
 def test_summary_only_completed(self):
  rid=self.submit();headers={'X-Telegram-Init-Data':'owner'}
  r=self.hclient.post('/api/world/hub/summary',json={'ids':[rid]},headers=headers);self.assertEqual(r.status_code,400)
  self.do('review',{'id':rid,'status':'approved'});self.do('apply',{'id':rid})
  r=self.hclient.post('/api/world/hub/summary',json={'ids':[rid]},headers=headers);self.assertEqual(r.status_code,200);self.assertIn('Build',r.json()['text'])
 def test_activity_owner_only(self):
  self.hs('player');self.assertEqual(self.hs('player')['activity'],[]);self.assertTrue(self.hs()['activity'])
if __name__=='__main__':unittest.main()
