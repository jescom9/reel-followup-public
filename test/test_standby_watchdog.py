import importlib.util,io,json,tempfile,unittest
from pathlib import Path
from urllib.error import HTTPError,URLError
from cryptography.fernet import Fernet
spec=importlib.util.spec_from_file_location('watchdog',Path(__file__).resolve().parents[1]/'scripts/standby-watchdog.py');watchdog=importlib.util.module_from_spec(spec);spec.loader.exec_module(watchdog)
class WatchdogTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.key=Fernet.generate_key();(self.root/'key').write_bytes(self.key);self.now=100000;self.sent=[];self.healthy=False;self.unknown=False
        self.payload={'account_id':'900','api_version':'v22.0','access_token':'test-only','health_url':'https://primary.test/host/health','subscribers':[{'sender_id':'scoped-owner','inbound_at':self.now-1}]};self.write()
    def write(self):(self.root/'alerts.rfalert').write_bytes(b'RFAL1'+Fernet(self.key).encrypt(json.dumps(self.payload).encode()))
    def tearDown(self):self.tmp.cleanup()
    def fetch(self,request,timeout):
        if request.full_url.endswith('/host/health'):
            if self.healthy:raise HTTPError(request.full_url,403,'Denied',{},io.BytesIO(b'{"error":"Host authentication denied."}'))
            raise URLError('Offline')
        self.sent.append(json.loads(request.data))
        if self.unknown:raise URLError('Unknown send result')
        return io.BytesIO(b'{"message_id":"accepted"}')
    def runcheck(self):return watchdog.run(self.root,self.root/'key',self.root/'state.json',self.fetch,lambda:self.now)
    def test_independent_outage_and_recovery_send_once_after_three_failures(self):
        self.runcheck();self.runcheck();self.assertEqual(self.sent,[]);result=self.runcheck();self.assertEqual(result['send_state'],'sent');self.assertEqual(len(self.sent),1);self.runcheck();self.assertEqual(len(self.sent),1)
        self.healthy=True;self.runcheck();self.assertEqual(len(self.sent),2);self.runcheck();self.assertEqual(len(self.sent),2)
        self.assertEqual(self.sent[0]['recipient']['id'],'scoped-owner')
    def test_expired_reply_window_never_sends(self):
        self.now+=86401
        for _ in range(5):self.runcheck()
        self.assertEqual(self.sent,[])
    def test_unknown_send_result_is_retained_for_review_and_not_retried(self):
        self.unknown=True
        for _ in range(4):result=self.runcheck()
        self.assertEqual(len(self.sent),1);self.assertEqual(result['send_state'],'review')
if __name__=='__main__':unittest.main()
