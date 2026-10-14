import json,unittest
from test_campaign_setup import SetupTests as Fixture
from native.service_alerts import ServiceAlerts

class AlertTests(unittest.TestCase):
    setUp=Fixture.setUp;tearDown=Fixture.tearDown;message=Fixture.message
    def prepare(self):
        with (self.root/'.env').open('a') as f:f.write('REEL_ALERT_USERNAME=creator\n')
        self.registry.service_alerts=ServiceAlerts(self.registry,lambda:self.now)
        self.source.store.once=self.source.store.flow_once
        original=self.registry.find_account
        self.registry.find_account=lambda aid:('source',self.source) if aid=='900' else original(aid)
        listing=self.registry.listing
        self.registry.listing=lambda:[{'account_id':'900','username':'reelfollowup','verified':True,'enabled':True},*[dict(r,enabled=True) for r in listing()]]
        self.registry.campaign_setup=self.setup
    def test_alerts_require_verified_target_owner_and_deduplicate_capacity_incidents(self):
        self.prepare();self.message('alerts');self.assertIn('alerts are on',self.registry.sent[-1]['message']['text'])
        report={'capacity':{'alerts':['Disk pressure']}};self.registry.service_alerts.check(report);count=len(self.registry.sent)
        self.registry.service_alerts.check(report);self.assertEqual(len(self.registry.sent),count)
        self.assertIn('Disk pressure',self.registry.sent[-1]['message']['text'])
        self.now+=86401;self.registry.service_alerts.check({'capacity':{'alerts':['New failure']}});self.assertEqual(len(self.registry.sent),count)
    def test_operational_alert_can_send_when_cloud_claims_are_unavailable(self):
        self.prepare();self.message('alerts')
        def failed(*args):raise RuntimeError('Neon unavailable')
        self.source.store.flow_once=failed
        self.registry.service_alerts.check({'capacity':{'alerts':['Neon unavailable']}})
        self.assertIn('Neon unavailable',self.registry.sent[-1]['message']['text'])
    def test_unrelated_owner_cannot_subscribe_to_operator_alerts(self):
        self.prepare();self.registry.senders['stranger']={'id':'stranger','username':'other'};self.message('alerts',sender='stranger')
        self.assertEqual(self.source.store.execute('SELECT * FROM service_alert_subscription'),[])
    def test_templates_are_two_copyable_messages_without_example_url_preview(self):
        self.message(payload='RF_SETUP_TEMPLATE');messages=[r['message']['text'] for r in self.registry.sent]
        self.assertEqual(len(messages),2);self.assertIn('My bike tips',messages[0]);self.assertEqual(messages[1].splitlines()[3],'Link:');self.assertNotIn('https://example.com',messages[0])
        from native.campaign_setup import draft_from_text
        parsed=draft_from_text(messages[0].replace('[your HTTPS link]','https://example.test/tips'))
        self.assertEqual(parsed['keywords'],['TIPS'])

if __name__=='__main__':unittest.main()
