import unittest
import test_workflows as fixtures
from test_manychat import NOW,button

class ReminderTests(unittest.TestCase):
    comment=fixtures.WorkflowTests.comment
    click=fixtures.WorkflowTests.click
    tearDown=fixtures.WorkflowTests.tearDown
    def setUp(self):
        fixtures.WorkflowTests.setUp(self);self.c['flows'][0].update(comment_reminder_enabled=True,comment_reminder_after_hours=24,comment_reminder_text='Check our DMs or the link in bio.',comment_reminder_account='self')
        self.engine.reply_resolver=lambda selected:(self.c,self.store.flow_once)
    def reminder(self):return self.store.execute('SELECT * FROM comment_reminders')[0]
    def test_reminder_waits_24h_then_sends_one_public_reply(self):
        self.comment('alarm');self.now+=86399;self.assertFalse(self.engine.run_one(self.c))
        self.now+=1;self.engine.run_one(self.c);self.assertEqual(self.reminder()['state'],'sent')
        sent=[call for call in self.api.calls if call[0]=='POST' and call[2].get('message')=='Check our DMs or the link in bio.']
        self.assertEqual(len(sent),1);self.assertFalse(self.engine.run_one(self.c))
    def test_real_interaction_cancels_reminder(self):
        self.comment('alarm');self.now+=1;event=button('RF_FOLLOW:alarm');event['value']['timestamp']=self.now*1000;self.engine.process('click',event,self.c);self.now+=86400;self.engine.run_one(self.c)
        self.assertEqual(self.reminder()['state'],'cancelled')
    def test_missed_webhook_is_checked_in_live_inbox_before_public_reply(self):
        self.comment('alarm');self.now+=86400;original=self.api.call
        from datetime import datetime,timezone
        self.api.call=lambda method,path,**kw:{'messages':{'data':[{'from':{'id':'dm-user'},'created_time':datetime.fromtimestamp(NOW+1,timezone.utc).isoformat()}]}} if path=='conversation' else original(method,path,**kw)
        self.engine.run_one(self.c);self.assertEqual(self.reminder()['state'],'cancelled')
    def test_pausing_flow_or_reminder_prevents_sending(self):
        self.comment('alarm');self.now+=86400;self.c['flows'][0]['comment_reminder_enabled']=False
        self.engine.run_one(self.c);self.assertEqual(self.reminder()['state'],'waiting')
        self.c['flows'][0]['comment_reminder_enabled']=True;self.c['flows'][0]['enabled']=False
        self.engine.run_one(self.c);self.assertEqual(self.reminder()['state'],'waiting')
    def test_cross_account_without_media_ownership_is_blocked_without_fallback(self):
        self.comment('alarm');self.now+=86400;self.engine.reply_resolver=lambda selected:({**self.c,'account_id':'other-account'},self.store.flow_once)
        self.engine.run_one(self.c);self.assertEqual(self.reminder()['state'],'blocked')
        self.assertNotIn('rf-comment-reminder:business:rf-opening:alarm:reel:comment-user',self.store.actions)

    def test_retired_collaboration_cannot_post_even_with_an_authorized_other_account(self):
        self.comment('alarm');self.now+=86400
        self.c['flows'][0]['comment_reminder_account']='default'
        calls=len(self.api.calls)
        self.engine.reply_resolver=lambda selected:({**self.c,'account_id':'other-account'},self.store.flow_once)
        self.engine.reminders.run_one(self.c,self.c['flows'])
        self.assertEqual(self.reminder()['state'],'blocked')
        self.assertEqual(len(self.api.calls),calls)

    def test_enabling_reminders_does_not_notify_reused_old_openings(self):
        self.c['flows'][0]['comment_reminder_enabled']=False;self.comment('alarm')
        self.c['flows'][0]['comment_reminder_enabled']=True;self.now+=90000;self.comment('alarm','another-comment')
        self.assertEqual(self.store.execute('SELECT * FROM comment_reminders'),[])
    def test_inbox_error_postpones_without_posting_a_comment(self):
        self.comment('alarm');self.now+=86400;original=self.api.call
        def unavailable(method,path,**query):
            if path=='business/conversations':raise RuntimeError('read timeout')
            return original(method,path,**query)
        self.api.call=unavailable;self.engine.run_one(self.c)
        self.assertEqual(self.reminder()['state'],'waiting')
        self.assertGreater(self.reminder()['next_at'],self.now)

if __name__=='__main__':unittest.main()
