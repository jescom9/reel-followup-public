import tempfile,unittest
from pathlib import Path
from native.app import Store,MetaError,Engine
from native.public_replies import PublicReplies

class PublicReplyTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        root=Path(self.tmp.name);self.store=Store(root/'account',root/'.env');self.addCleanup(self.store.db.close)
        self.store.config.update(account_id='123',username='owner',account_aliases=['alias'],verified=True,enabled=True)
        self.now=100;self.posts=[];self.owner='alias';self.text='FIT';self.replies=[];self.failure=None
        class API:
            def call(_,method,path,data=None,**query):
                if method=='POST':
                    self.posts.append((path,data))
                    if self.failure:raise self.failure
                    return {'id':'receipt'}
                if path=='456':return {'id':'456','owner':{'id':self.owner}}
                if path=='789':return {'id':'789','text':self.text,'media':{'id':'456'}}
                return {'data':self.replies}
        self.factory=lambda config:API();self.queue=PublicReplies(self.store,self.factory,lambda:self.now)
        self.queue.create('batch','456','fit','Approved reply',[{'id':'789','text':'fit'}])
        self.queue.control('batch','resume')
    def state(self):return self.queue.status('batch')[0]
    def test_success_pacing_and_restart_do_not_duplicate(self):
        self.assertTrue(self.queue.run_one(self.store.config));self.assertEqual(self.state()['counts'],{'sent':1})
        self.assertFalse(self.queue.run_one(self.store.config))
        restarted=PublicReplies(self.store,self.factory,lambda:self.now,recover=True)
        self.now+=31;restarted.run_one(self.store.config)
        self.assertEqual(len(self.posts),1);self.assertEqual(self.state()['state'],'complete')
    def test_sender_mismatch_or_wrong_owner_never_posts(self):
        self.owner='other';self.queue.run_one(self.store.config)
        self.assertEqual(self.state()['state'],'paused');self.assertEqual(self.posts,[])
    def test_unknown_network_outcome_is_held_across_restart(self):
        self.failure=MetaError('Network result unknown');self.queue.run_one(self.store.config)
        self.assertEqual(self.state()['counts'],{'review':1})
        PublicReplies(self.store,self.factory,recover=True)
        with self.assertRaises(ValueError):self.queue.control('batch','resume')
        self.now+=40;self.queue.run_one(self.store.config);self.assertEqual(len(self.posts),1)
    def test_rate_or_permission_rejection_pauses_remaining_work(self):
        self.failure=MetaError('Rate limited',code=4);self.queue.run_one(self.store.config)
        self.assertEqual(self.state()['counts'],{'rejected':1});self.assertEqual(self.state()['state'],'paused')
    def test_interrupted_send_pauses_for_review(self):
        self.store.execute("UPDATE public_reply_jobs SET state='sending'")
        PublicReplies(self.store,self.factory,recover=True)
        self.assertEqual(self.state()['counts'],{'review':1});self.assertEqual(self.state()['state'],'paused')
    def test_changed_keyword_and_already_replied_targets_are_skipped(self):
        self.text='outfit';self.queue.run_one(self.store.config)
        self.assertEqual(self.state()['counts'],{'skipped':1});self.assertEqual(self.posts,[])
    def test_mention_prefix_existing_reply_is_not_duplicated(self):
        self.replies=[{'text':'@someone Approved reply'}];self.queue.run_one(self.store.config)
        self.assertEqual(self.state()['counts'],{'skipped':1});self.assertEqual(self.posts,[])
    def test_pause_and_account_pause_prevent_sends(self):
        self.queue.control('batch','pause');self.assertFalse(self.queue.run_one(self.store.config))
        self.queue.control('batch','resume');self.store.config['enabled']=False
        self.assertFalse(self.queue.run_one(self.store.config));self.assertEqual(self.posts,[])
    def test_recreating_batch_is_idempotent_but_changed_sender_is_rejected(self):
        self.queue.create('batch','456','fit','Approved reply',[{'id':'789','text':'fit'}])
        self.assertEqual(self.state()['counts'],{'pending':1})
        self.store.config['account_id']='999'
        with self.assertRaises(ValueError):self.queue.create('batch','456','fit','Approved reply',[])
    def test_existing_engine_runs_batch_without_another_worker(self):
        engine=Engine(self.store,self.factory,lambda:self.now)
        self.assertTrue(engine.run_one());self.assertEqual(len(self.posts),1)

if __name__=='__main__':unittest.main()
