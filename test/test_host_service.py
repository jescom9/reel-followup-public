import hashlib,hmac,json,tempfile,time,unittest
from pathlib import Path
from native.app import App,DEFAULTS
from native.accounts import AccountRegistry
from native.host_service import HostService

class MetaFixture:
    def __init__(self,c):self.c=c
    def call(self,method,path,data=None,**query):
        if method=='POST':return {'success':True}
        return {'user_id':self.c['access_token'].split('-')[0],'username':'creator','id':self.c['access_token'].split('-')[0]}

class HostTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        (self.root/'.env').write_text('IG_APP_ID=456\nREEL_STORAGE=sqlite\nREEL_WEBHOOK_DELIVERY=relay\nREEL_PI_SERVICE_SECRET='+('s'*40)+'\nREEL_RESERVED_ACCOUNT_IDS=111\n')
        self.registry=AccountRegistry(self.root,App,MetaFixture,DEFAULTS);self.host=HostService(self.registry)
    def tearDown(self):
        for app in self.registry.apps.values():app.store.db.close()
        self.tmp.cleanup()
    def connect(self,id):
        return self.host.handle('/host/connect',{'app_id':'456','account_id':id,'access_token':id+'-private-token','expires_at':2000000000})
    def test_signed_enrollment_and_replay_protection(self):
        path='/host/connect';raw=b'{"account_id":"123"}';stamp=str(int(time.time()));nonce='a'*32
        text='\n'.join(['reel-pi-v1',stamp,nonce,'POST',path,hashlib.sha256(raw).hexdigest()])
        headers={'X-Reel-Time':stamp,'X-Reel-Nonce':nonce,'X-Reel-Signature':hmac.new(b's'*40,text.encode(),hashlib.sha256).hexdigest()}
        self.assertTrue(self.host.authenticate(path,raw,headers));self.assertFalse(self.host.authenticate(path,raw,headers))
        self.assertFalse(self.host.authenticate(path,b'changed',headers))
    def test_connect_refreshes_vault_and_never_leaves_token_in_env_or_status(self):
        result=self.connect('123');app=self.registry.get(result['profile_id'])
        self.assertFalse(result['enabled']);self.assertNotIn('private-token',app.store.env_file.read_text())
        self.assertNotIn(b'123-private-token',app.store.vault.path.read_bytes())
        status=self.host.handle('/host/portal',{'account_id':'123','operation':'status'})
        self.assertNotIn('private-token',json.dumps(status));self.assertTrue(status['credentials']['stored'])
        self.assertEqual(self.connect('123')['profile_id'],result['profile_id'])
    def test_accounts_and_events_stay_isolated_and_reserved_account_cannot_activate(self):
        one=self.connect('123');two=self.connect('222');self.connect('111')
        body={'account_id':'123','events':[{'id':'comment:1','payload':{'kind':'comment','value':{'id':'1','text':'INFO'}}}]}
        self.assertTrue(self.host.handle('/host/events',body)['managed'])
        self.assertEqual(len(self.registry.get(one['profile_id']).store.execute('SELECT * FROM events')),1)
        self.assertEqual(self.registry.get(two['profile_id']).store.execute('SELECT * FROM events'),[])
        with self.assertRaises(ValueError):self.host.handle('/host/portal',{'account_id':'111','operation':'account.toggle','data':{'enabled':True}})
        with self.assertRaises(ValueError):self.host.handle('/host/portal',{'account_id':'999','operation':'status'})
    def test_history_is_owned_by_the_authenticated_account_and_keeps_messages_scoped(self):
        from native.storage import StorageBridge
        one=self.connect('123');two=self.connect('222')
        for result,account,text in [(one,'123','my conversation'),(two,'222','other private conversation')]:
            app=self.registry.get(result['profile_id'])
            with StorageBridge(app.store.env_file,app.store.folder) as db:
                db.request({'records':[{'ig_account_id':account,'conversation_id':'shared-thread-id','record_type':'message','record_id':account+'-message','message_created_at':'2026-10-12T12:00:00Z','payload':{'message':text,'from':{'id':'customer','username':'friend'},'to':{'data':[{'id':account}]}}}]})
        status=self.host.handle('/host/portal',{'account_id':'123','operation':'status'})
        self.assertEqual(status['history']['messages'],1)
        chats=self.host.handle('/host/portal',{'account_id':'123','operation':'archive.list','data':{'account_id':'222'}})
        self.assertEqual(chats['rows'][0]['preview'],'my conversation')
        conversation=self.host.handle('/host/portal',{'account_id':'123','operation':'archive.conversation','data':{'conversation_id':'shared-thread-id','account_id':'222'}})
        self.assertEqual([m['text'] for m in conversation['messages']],['my conversation'])
        self.assertNotIn('private-token',json.dumps(conversation))
        with self.assertRaises(ValueError):self.host.handle('/host/portal',{'account_id':'123','operation':'archive.list','data':{'page':-1}})
        with self.assertRaises(ValueError):self.host.handle('/host/portal',{'account_id':'123','operation':'archive.list','data':{'page':True}})
    def test_resuming_a_restored_workspace_preserves_the_original_campaign_start(self):
        result=self.connect('123');app=self.registry.get(result['profile_id'])
        app.store.save({**app.store.config,'campaign_started_at':123})
        self.host.handle('/host/portal',{'account_id':'123','operation':'account.toggle','data':{'enabled':True}})
        self.assertEqual(app.store.config['campaign_started_at'],123)

    def test_metrics_count_recorded_activity_without_exposing_other_accounts(self):
        from native.storage import StorageBridge
        one=self.connect('123');two=self.connect('222')
        app=self.registry.get(one['profile_id']);other=self.registry.get(two['profile_id'])
        from native.workflows import flows
        for owner in [app,other]:
            legacy={**flows(owner.store.config)[0],'id':'legacy'}
            owner.store.save({**owner.store.config,'flows':[legacy]})
        for owner,recipient in [(app,'mine'),(other,'private-other')]:
            owner.store.execute("INSERT INTO workflow_contacts VALUES('legacy',?,1,1,0,0)",(recipient,))
            owner.store.execute("INSERT INTO workflow_jobs(flow_id,recipient_id,kind,event_key,inbound_at,next_at,state) VALUES('legacy',?,'followup','event',0,0,'sent')",(recipient,))
        with StorageBridge(app.store.env_file,app.store.folder) as db:
            for recipient in ['mine','historical']:
                db.request({'flow_contact_put':{'ig_account_id':'123','recipient_id':recipient,'opened':True,'link_sent':True}})
            db.request({'flow_contact_put':{'ig_account_id':'222','recipient_id':'foreign','opened':True,'link_sent':True}})
        app.store.execute("INSERT INTO workflow_jobs(flow_id,recipient_id,kind,event_key,inbound_at,next_at,state) VALUES('legacy','waiting','followup','event2',0,0,'waiting_inbound')")
        app.store.execute("INSERT INTO workflow_contacts VALUES('removed','old',1,1,0,0)")
        status=self.host.handle('/host/portal',{'account_id':'123','operation':'status'})
        self.assertEqual(status['metrics']['runs'],2)
        self.assertEqual(status['metrics']['links_sent'],2)
        self.assertEqual(status['metrics']['followups_sent'],1)
        self.assertEqual(status['metrics']['waiting_inbound'],1)
        self.assertIsNone(status['metrics']['ctr'])
        self.assertNotIn('private-other',json.dumps(status))
        self.assertNotIn('foreign',json.dumps(status))

    def test_scheduled_activity_is_paginated_scoped_and_explains_paused_requests(self):
        from native.workflows import flows
        from native.storage import StorageBridge
        one=self.connect('123');two=self.connect('222')
        app=self.registry.get(one['profile_id']);other=self.registry.get(two['profile_id'])
        fid=flows(app.store.config)[0]['id']
        flow={**flows(app.store.config)[0],'enabled':True,'followup_enabled':True,'comment_reminder_enabled':True,'comment_reminder_after_hours':24}
        app.store.save({**app.store.config,'flows':[flow],'enabled':False})
        for index in range(35):
            app.store.execute("INSERT INTO workflow_jobs(flow_id,recipient_id,kind,event_key,inbound_at,next_at,state) VALUES(?,?,'followup','event',100,200,'waiting')",(fid,'contact-'+str(index)))
        other.store.execute("INSERT INTO workflow_jobs(flow_id,recipient_id,kind,event_key,inbound_at,next_at,state) VALUES(?,'foreign-contact','followup','foreign',100,200,'waiting')",(fid,))
        app.store.execute("INSERT INTO comment_reminders VALUES('opening',?,'comment','media','contact-0',100,150,'waiting','')",(fid,))
        with StorageBridge(app.store.env_file,app.store.folder) as db:
            db.request({'records':[{'ig_account_id':'123','conversation_id':'thread','record_type':'message','record_id':'message','message_created_at':'2026-10-12T12:00:00Z','payload':{'message':'Hello','from':{'id':'contact-0','username':'friend'},'to':{'data':[{'id':'123'}]}}}]})
        request={'account_id':'123','operation':'activity.list','data':{'account_id':'222'}}
        result=self.host.handle('/host/portal',request)
        self.assertEqual(result['total'],36);self.assertEqual(len(result['rows']),30)
        self.assertTrue(all(row['status']=='paused_account' for row in result['rows']))
        self.assertNotIn('foreign-contact',json.dumps(result))
        result=self.host.handle('/host/portal',{**request,'data':{'kind':'reminder'}})
        self.assertEqual(result['total'],1);self.assertEqual(result['rows'][0]['due_at'],86500)
        self.assertEqual(result['rows'][0]['username'],'friend')
        app.store.save({**app.store.config,'enabled':True,'flows':[{**flow,'followup_enabled':False}]})
        result=self.host.handle('/host/portal',{**request,'data':{'kind':'followup','page':1}})
        self.assertEqual(len(result['rows']),5)
        self.assertTrue(all(row['status']=='paused_followup' for row in result['rows']))
        for data in [{'page':True},{'page':-1},{'kind':'invalid'},{'history':'yes'}]:
            with self.assertRaises(ValueError):self.host.handle('/host/portal',{**request,'data':data})

    def test_public_reply_batch_progress_is_account_owned_and_has_honest_estimates(self):
        from native import hosted_activity
        from native.workflows import flows
        result=self.connect('123');app=self.registry.get(result['profile_id'])
        app.store.save({**app.store.config,'enabled':True})
        for identifier,account in [('mine','123'),('foreign','222')]:
            app.store.execute("INSERT INTO public_reply_batches VALUES(?,?, 'media','INFO','reply','running',1000,30,'','[]','[]')",(identifier,account))
            for cid,state in [('1','sent'),('2','skipped'),('3','pending'),('4','pending')]:
                app.store.execute('INSERT INTO public_reply_jobs(batch_id,comment_id,state) VALUES(?,?,?)',(identifier,cid,state))
        activity=hosted_activity.list_activity(app.store,flows(app.store.config),{},now=990)
        self.assertEqual([b['id'] for b in activity['batches']],['mine'])
        batch=activity['batches'][0];self.assertEqual(batch['processed'],2);self.assertEqual(batch['total'],4)
        self.assertEqual(batch['estimate_seconds'],40)
        app.store.save({**app.store.config,'enabled':False})
        paused=hosted_activity.list_activity(app.store,flows(app.store.config),{},now=990)['batches'][0]
        self.assertEqual(paused['status'],'paused_account');self.assertIsNone(paused['estimate_seconds'])
