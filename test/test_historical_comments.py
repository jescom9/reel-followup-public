import tempfile,unittest
from pathlib import Path
from datetime import datetime,timezone
from native.app import Store,MetaError
from native.workflows import WorkflowEngine
from native.historical_comments import HistoricalComments,DAY

NOW=1800000000
class HistoricalLaunchTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);root=Path(self.tmp.name)
        self.store=Store(root/'account',root/'.env');self.addCleanup(self.store.db.close)
        self.flow={'id':'launch','name':'Launch','keywords':['App','Fit'],'enabled':True,'require_follow':True,'link_button':True,'link_url':'https://apps.apple.com/app/id6815747379','opening_text':'App free. Follow first.','follow_text':'Follow and tap Following.','link_text':'Your app','button_text':'App Store','public_reply':True,'public_reply_text':'App now free. Check your DMs.','followup_enabled':False,'followup_delay_minutes':60,'followup_text':'How was it?','media_scope':'all','media_ids':[]}
        self.store.config.update(account_id='123',account_aliases=[],username='owner',verified=True,enabled=True,workflow_mode='manychat',access_token='fake',flows=[self.flow])
        self.now=NOW;self.private=[];self.public=[];self.links=[];self.failure=None;self.following=False;self.owner='123';self.replies=[]
        def comment(cid,age,sender):return {'id':cid,'text':'App','timestamp':datetime.fromtimestamp(NOW-age,timezone.utc).isoformat(),'from':{'id':sender,'username':sender},'media':{'id':'456'}}
        self.comments=[comment('789',100,'reader'),comment('890',8*DAY,'old-reader')]
        outer=self
        class API:
            def call(self,method,path,data=None,**query):
                if method=='POST':outer.public.append(data['message']);return {'id':'public-receipt'}
                if path=='123/media':return {'data':[{'id':'456','media_product_type':'REELS'}]}
                if path=='456/comments':return {'data':outer.comments}
                if path=='456':return {'id':'456','owner':{'id':outer.owner},'media_product_type':'REELS'}
                if path=='dm-user':return {'is_user_follow_business':outer.following}
                if path.endswith('/replies'):return {'data':outer.replies}
                return next(c for c in outer.comments if c['id']==path)
            def send_button(self,recipient,text,label,payload):
                outer.private.append((recipient,text,payload))
                if outer.failure:raise outer.failure
                return {'message_id':'opening','recipient_id':'dm-user'}
            def send_link(self,recipient,text,label,url):outer.links.append(url);return {'message_id':'link'}
        self.factory=lambda config:API();self.workflows=WorkflowEngine(self.store,self.factory,None,lambda:self.now)
        self.queue=HistoricalComments(self.store,self.factory,self.workflows,lambda:self.now)
        self.old_text='App now free. Follow and comment App again for the link.'
        self.run=self.queue.preview(self.store.config,self.flow,self.old_text)
    def start(self):self.queue.control(self.store.config,self.run['id'],'start',self.flow)
    def status(self):return self.queue.status(self.store.config,self.run['id'])[0]
    def test_preview_does_not_send_and_accounts_and_flows_must_be_active(self):
        self.assertEqual(self.private+self.public,[]);self.assertEqual(self.run['private_eligible'],1);self.assertEqual(self.run['older_pending'],1)
        self.store.config['enabled']=False
        with self.assertRaises(ValueError):self.start()
        self.assertFalse(self.queue.run_one(self.store.config))
    def test_recent_opening_is_accepted_before_check_dms_and_link_is_follower_gated(self):
        self.start();self.queue.run_one(self.store.config)
        self.assertEqual(self.private[0][2],'RF_FOLLOW:launch');self.assertEqual(self.public,['App now free. Check your DMs.']);self.assertEqual(self.links,[])
        self.assertEqual(self.status()['dm_accepted'],1)
        def click(key):return self.workflows.process(key,{'kind':'message','value':{'sender':{'id':'dm-user'},'recipient':{'id':'123'},'timestamp':self.now*1000,'postback':{'payload':'RF_FOLLOW:launch'}}},self.store.config)
        click('click1');self.assertEqual(self.links,[])
        self.following=True;self.now+=1;click('click2');self.assertEqual(self.links,['https://apps.apple.com/app/id6815747379'])
    def test_old_comments_get_only_truthful_public_launch_and_are_paced(self):
        self.start();self.queue.run_one(self.store.config);self.assertFalse(self.queue.run_one(self.store.config))
        self.now+=60;self.queue.run_one(self.store.config)
        self.assertEqual(len(self.private),1);self.assertEqual(self.public[-1],self.old_text)
        self.assertNotIn('Check your DMs',self.public[-1]);self.assertEqual(self.status()['public_accepted'],2)
        self.now+=60;self.queue.run_one(self.store.config);self.assertEqual(self.status()['state'],'complete')
    def test_failed_private_send_never_posts_check_dms_and_cannot_be_blindly_resumed(self):
        self.failure=MetaError('Network result unknown');self.start();self.queue.run_one(self.store.config)
        self.assertEqual(self.public,[]);self.assertEqual(self.status()['state'],'paused')
        self.assertEqual(self.status()['counts'],{'pending':1,'review':1})
        HistoricalComments(self.store,self.factory,self.workflows,lambda:self.now,recover=True)
        with self.assertRaises(ValueError):self.start()
    def test_ownership_change_and_edited_flow_stop_before_sending(self):
        self.start();self.owner='foreign';self.queue.run_one(self.store.config)
        self.assertEqual(self.public+self.private,[]);self.assertEqual(self.status()['state'],'paused')
        self.flow['link_url']='https://changed.test/'
        with self.assertRaisesRegex(ValueError,'final flow settings'):self.start()
    def test_repeat_preview_deduplicates_people_and_completed_launches(self):
        duplicate={**self.comments[0],'id':'999','timestamp':datetime.fromtimestamp(NOW-200,timezone.utc).isoformat()}
        self.comments.append(duplicate)
        preview=self.queue.preview(self.store.config,self.flow,self.old_text)
        self.assertEqual(preview['total'],2);self.assertEqual(preview['excluded'],1)
        self.start();self.queue.run_one(self.store.config);self.now+=60;self.queue.run_one(self.store.config);self.now+=60;self.queue.run_one(self.store.config)
        again=self.queue.preview(self.store.config,self.flow,self.old_text);self.assertEqual(again['total'],0)
    def test_existing_public_launch_reply_prevents_repeat_dm(self):
        self.replies=[{'text':'@reader '+self.flow['public_reply_text']}];self.start();self.queue.run_one(self.store.config)
        self.assertEqual(self.private+self.public,[]);self.assertEqual(self.status()['counts'].get('skipped'),1)
    def test_blank_operator_profile_does_not_exclude_comments_without_usernames(self):
        for comment in self.comments:comment['from'].pop('username')
        preview=self.queue.preview(self.store.config,self.flow,self.old_text,['','owner'],[''])
        self.assertEqual(preview['total'],2)

    def test_saved_run_is_account_scoped(self):
        other={**self.store.config,'account_id':'999'}
        self.assertEqual(self.queue.status(other),[])
        with self.assertRaises(ValueError):self.queue.control(other,self.run['id'],'start',self.flow)
    def test_contact_limit_pauses_before_private_or_public_send(self):
        from native.plans import managed
        managed(self.store)
        for n in range(50):self.store.execute('INSERT INTO plan_contacts VALUES(?,0)',('full-'+str(n),))
        self.start();self.queue.run_one(self.store.config)
        self.assertEqual(self.private+self.public,[]);self.assertEqual(self.status()['state'],'paused')
        self.assertIn('Contact limit',self.status()['detail'])
