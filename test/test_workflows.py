import copy,unittest
from datetime import datetime,timezone
from native.workflows import WorkflowEngine,validate_flows,flows
from test_follower_checks import DurableStore
from test_manychat import API,CONFIG,COMMENT,NOW,button

class WorkflowAPI(API):
    def send_link(self,recipient,text,label,url):
        self.calls.append(('url',recipient,text,label,url));return {'message_id':'url-receipt','recipient_id':'dm-user'}
    def call(self,method,path,data=None,**query):
        if path=='business/conversations':return {'data':[{'id':'conversation','participants':{'data':[{'id':'dm-user'}]}}]}
        if path=='conversation' and getattr(self,'no_inbound',False):return {'messages':{'data':[]}}
        if path=='conversation':return {'messages':{'data':[{'id':'inbound','created_time':datetime.fromtimestamp(NOW-1,timezone.utc).isoformat(),'from':{'id':'dm-user'},'message':'Following'}]}}
        return super().call(method,path,data,**query)

def flow(fid,keyword,follow=True):
    return {'id':fid,'name':keyword.title(),'keywords':[keyword],'enabled':True,'require_follow':follow,
        'link_button':True,'link_url':f'https://example.test/{keyword}','opening_text':'Folge meinem Account und tippe auf Following 👇',
        'follow_text':'Tippe nach dem Folgen auf Following 👇','link_text':'Dein Link','button_text':'Open link',
        'public_reply':True,'public_reply_text':'Sent you a message!','followup_enabled':True,
        'followup_delay_minutes':1,'followup_text':f'How was {keyword}?'}

class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.now=NOW;self.store=DurableStore();self.api=WorkflowAPI()
        self.c={**CONFIG,'flows':[flow('alarm','alarm'),flow('app','app',False)]}
        self.engine=WorkflowEngine(self.store,lambda _:self.api,None,lambda:self.now)
    def comment(self,keyword,key='comment:1'):
        event=copy.deepcopy(COMMENT);event['value']['text']=keyword
        return self.engine.process(key,event,self.c)
    def click(self,fid='alarm',key='click'):
        return self.engine.process(key,button('RF_FOLLOW:'+fid),self.c)
    def tearDown(self):self.store.db.close()
    def test_cross_account_collaboration_settings_are_rejected_and_old_flows_are_paused(self):
        from native.workflows import flows
        for sender in ['default','ig-'+'a'*20]:
            item={**self.c['flows'][0],'comment_reminder_enabled':True,'comment_reminder_account':sender}
            with self.assertRaisesRegex(ValueError,'Cross-account collaboration'):
                validate_flows([item])
            restored=flows({**self.c,'flows':[item]})[0]
            self.assertEqual(restored['comment_reminder_account'],'self')
            self.assertFalse(restored['comment_reminder_enabled'])
            self.assertTrue(restored['enabled'])
        self.assertEqual(validate_flows([{**self.c['flows'][0],'comment_reminder_account':'self'}])[0]['comment_reminder_account'],'self')

    def test_reel_selection_is_validated_and_keyword_overlap_is_scoped(self):
        selected={**flow('one','INFO'),'media_scope':'selected','media_ids':['111']}
        other={**flow('two','INFO'),'media_scope':'selected','media_ids':['222']}
        self.assertEqual(len(validate_flows([selected,other])),2)
        for bad in [{**selected,'media_ids':[]},{**selected,'media_ids':['111','111']},{**selected,'media_ids':[111]},{**selected,'media_scope':'unknown'}]:
            with self.assertRaises(ValueError):validate_flows([bad])
        for conflicting in [{**other,'media_ids':['111']},{**other,'media_scope':'all'}]:
            with self.assertRaisesRegex(ValueError,'unique'):validate_flows([selected,conflicting])
        self.assertEqual(validate_flows([flow('default','info')])[0]['media_scope'],'all')

    def test_unselected_reels_never_open_or_schedule_a_flow(self):
        self.c['flows'][0].update(media_scope='selected',media_ids=['111'])
        result=self.comment('alarm')
        self.assertIn('No active',result);self.assertEqual(self.api.calls,[])
        self.assertEqual(self.store.execute('SELECT * FROM workflow_jobs'),[])

    def test_selected_reel_triggers_only_the_matching_scoped_flow(self):
        self.c['flows']=[{**flow('one','info',False),'media_scope':'selected','media_ids':['111']},{**flow('two','info',False),'media_scope':'selected','media_ids':['222']}]
        original=self.api.call
        def media(method,path,data=None,**query):
            if path in ('111','222'):return {'id':path,'owner':{'id':'business'},'media_product_type':'REELS'}
            return original(method,path,data,**query)
        self.api.call=media
        event=copy.deepcopy(COMMENT);event['value']['text']='info';event['value']['media']['id']='222'
        self.engine.process('selected-comment',event,self.c)
        self.assertEqual([c[-1] for c in self.api.calls if c[0]=='url'],['https://example.test/info'])
        self.assertEqual(self.store.execute('SELECT flow_id FROM workflow_contacts')[0]['flow_id'],'two')

    def test_distinct_keywords_have_distinct_destinations_and_follow_requirements(self):
        self.comment('alarm');self.assertFalse(any(c[0]=='url' for c in self.api.calls))
        self.click();self.assertEqual(self.api.calls[-1][-1],'https://example.test/alarm')
        self.comment('app','comment:2');self.assertEqual([c[-1] for c in self.api.calls if c[0]=='url'],['https://example.test/alarm','https://example.test/app'])
    def test_delayed_following_requires_true_without_repeat_prompts(self):
        self.comment('alarm');self.api.following=False;self.click()
        self.click(key='click2');self.assertEqual(sum(c[0]=='button' for c in self.api.calls),2)
        self.now+=5;self.engine.run_one(self.c)
        self.assertFalse(any(c[0]=='url' for c in self.api.calls))
        self.api.following=True;self.now+=15;self.engine.run_one(self.c)
        self.assertEqual(sum(c[0]=='url' for c in self.api.calls),1)
    def test_duplicate_click_does_not_send_duplicate_link(self):
        self.comment('alarm');self.click();self.click()
        self.assertEqual(sum(c[0]=='url' for c in self.api.calls),1)
    def test_automatic_followup_uses_each_flows_own_text_once(self):
        self.comment('alarm');self.click();self.now+=60
        self.assertTrue(self.engine.run_one(self.c));self.assertEqual(self.api.calls[-1],('send',{'id':'dm-user'},'How was alarm?'))
        self.assertFalse(self.engine.run_one(self.c));self.assertEqual(sum(c[0]=='send' for c in self.api.calls),1)
    def test_paused_followups_resume_without_stopping_initial_link(self):
        self.c['flows'][0]['followup_enabled']=False;self.comment('alarm');self.click();self.now+=60
        self.assertFalse(self.engine.run_one(self.c));self.assertEqual(sum(c[0]=='url' for c in self.api.calls),1)
        self.c['flows'][0]['followup_enabled']=True;self.assertTrue(self.engine.run_one(self.c))
    def test_paused_flow_does_not_send_or_recheck(self):
        self.comment('alarm');self.api.following=False;self.click();self.c['flows'][0]['enabled']=False;self.now+=30
        calls=len(self.api.calls);self.assertFalse(self.engine.run_one(self.c));self.click(key='late');self.assertEqual(len(self.api.calls),calls)
    def test_no_follow_url_click_does_not_open_followup_window(self):
        self.api.no_inbound=True;self.comment('app');self.now+=60;self.engine.run_one(self.c)
        self.assertFalse(any(c[0]=='send' for c in self.api.calls))
        self.assertEqual(self.store.execute('SELECT state FROM workflow_jobs')[0]['state'],'waiting_inbound')
        event=button();event['value'].pop('postback');event['value']['message']={'text':'Thanks'};event['value']['timestamp']=self.now*1000
        self.api.no_inbound=False;self.engine.process('reply',event,self.c);self.engine.run_one(self.c)
        self.assertEqual(self.api.calls[-1],('send',{'id':'dm-user'},'How was app?'))
    def test_expired_live_inbox_or_local_window_never_receives_followup(self):
        self.comment('alarm');self.click();self.now+=86400;self.engine.run_one(self.c)
        self.assertFalse(any(c[0]=='send' for c in self.api.calls))
        self.assertEqual(self.store.execute("SELECT state FROM workflow_jobs WHERE kind='followup'")[0]['state'],'expired')
    def test_fresh_live_reply_can_recover_a_missed_inbound_webhook(self):
        self.comment('alarm');self.click();self.now+=90000
        original=self.api.call
        def live(method,path,**query):
            if path=='conversation':return {'messages':{'data':[{'created_time':datetime.fromtimestamp(self.now-5,timezone.utc).isoformat(),'from':{'id':'dm-user'}}]}}
            return original(method,path,**query)
        self.api.call=live;self.engine.run_one(self.c)
        self.assertEqual(self.api.calls[-1],('send',{'id':'dm-user'},'How was alarm?'))
    def test_live_window_is_rechecked_even_when_local_window_is_fresh(self):
        self.comment('alarm');self.click();self.now+=60
        original=self.api.call
        self.api.call=lambda method,path,**kw: {'messages':{'data':[]}} if path=='conversation' else original(method,path,**kw)
        self.engine.run_one(self.c);self.assertFalse(any(c[0]=='send' for c in self.api.calls))
    def test_unrelated_or_unopened_button_cannot_receive_a_link(self):
        self.click();self.assertEqual(self.api.calls,[])
        self.comment('alarm');event=button('ACT::other');event['value']['postback']['title']='Shop'
        self.engine.process('shop',event,self.c);self.assertFalse(any(c[0]=='url' for c in self.api.calls))
    def test_validation_rejects_conflicting_keywords_and_unsafe_links(self):
        self.assertEqual(len(validate_flows(self.c['flows'])),2)
        for modify in [lambda c:c[1].update(keywords=['ALARM']),lambda c:c[1].update(link_url='http://example.test'),lambda c:c[1].update(link_url='https://user:password@example.test'),lambda c:c[1].update(followup_delay_minutes=1440)]:
            items=copy.deepcopy(self.c['flows']);modify(items)
            with self.assertRaises(ValueError):validate_flows(items)
    def test_paused_drafts_can_wait_for_destination_url(self):
        draft=flow('draft','new');draft.update(enabled=False,link_url='')
        self.assertEqual(validate_flows([draft])[0]['link_url'],'')
        draft['enabled']=True
        with self.assertRaises(ValueError):validate_flows([draft])

if __name__=='__main__':unittest.main()
