import sqlite3,unittest
from native.follower_checks import FollowerChecks
from native.manychat import ManychatFlow
from test_manychat import Store,API,CONFIG,NOW,button

class DurableStore(Store):
    def __init__(self):
        super().__init__();self.db=sqlite3.connect(':memory:');self.db.row_factory=sqlite3.Row
    def execute(self,sql,args=()):
        cursor=self.db.execute(sql,args);rows=cursor.fetchall();self.db.commit();return rows

class FollowerRecheckTests(unittest.TestCase):
    def setUp(self):
        self.time=NOW;self.store=DurableStore();self.api=API()
        self.store.contacts['dm-user']={'opened':True}
        self.flow=ManychatFlow(self.store,lambda _:self.api,lambda:self.time)
        self.checks=FollowerChecks(self.store,lambda _:self.api,self.flow.send_verified_link,lambda:self.time)
        self.flow.checks=self.checks
    def tearDown(self):self.store.db.close()
    def test_delayed_follow_update_sends_link_without_another_click(self):
        self.api.following=False;self.flow.process('click',button(),CONFIG)
        self.assertEqual(sum(c[0]=='button' for c in self.api.calls),1)
        self.assertFalse(self.checks.run_one(CONFIG))
        self.time+=5;self.checks.run_one(CONFIG)
        self.assertEqual(sum(c[0]=='button' for c in self.api.calls),1)
        self.api.following=True;self.time+=15;self.checks.run_one(CONFIG)
        self.assertEqual(sum(c[0]=='send' for c in self.api.calls),1)
        self.assertTrue(self.store.contacts['dm-user']['link_sent'])
        self.assertIn('mc-response:click',self.store.actions)
        self.assertIn('mc-link:v1:dm-user',self.store.actions)
        self.assertFalse(self.checks.run_one(CONFIG))
    def test_expired_window_never_checks_or_sends(self):
        self.checks.schedule('dm-user','old',NOW-86400)
        self.time+=5;self.checks.run_one(CONFIG)
        self.assertEqual(self.api.calls,[])
        self.assertEqual(self.store.execute('SELECT state FROM follower_checks')[0]['state'],'expired')
    def test_unknown_status_does_not_grant_link_or_repeat_prompt(self):
        self.api.following=None;self.flow.process('click',button(),CONFIG)
        self.time+=5;self.checks.run_one(CONFIG)
        self.assertFalse(any(c[0]=='send' for c in self.api.calls))
        self.assertEqual(sum(c[0]=='button' for c in self.api.calls),1)
    def test_recheck_survives_scheduler_restart_and_does_not_resend_existing_link(self):
        self.checks.schedule('dm-user','click',NOW-1)
        self.store.contacts['dm-user']['link_sent']=True
        self.checks=FollowerChecks(self.store,lambda _:self.api,self.flow.send_verified_link,lambda:self.time)
        self.time+=5;self.checks.run_one(CONFIG)
        self.assertFalse(any(c[0]=='send' for c in self.api.calls))
    def test_uncertain_link_send_is_held_for_review(self):
        def fail(*args,**kwargs):raise RuntimeError('timeout')
        self.api.send=fail;self.checks.schedule('dm-user','click',NOW-1)
        self.time+=5;self.checks.run_one(CONFIG)
        self.assertEqual(self.store.execute('SELECT state FROM follower_checks')[0]['state'],'review')
        self.time+=3600;self.assertFalse(self.checks.run_one(CONFIG))

if __name__=='__main__':unittest.main()
