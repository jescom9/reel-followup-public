import json,tempfile,unittest
from pathlib import Path
from native.accounts import AccountRegistry
from native.app import App,DEFAULTS

class GraphFixture:
    def __init__(self,config):self.config=config
    def call(self,method,path,data=None,**query):
        if method=='POST':return {'success':True}
        return {'user_id':'222','id':'444','username':'second'}

class AccountsTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        base=self.root/'native/.local';base.mkdir(parents=True)
        (self.root/'.env').write_text('IG_APP_ID=app\nIG_ACCESS_TOKEN=first-token\nIG_APP_SECRET=test-secret\n')
        (base/'config.json').write_text(json.dumps({'account_id':'111','username':'first','verified':True,'keyword':'one'}))
        self.registry=AccountRegistry(self.root,App,GraphFixture,DEFAULTS)
    def tearDown(self):
        for app in self.registry.apps.values():app.store.db.close()
        self.tmp.cleanup()
    def test_accounts_have_separate_credentials_config_data_and_pause_state(self):
        identifier=self.registry.create({'access_token':'second-token'})
        first=self.registry.get('default');second=self.registry.get(identifier)
        self.assertEqual(first.store.config['access_token'],'first-token')
        self.assertEqual(second.store.config['access_token'],'second-token')
        self.assertNotEqual(first.store.folder,second.store.folder)
        config=dict(second.store.config);config['keyword']='two';second.store.save(config)
        self.assertEqual(first.store.config['keyword'],'one')
        self.assertFalse(second.store.config['enabled'])
        self.assertEqual(second.store.env_file.stat().st_mode & 0o777,0o600)
        self.assertNotIn('access_token',self.registry.listing()[1])
    def test_wrong_app_duplicate_account_and_unknown_workspace_are_rejected(self):
        with self.assertRaises(ValueError):self.registry.create({'access_token':'other','app_id':'other-app'})
        self.registry.create({'access_token':'second-token'})
        with self.assertRaises(ValueError):self.registry.create({'access_token':'second-token'})
        with self.assertRaises(ValueError):self.registry.get('../default')
    def test_signed_events_are_ingested_only_into_matching_account(self):
        identifier=self.registry.create({'access_token':'second-token'})
        self.registry.ingest({'object':'instagram','entry':[{'id':'444','changes':[{'field':'comments','value':{'id':'comment','text':'INFO'}}]}]})
        self.assertEqual(self.registry.get('default').store.execute('SELECT * FROM events'),[])
        self.assertEqual(len(self.registry.get(identifier).store.execute('SELECT * FROM events')),1)

if __name__=='__main__':unittest.main()
