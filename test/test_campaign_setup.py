import copy,json,tempfile,threading,unittest
from pathlib import Path
from types import SimpleNamespace
from native.campaign_setup import CampaignSetup,draft_from_text,TEMPLATE
from test_follower_checks import DurableStore
from test_workflows import flow

class Store(DurableStore):
    def __init__(self,config):super().__init__();self.config=config;self.saved=0
    def save(self,config):self.config=copy.deepcopy(config);self.saved+=1

class Graph:
    def __init__(self,registry,config):self.r,self.c=registry,config
    def call(self,method,path,data=None,**fields):
        if method=='POST':self.r.sent.append(data);return {'message_id':str(len(self.r.sent))}
        if path=='me':return self.r.live.get(self.c['account_id'],{'user_id':self.c['account_id'],'username':self.c['username']})
        if self.r.read_failure:raise RuntimeError('Profile read unavailable')
        return self.r.senders.get(path,{'id':path,'username':'creator'})
    def send(self,recipient,text):return self.call('POST',self.c['account_id']+'/messages',{'recipient':recipient,'message':{'text':text}})

class SetupTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.now=100000
        self.root=Path(self.tmp.name);(self.root/'.env').write_text('REEL_CAMPAIGN_SETUP_USERNAME=reelfollowup\n')
        self.source=SimpleNamespace(store=Store({'account_id':'900','username':'reelfollowup','verified':True,'enabled':True}))
        self.target=SimpleNamespace(store=Store({'account_id':'123','username':'creator','verified':True,'enabled':True,'flows':[flow('fit','Fit')],'managed_plan':{'generation':'one'}}),lifecycle=threading.RLock(),stop=threading.Event())
        self.other=SimpleNamespace(store=Store({'account_id':'456','username':'other','verified':True,'enabled':True,'flows':[flow('app','App')],'managed_plan':{'generation':'other'}}),lifecycle=threading.RLock(),stop=threading.Event())
        self.registry=SimpleNamespace(project=self.root,sent=[],live={},senders={},read_failure=False)
        self.registry.graph=lambda c:Graph(self.registry,c)
        self.registry.listing=lambda:[{'profile_id':'creator','account_id':'123','username':'creator','verified':True},{'profile_id':'other','account_id':'456','username':'other','verified':True}]
        self.registry.find_account=lambda aid:('creator',self.target) if aid=='123' else ('other',self.other) if aid=='456' else None
        self.setup=CampaignSetup(self.registry,lambda:self.now)
    def tearDown(self):
        for app in (self.source,self.target,self.other):app.store.db.close()
        self.tmp.cleanup()
    def message(self,text='',payload=None,sender='sender',key='incoming'):
        value={'sender':{'id':sender},'timestamp':(self.now-1)*1000,'message':{'text':text}}
        if payload:value['postback']={'payload':payload}
        return self.setup.process(self.source,key,{'kind':'message','value':value},self.source.store.config)
    def template(self,keyword='NEW'):return f'Campaign:\nName: New campaign\nKeyword: {keyword}\nLink: https://example.test/new\nFollow required: yes\nMessage: Here you go'
    def request(self):return dict(self.source.store.execute('SELECT * FROM campaign_setup_requests ORDER BY rowid DESC LIMIT 1')[0])
    def confirm(self,key='confirm'):return self.message(payload='RF_SETUP_CONFIRM:'+self.request()['id'],key=key)
    def test_menu_template_and_confirmed_creation_only_change_the_verified_owners_workspace(self):
        self.message('hi');buttons=self.registry.sent[-1]['message']['attachment']['payload']['elements'][0]['buttons'];self.assertEqual(buttons[0]['payload'],'RF_SETUP_TEMPLATE')
        self.message(payload='RF_SETUP_TEMPLATE',key='template');self.assertIn(TEMPLATE,self.registry.sent[-1]['message']['text'])
        self.message(self.template(),key='draft');self.assertEqual(self.target.store.saved,0)
        self.confirm();self.assertEqual(self.target.store.saved,1);created=self.target.store.config['flows'][-1];self.assertTrue(created['require_follow']);self.assertFalse(created['followup_enabled']);self.assertEqual(created['keywords'],['NEW']);self.assertEqual(self.other.store.saved,0)
        self.confirm('repeat');self.assertEqual(self.target.store.saved,1)
    def test_unknown_sender_is_sent_to_signup_and_cannot_create_a_campaign(self):
        self.registry.senders['sender']={'id':'sender','username':'unregistered'};self.message(self.template());self.assertEqual(self.target.store.saved,0)
        button=self.registry.sent[-1]['message']['attachment']['payload']['elements'][0]['buttons'][0];self.assertEqual(button['url'],'https://reelfollowups.app/connect/')
    def test_claimed_username_and_recycled_or_renamed_handles_never_grant_control(self):
        self.registry.senders['sender']={'id':'sender','username':'unregistered'};self.message(self.template()+'\nAccount: creator');self.assertEqual(self.target.store.saved,0)
        self.registry.senders.clear();self.registry.live['123']={'user_id':'123','username':'renamed'};self.message(self.template(),key='renamed');self.assertEqual(self.target.store.saved,0)
        self.registry.live['123']={'user_id':'999','username':'creator'};self.message(self.template(),key='wrong-id');self.assertEqual(self.target.store.saved,0)
    def test_case_insensitive_duplicate_reuses_latest_saved_campaign_without_overwriting_it(self):
        self.target.store.config['flows']=[{**flow('old','Fit'),'media_scope':'selected','media_ids':['111']},{**flow('latest','FIT'),'media_scope':'selected','media_ids':['222']}]
        before=copy.deepcopy(self.target.store.config);self.message(self.template('fit'));self.assertIn('latest existing campaign',self.registry.sent[-2]['message']['text'])
        self.confirm();self.assertEqual(self.target.store.config,before);self.assertEqual(self.request()['result_flow_id'],'latest')
    def test_keyword_race_requires_a_new_preview_instead_of_changing_another_campaign(self):
        self.message(self.template());original=self.request()['id'];self.target.store.config['flows'].append(flow('race','NEW'));self.confirm()
        self.assertEqual(self.target.store.saved,0);self.assertNotEqual(self.request()['id'],original);self.assertEqual(self.request()['state'],'pending')
        self.confirm('second-confirm');self.assertEqual(self.target.store.saved,0)
    def test_cancel_expiry_and_another_sender_cannot_apply_the_preview(self):
        self.message(self.template());rid=self.request()['id'];self.message(payload='RF_SETUP_CONFIRM:'+rid,sender='intruder',key='stolen');self.assertEqual(self.target.store.saved,0)
        self.message(payload='RF_SETUP_CANCEL:'+rid,key='cancel');self.assertEqual(self.request()['state'],'cancelled');self.confirm('late');self.assertEqual(self.target.store.saved,0)
        self.message(self.template(),key='new');self.now+=901;self.confirm('expired');self.assertEqual(self.target.store.saved,0)
    def test_reconnected_deleted_or_paused_workspaces_are_handled_without_resuming_accounts(self):
        self.message(self.template());self.target.store.config['managed_plan']['generation']='new';self.confirm();self.assertEqual(self.target.store.saved,0)
        self.message(self.template(),key='new');self.target.stop.set();self.confirm('deleting');self.assertEqual(self.target.store.saved,0);self.target.stop.clear()
        self.target.store.config['enabled']=False;self.message(self.template(),key='paused');self.confirm('paused-confirm');self.assertFalse(self.target.store.config['enabled']);self.assertEqual(self.target.store.saved,1)
    def test_stale_events_echoes_and_non_inbox_accounts_do_not_send_messages(self):
        self.source.store.config['username']='ordinary';self.assertIsNone(self.message('hi'));self.assertEqual(self.registry.sent,[])
        self.source.store.config['username']='reelfollowup';event={'kind':'message','value':{'sender':{'id':'sender'},'timestamp':(self.now-86401)*1000,'message':{'text':'hi'}}};self.setup.process(self.source,'stale',event,self.source.store.config);self.message('hi',sender='900',key='echo');self.assertEqual(self.registry.sent,[])
    def test_invalid_link_duplicate_fields_and_large_messages_never_change_flows(self):
        for text in [self.template().replace('https://example.test/new','http://example.test/new'),self.template()+'\nName: other',self.template().replace('Keyword: NEW','Keyword: one,two'),'x'*3001]:self.message(text,key=str(len(self.registry.sent)));self.assertEqual(self.target.store.saved,0)
    def test_failed_identity_read_never_changes_a_workspace(self):
        self.registry.read_failure=True;self.message(self.template());self.assertEqual(self.target.store.saved,0);self.assertIn('couldn’t verify',self.registry.sent[-1]['message']['text'])
    def test_unfinished_existing_draft_directs_to_editor_instead_of_claiming_it_is_ready(self):
        self.target.store.config['flows']=[{**flow('starter','NEW'),'link_url':'','enabled':False}];self.message(self.template());self.assertEqual(self.target.store.saved,0);self.assertIn('unfinished draft',self.registry.sent[-1]['message']['text'])

if __name__=='__main__':unittest.main()
