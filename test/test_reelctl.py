import json,subprocess,sys,tempfile,threading,unittest,urllib.request,urllib.error
from unittest.mock import patch
from pathlib import Path
from native.app import App,Handler,ThreadingHTTPServer

ROOT=Path(__file__).resolve().parent.parent

class ReelControlTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();root=Path(self.tmp.name)
        env=root/'.env';env.write_text('REEL_STORAGE=sqlite\nIG_ACCESS_TOKEN=private-test-token\nIG_APP_SECRET=private-test-secret\n')
        self.app=App(root/'data',env)
        self.server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        self.server.app=self.app;self.server.ingress=False
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.url='http://localhost:'+str(self.server.server_port)
    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join()
        self.app.store.db.close();self.tmp.cleanup()
    def cli(self,*args):
        return subprocess.run([sys.executable,str(ROOT/'scripts/reelctl.py'),'--url',self.url,*args],capture_output=True,text=True)
    def test_unverified_drafts_are_paused_and_cannot_be_resumed(self):
        added=self.cli('campaign','add','--name','Test','--keyword','APP','--keyword','DOWNLOAD','--link','https://example.com/app','--no-follow')
        self.assertEqual(added.returncode,0,added.stderr);cid=json.loads(added.stdout)['campaign_id']
        drafts=json.loads(self.cli('campaign','list').stdout)
        campaign=next(f for f in drafts if f['id']==cid)
        self.assertEqual(campaign['keywords'],['APP','DOWNLOAD'])
        self.assertFalse(campaign['enabled']);self.assertFalse(campaign['require_follow'])
        self.assertFalse(campaign['followup_enabled']);self.assertTrue(all(not f['enabled'] for f in drafts))
        self.assertEqual(self.cli('campaign','pause',cid).returncode,0)
        resumed=self.cli('campaign','resume',cid)
        self.assertNotEqual(resumed.returncode,0);self.assertIn('Verify',resumed.stderr)
    def test_status_keeps_credentials_and_nonce_private(self):
        status=self.cli('status');self.assertEqual(status.returncode,0,status.stderr)
        value=json.loads(status.stdout);self.assertEqual(value['storage']['backend'],'sqlite')
        self.assertNotIn('private-test-token',status.stdout);self.assertNotIn('private-test-secret',status.stdout)
        self.assertNotIn(self.app.nonce,status.stdout)
    def test_token_only_direct_setup_cannot_verify_without_app_secret(self):
        self.app.store.config.update(app_id='123',app_secret='')
        for path in ['/api/verify','/api/accounts/create']:
            request=urllib.request.Request(self.url+path,data=b'{"access_token":"test-token"}',method='POST',headers={
                'Content-Type':'application/json','Origin':self.url,'X-Local-Token':self.app.nonce})
            with patch('native.app.Graph') as graph,self.assertRaises(urllib.error.HTTPError) as error:
                urllib.request.urlopen(request)
            message=json.load(error.exception)['error'];error.exception.close()
            self.assertIn('own Meta app secret',message);graph.assert_not_called()

if __name__=='__main__':unittest.main()
