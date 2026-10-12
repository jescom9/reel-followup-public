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
