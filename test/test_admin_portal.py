import json,unittest
from unittest.mock import patch,MagicMock
from test_host_service import HostTests as Fixture
from native import hosted_history
from native.storage import StorageBridge

class AdminTests(unittest.TestCase):
    setUp=Fixture.setUp;tearDown=Fixture.tearDown;connect=Fixture.connect
    def call(self,actor,op,**data):return self.host.handle('/host/portal',{'account_id':actor,'operation':op,'data':data})
    def admin(self):
        self.connect('900');self.connect('123')
        with (self.root/'.env').open('a') as out:out.write('REEL_ADMIN_ACCOUNT_IDS=900\n')
        return self.registry.find_account('900')[1],self.registry.find_account('123')[1]
    def test_roles_are_server_pinned_and_ordinary_sessions_cannot_inspect_targets(self):
        actor,target=self.admin();self.assertTrue(self.call('900','status')['is_admin']);self.assertFalse(self.call('123','status')['is_admin'])
        for operation in ['admin.overview','admin.inspect','admin.resources','admin.audit']:
            with self.assertRaisesRegex(ValueError,'Administrator'):self.call('123',operation,target_account_id='900',is_admin=True)
        actor.store.save({**actor.store.config,'verified':False})
        self.assertFalse(self.host.admin.allowed(actor.store.config))
    def test_inspection_is_scoped_redacted_read_only_and_audited(self):
        actor,target=self.admin();before=json.dumps(target.store.config,sort_keys=True)
        target.store.enqueue('event',{'kind':'message','value':{'message':{'text':'private-token '+target.store.config['access_token']}}})
        target.store.execute("UPDATE events SET state='review',detail=? WHERE id='event'",('https://example.test/?access_token='+target.store.config['access_token'],))
        overview=self.call('900','admin.overview');self.assertEqual(overview['totals']['accounts'],2)
        detail=self.call('900','admin.inspect',target_account_id='123');self.assertEqual(detail['account_id'],'123');self.assertNotIn('access_token',json.dumps(detail))
        rows=self.call('900','admin.events',target_account_id='123');self.assertEqual(rows['total'],1);self.assertNotIn(target.store.config['access_token'],json.dumps(rows))
        self.assertEqual(json.dumps(target.store.config,sort_keys=True),before)
        audit=self.call('900','admin.audit');self.assertIn('123',[r['target_id'] for r in audit['rows']])
        with self.assertRaises(ValueError):self.call('900','admin.events',target_account_id='123',page=True)
        with self.assertRaises(ValueError):self.call('900','admin.inspect',target_account_id='999')
        with self.assertRaises(ValueError):self.call('900','admin.delete',target_account_id='123')
    def test_admin_history_never_uses_request_supplied_owner_ids(self):
        _,target=self.admin()
        with StorageBridge(target.store.env_file,target.store.folder) as db:db.request({'records':[{'ig_account_id':'123','conversation_id':'thread','record_type':'message','record_id':'m','message_created_at':'2026-10-14T00:00:00Z','payload':{'from':{'id':'reader','username':'friend'},'message':'owned'}}]})
        result=self.call('900','admin.archive.conversation',target_account_id='123',account_id='900',conversation_id='thread')
        self.assertEqual(result['messages'][0]['text'],'owned')
    def test_stale_admin_sessions_are_rejected(self):
        actor,_=self.admin();actor.store.save({**actor.store.config,'session_not_before':100})
        with self.assertRaisesRegex(ValueError,'Sign in again'):self.host.handle('/host/portal',{'account_id':'900','session_issued_at':99,'operation':'admin.overview'})
    def test_neon_history_queries_use_verified_owner_and_bounded_pagination(self):
        _,target=self.admin();queries=[]
        class Cloud:
            def __enter__(self):return self
            def __exit__(self,*a):pass
            def query(self,name,args):
                queries.append((name,args));return [{'total':1}] if name.endswith('_total') else [{'payload':{'from':{'id':'reader'},'message':'cloud message'},'message_created_at':'now'}]
        with patch.object(hosted_history,'is_cloud',return_value=True),patch.object(hosted_history,'cloud',return_value=Cloud()):
            result=hosted_history.conversation(target.store,{'account_id':'900','conversation_id':'thread','page':2})
            self.assertEqual(result['messages'][0]['text'],'cloud message');self.assertTrue(all(args[0]=='123' for _,args in queries));self.assertEqual(queries[-1][1][-1],60)
            with self.assertRaises(ValueError):hosted_history.conversation(target.store,{'conversation_id':'thread','page':True})
    def test_operational_claims_preserve_old_cloud_outcomes_and_survive_cloud_failure(self):
        import hashlib,time
        actor,target=self.admin();actor.store.save({**actor.store.config,'username':'reelfollowup','enabled':True})
        with (self.root/'.env').open('a') as f:f.write('REEL_CAMPAIGN_SETUP_USERNAME=reelfollowup\nREEL_ALERT_USERNAME=creator\n')
        alerts=self.registry.service_alerts;alerts.initialize(actor.store)
        actor.store.execute('INSERT INTO service_alert_subscription(sender_id,target_id,inbound_at) VALUES(?,?,?)',('owner','123',time.time()))
        sent=[]
        class Sender:
            def send(self,recipient,text):sent.append(text);return {'message_id':'accepted'}
        self.registry.graph=lambda c:Sender()
        actor.store.flow_once=lambda *args:(_ for _ in ()).throw(RuntimeError('Neon unavailable'))
        items=['Neon unavailable'];signature=hashlib.sha256(json.dumps(sorted(items)).encode()).hexdigest();key='ops:check:owner:'+signature+':0'
        with StorageBridge(actor.store.env_file,actor.store.folder) as local:
            local.request({'flow_action_claim':{'ig_account_id':'900','action_id':key}})
            local.request({'flow_action_finish':{'ig_account_id':'900','action_id':key,'state':'sent','receipt':{'message_id':'already-sent'}}})
        alerts.check({'capacity':{'alerts':items}});self.assertEqual(sent,[])
        self.assertEqual(actor.store.execute('SELECT state FROM actions WHERE id=?',(key,))[0]['state'],'sent')
        actor.store.execute('UPDATE service_alert_subscription SET last_sent=0')
        alerts.check({'capacity':{'alerts':['New availability issue']}});self.assertEqual(len(sent),1)

    def test_archive_outage_does_not_hide_the_local_plan_or_block_support_inspection(self):
        from native.neon_http import ArchiveError
        self.admin()
        with patch.object(hosted_history,'summary',side_effect=ArchiveError('Neon unavailable')):
            status=self.call('123','status');self.assertIsNone(status['history']);self.assertEqual(status['plan']['name'],'free')
            inspected=self.call('900','admin.inspect',target_account_id='123');self.assertIsNone(inspected['history']);self.assertEqual(inspected['account_id'],'123')

    def test_cloud_header_totals_are_cached_per_account_without_delaying_live_plan_data(self):
        actor,target=self.admin();calls=[]
        class Cloud:
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def query(self,name,args):calls.append(args[0]);return [{'messages':len(calls)}]
        with patch.object(hosted_history,'is_cloud',return_value=True),patch.object(hosted_history,'cloud',return_value=Cloud()):
            hosted_history.summary(target.store);hosted_history.summary(target.store);hosted_history.summary(actor.store)
        self.assertEqual(calls,['123','900'])

    def test_resource_operation_does_not_require_a_target_account(self):
        self.admin();self.registry.resources.report=MagicMock(return_value={'checked_at':1})
        self.assertEqual(self.call('900','admin.resources'),{'checked_at':1})

if __name__=='__main__':unittest.main()
