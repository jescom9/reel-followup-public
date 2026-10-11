import tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
from datetime import datetime,timezone
from native.storage import StorageBridge
from native.neon_http import ArchiveError

class LocalStorageTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.env=self.root/'.env';self.env.write_text('REEL_STORAGE=sqlite\n');self.data=self.root/'data'
    def tearDown(self):self.tmp.cleanup()
    def bridge(self):return StorageBridge(self.env,self.data)
    def test_default_without_neon_url_never_calls_network(self):
        self.env.write_text('')
        with patch('urllib.request.urlopen',side_effect=AssertionError('network')),self.bridge() as db:
            self.assertEqual(db.backend,'sqlite')
            self.assertEqual(db.request({'manifest':True,'ig_account_id':'a'}),{'manifest':[]})
    def test_claim_survives_restart_and_rejects_uncertain_resend(self):
        identity={'ig_account_id':'a','action_id':'link'}
        with self.bridge() as db:self.assertTrue(db.request({'flow_action_claim':identity})['claimed'])
        with self.bridge() as db:
            self.assertFalse(db.request({'flow_action_claim':identity})['claimed'])
            db.request({'flow_action_finish':{**identity,'state':'sent','receipt':{'message_id':'accepted'}}})
        with self.bridge() as db:
            result=db.request({'flow_action_claim':identity})
            self.assertFalse(result['claimed']);self.assertEqual(result['receipt']['message_id'],'accepted')
    def test_accounts_and_contacts_are_isolated(self):
        with self.bridge() as db:
            db.request({'flow_contact_put':{'ig_account_id':'a','recipient_id':'person','opened':True,'inbound_at':20}})
            self.assertTrue(db.request({'flow_contact_get':{'ig_account_id':'a','recipient_id':'person'}})['contact']['opened'])
            self.assertFalse(db.request({'flow_contact_get':{'ig_account_id':'b','recipient_id':'person'}})['contact']['opened'])
            self.assertTrue(db.request({'flow_action_claim':{'ig_account_id':'a','action_id':'same'}})['claimed'])
            self.assertTrue(db.request({'flow_action_claim':{'ig_account_id':'b','action_id':'same'}})['claimed'])
    def test_archive_checkpoint_latest_match_and_window(self):
        def record(mid,sender,text,stamp):
            return {'ig_account_id':'a','conversation_id':'thread','record_type':'message','record_id':mid,
                'message_created_at':datetime.fromtimestamp(stamp,timezone.utc).isoformat(),
                'payload':{'from':{'id':sender},'to':{'data':[{'id':'person','username':'customer'}]},'message':text}}
        now=time.time()
        with self.bridge() as db:
            db.request({'records':[{'ig_account_id':'a','conversation_id':'thread','record_type':'conversation','record_id':'thread','payload':{'archive_sync_state':'complete','archive_schema_version':3}}]})
            db.request({'records':[record('in','person','Following',now-20),record('out','a','Test phrase',now-10)]})
            result=db.request({'overview':True,'ig_account_id':'a','rule_key':'rule','phrase':'Test phrase'})
            self.assertEqual(result['stats']['eligible'],1);self.assertEqual(result['rows'][0]['recipient_id'],'person')
            db.request({'index_cursor':{'ig_account_id':'a','conversation_id':'thread','cursor':'next'}})
            self.assertEqual(db.request({'manifest':True,'ig_account_id':'a'})['manifest'][0]['archive_next_conversation_cursor'],'next')
            db.request({'records':[record('new','person','Thanks',now)]})
            self.assertEqual(db.request({'targets':True,'ig_account_id':'a','phrase':'Test phrase'})['targets'],[])
    def test_neon_is_explicit_and_unknown_backend_is_rejected(self):
        self.env.write_text('REEL_STORAGE=wrong')
        with self.assertRaises(ArchiveError):self.bridge()
        self.env.write_text('REEL_STORAGE=neon')
        with self.assertRaises(ArchiveError):
            with self.bridge():pass

if __name__=='__main__':unittest.main()
