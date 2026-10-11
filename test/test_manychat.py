import unittest
from datetime import datetime,timezone
from native.manychat import ManychatFlow,LINK,OPENING,PUBLIC_REPLY

NOW=1_800_000_000
CONFIG={'account_id':'business','account_aliases':['scoped-business'],'keyword':'Fit','campaign_started_at':NOW-100,'public_reply':True}
COMMENT={'kind':'comment','received':NOW,'value':{'id':'comment-1','text':'Fit pls','from':{'id':'comment-user'},'media':{'id':'reel'}}}
def button(payload='BF_FOLLOW'):
    return {'kind':'message','value':{'sender':{'id':'dm-user'},'recipient':{'id':'business'},'timestamp':(NOW-1)*1000,'postback':{'payload':payload}}}
class Store:
    def __init__(self): self.actions={};self.contacts={}
    def flow_once(self,key,callback):
        if key not in self.actions:self.actions[key]=callback()
        return self.actions[key]
    def flow_contact_get(self,sender):return self.contacts.get(sender,{})
    def flow_contact_put(self,sender,**values):self.contacts.setdefault(sender,{}).update(values)
class API:
    def __init__(self):self.calls=[];self.following=True;self.product='REELS';self.owner='business';self.fail_opening=False
    def call(self,method,path,data=None,**query):
        self.calls.append((method,path,data,query))
        if path=='reel':return {'id':'reel','owner':{'id':self.owner},'media_product_type':self.product}
        if path=='comment-1':return {'timestamp':datetime.fromtimestamp(NOW-2,timezone.utc).isoformat()}
        if path=='dm-user':return {'is_user_follow_business':self.following}
        return {'id':'public-receipt'}
    def send_button(self,recipient,text,label,payload,quick=False):
        self.calls.append(('button',recipient,text,label,payload,quick))
        if self.fail_opening:raise RuntimeError('Delivery failed')
        return {'message_id':'opening-receipt','recipient_id':'dm-user'}
    def send(self,recipient,text):self.calls.append(('send',recipient,text));return {'message_id':'link-receipt'}
class ManychatTests(unittest.TestCase):
    def setUp(self):self.store=Store();self.api=API();self.flow=ManychatFlow(self.store,lambda _:self.api,lambda:NOW)
    def test_other_creator_uses_their_own_follow_prompt_and_link(self):
        config={**CONFIG,'username':'another_creator','link_url':'https://creator.example/download'}
        self.flow.process('comment:1',COMMENT,config)
        self.assertIn('@another_creator',self.api.calls[2][2])
        self.assertNotIn('@jescojm',self.api.calls[2][2])
        self.api.following=False
        self.flow.process('message:1',button(),config)
        self.assertIn('@another_creator',self.api.calls[-1][2])
        self.api.following=True
        self.flow.process('message:2',button(),config)
        self.assertIn(config['link_url'],self.api.calls[-1][2])
        self.assertNotIn(LINK,self.api.calls[-1][2])
    def test_opening_button_and_public_confirmation_use_different_recipient_scope(self):
        self.flow.process('comment:1',COMMENT,CONFIG)
        self.assertTrue(self.store.contacts['dm-user']['opened'])
        self.assertEqual(self.api.calls[2],('button',{'comment_id':'comment-1'},OPENING,'Following','BF_FOLLOW',False))
        self.assertLessEqual(len(OPENING.encode('utf-16-le'))//2,80)
        self.assertEqual(self.api.calls[3][1],'comment-1/replies')
        self.assertEqual(self.api.calls[3][2],{'message':PUBLIC_REPLY})
        self.flow.process('message:1',button(),CONFIG)
        self.assertTrue(self.store.contacts['dm-user']['link_sent'])
        self.assertIn(LINK,self.api.calls[-1][2])
    def test_no_public_sent_claim_if_private_reply_fails(self):
        self.api.fail_opening=True
        with self.assertRaises(RuntimeError):self.flow.process('comment:1',COMMENT,CONFIG)
        self.assertFalse(any(call[0]=='POST' for call in self.api.calls))
    def test_verified_scoped_owner_alias_is_accepted(self):
        self.api.owner='scoped-business'
        self.flow.process('comment:1',COMMENT,CONFIG)
        self.assertTrue(self.store.contacts['dm-user']['opened'])
    def test_non_reel_wrong_owner_and_nonkeyword_never_receive_messages(self):
        for product,owner,text in [('FEED','business','Fit'),('REELS','other','Fit'),('REELS','business','outfit')]:
            self.api.calls=[];self.api.product,self.api.owner=product,owner
            self.flow.process('comment:1',{**COMMENT,'value':{**COMMENT['value'],'text':text}},CONFIG)
            self.assertFalse(any(c[0] in ('button','send','POST') for c in self.api.calls))
    def test_duplicate_events_never_send_twice(self):
        for _ in range(2):self.flow.process('comment:1',COMMENT,CONFIG)
        self.assertEqual(sum(c[0]=='button' for c in self.api.calls),1)
        for _ in range(2):self.flow.process('message:1',button(),CONFIG)
        self.assertEqual(sum(c[0]=='send' for c in self.api.calls),1)
    def test_every_new_follow_button_rechecks_until_following(self):
        self.flow.process('comment:1',COMMENT,CONFIG)
        self.api.following=False;self.flow.process('message:1',button(),CONFIG)
        for key in ('message:2','message:3'):
            self.assertEqual(self.api.calls[-1][3:6],('Following','BF_FOLLOW',False))
            self.assertIn('@jescojm',self.api.calls[-1][2])
            self.assertNotIn(LINK,self.api.calls[-1][2])
            self.assertFalse(any(c[0]=='send' for c in self.api.calls))
            self.flow.process(key,button(),CONFIG)
        self.api.following=True;self.flow.process('message:4',button(),CONFIG)
        self.assertEqual(sum(c[1]=='dm-user' for c in self.api.calls if c[0]=='GET'),4)
        self.assertTrue(self.store.contacts['dm-user']['link_sent'])
        self.assertEqual(sum(c[0]=='send' for c in self.api.calls),1)
    def test_unknown_follower_status_never_sends_link(self):
        self.store.contacts['dm-user']={'opened':True};self.api.following=None
        self.flow.process('message:1',button(),CONFIG)
        self.assertEqual(self.api.calls[-1][3:6],('Following','BF_FOLLOW',False));self.assertFalse(any(c[0]=='send' for c in self.api.calls))
    def test_previously_sent_link_button_still_checks_following(self):
        self.store.contacts['dm-user']={'opened':True};self.api.following=False
        self.flow.process('message:1',button('BF_LINK'),CONFIG)
        self.assertEqual(self.api.calls[0],('GET','dm-user',None,{'fields':'is_user_follow_business'}))
        self.assertEqual(self.api.calls[-1][3:5],('Following','BF_FOLLOW'))
        self.assertFalse(any(c[0]=='send' for c in self.api.calls))
    def test_typed_following_checks_status(self):
        self.store.contacts['dm-user']={'opened':True}
        event=button();event['value'].pop('postback');event['value']['message']={'text':' Following '}
        self.flow.process('message:1',event,CONFIG)
        self.assertEqual(self.api.calls[0],('GET','dm-user',None,{'fields':'is_user_follow_business'}))
        self.assertIn(LINK,self.api.calls[-1][2])
    def test_legacy_manychat_link_button_continues_with_follow_prompt(self):
        self.store.contacts['dm-user']={'opened':True};self.api.following=False
        event=button('ACT::ca4489c922143edfd874b7f69b0f8ad6')
        event['value']['postback']['title']='Send me the link'
        self.flow.process('message:legacy',event,CONFIG)
        self.assertEqual(self.api.calls[0],('GET','dm-user',None,{'fields':'is_user_follow_business'}))
        self.assertEqual(self.api.calls[-1][3:6],('Following','BF_FOLLOW',False))
        self.assertFalse(any(c[0]=='send' for c in self.api.calls))
        self.assertNotIn(LINK,self.api.calls[-1][2])
    def test_legacy_manychat_follow_button_sends_link_only_when_verified(self):
        self.store.contacts['dm-user']={'opened':True}
        event=button('ACT::old-follow-button');event['value']['postback']['title']='Following'
        self.flow.process('message:legacy',event,CONFIG)
        self.assertEqual(self.api.calls[0],('GET','dm-user',None,{'fields':'is_user_follow_business'}))
        self.assertIn(LINK,self.api.calls[-1][2])
    def test_unrelated_legacy_button_and_unrecorded_opener_are_ignored(self):
        for opened,title in [(True,'Shop'),(False,'Send me the link')]:
            self.store.contacts['dm-user']={'opened':opened}
            event=button('ACT::old-button');event['value']['postback']['title']=title
            self.flow.process('message:legacy',event,CONFIG)
            self.assertEqual(self.api.calls,[])
    def test_quick_reply_following_checks_status(self):
        self.store.contacts['dm-user']={'opened':True}
        event=button();event['value'].pop('postback');event['value']['message']={'text':'Following','quick_reply':{'payload':'BF_FOLLOW'}}
        self.flow.process('message:1',event,CONFIG)
        self.assertEqual(self.api.calls[0],('GET','dm-user',None,{'fields':'is_user_follow_business'}))
        self.assertIn(LINK,self.api.calls[-1][2])
    def test_no_opening_or_expired_message_is_ignored(self):
        self.flow.process('message:1',button(),CONFIG);self.assertEqual(self.api.calls,[])
        self.store.contacts['dm-user']={'opened':True}
        expired=button();expired['value']['timestamp']=(NOW-86401)*1000
        self.flow.process('message:2',expired,CONFIG);self.assertEqual(self.api.calls,[])
    def test_returning_follower_gets_dashboard_after_fresh_check(self):
        self.store.contacts['dm-user']={'opened':True,'link_sent':True}
        self.flow.process('message:1',button(),CONFIG)
        self.assertEqual(self.api.calls[0],('GET','dm-user',None,{'fields':'is_user_follow_business'}))
        self.assertEqual(self.api.calls[1][0],'send');self.assertIn('Dashboard',self.api.calls[1][2])
    def test_returning_nonfollower_or_unknown_gets_recheck_instead_of_link(self):
        self.store.contacts['dm-user']={'opened':True,'link_sent':True}
        for key,status in [('message:1',False),('message:2',None)]:
            self.api.following=status;self.flow.process(key,button(),CONFIG)
            self.assertEqual(self.api.calls[-1][3:6],('Following','BF_FOLLOW',False))
            self.assertFalse(any(c[0]=='send' for c in self.api.calls))
        self.assertEqual(sum(c[1]=='dm-user' for c in self.api.calls if c[0]=='GET'),2)

if __name__=='__main__':unittest.main()
