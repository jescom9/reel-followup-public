import copy,json,tempfile,unittest
from unittest.mock import patch
from native.app import Store

class LocalWebhookTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory()
        with patch('native.app.read_env',return_value={}),patch('native.app.save_instagram_env'):
            self.store=Store(self.folder.name)
        self.store.config.update(account_id='owner',account_aliases=['scoped-owner'])
    def tearDown(self):self.store.db.close();self.folder.cleanup()
    def event(self,stamp=100):
        return {'object':'instagram','entry':[{'id':'scoped-owner','messaging':[{'sender':{'id':'person'},'recipient':{'id':'scoped-owner'},'timestamp':stamp,'postback':{'mid':'same-original-template','payload':'BF_FOLLOW','title':'Following'}}]}]}
    def test_each_distinct_click_survives_while_duplicate_delivery_is_ignored(self):
        self.store.ingest(self.event());self.store.ingest(self.event());self.store.ingest(self.event(101))
        rows=self.store.execute('SELECT id,payload FROM events')
        self.assertEqual(len(rows),2);self.assertNotEqual(rows[0]['id'],rows[1]['id'])
        self.assertEqual(json.loads(rows[0]['payload'])['value']['recipient']['id'],'owner')
    def test_foreign_accounts_and_echo_messages_are_ignored(self):
        foreign=self.event();foreign['entry'][0]['id']='someone-else';self.store.ingest(foreign)
        echo=self.event();echo['entry'][0]['messaging'][0]['message']={'mid':'echo','is_echo':True};self.store.ingest(echo)
        self.assertEqual(self.store.execute('SELECT * FROM events'),[])
    def test_postback_without_mid_still_has_a_stable_delivery_identity(self):
        event=self.event();event['entry'][0]['messaging'][0]['postback'].pop('mid')
        self.store.ingest(event);self.store.ingest(event)
        self.assertEqual(len(self.store.execute('SELECT * FROM events')),1)

if __name__=='__main__':unittest.main()
