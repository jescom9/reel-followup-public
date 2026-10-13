import unittest,tempfile
from pathlib import Path
from native.app import Store
from native.workflows import WorkflowEngine
from native.plans import managed,summary,admit,apply

class PlanTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.store=Store(Path(self.tmp.name)/'profile',Path(self.tmp.name)/'.env');self.addCleanup(self.store.db.close)
        self.store.config['account_id']='123';WorkflowEngine(self.store,None,None)
    def test_free_boundary_existing_contacts_and_cross_flow_dedup(self):
        self.store.execute("INSERT INTO workflow_contacts VALUES('one','same',1,0,0,0)")
        self.store.execute("INSERT INTO workflow_contacts VALUES('two','same',1,0,0,0)")
        self.assertEqual(managed(self.store)['used'],1)
        for n in range(49):self.assertTrue(admit(self.store,str(n)))
        self.assertFalse(admit(self.store,'new'));self.assertTrue(admit(self.store,'same'));self.assertEqual(summary(self.store)['used'],50)
    def test_promotion_paid_expiry_generation_and_pro_limit(self):
        p=managed(self.store)
        with self.assertRaises(ValueError):apply(self.store,{'source':'promotion','generation':'foreign'})
        p=apply(self.store,{'source':'promotion','generation':p['generation']});self.assertEqual(p['limit'],5000)
        for n in range(5000):self.store.execute('INSERT INTO plan_contacts VALUES(?,0)',(str(n),))
        self.assertFalse(admit(self.store,'over'))
        p=apply(self.store,{'source':'stripe','generation':p['generation'],'valid_until':0,'event_created':2});self.assertEqual(p['limit'],50)
        p=apply(self.store,{'source':'stripe','generation':p['generation'],'valid_until':2000000000,'event_created':1});self.assertEqual(p['limit'],50)
    def test_self_hosted_has_no_managed_cap(self):
        for n in range(51):self.assertTrue(admit(self.store,str(n)))
        self.assertNotIn('managed_plan',self.store.config)

    def test_comment_and_dm_ids_are_one_contact_across_flows(self):
        from native.plans import reconcile
        managed(self.store);admit(self.store,'comment-id');reconcile(self.store,'comment-id','dm-id')
        self.store.execute("INSERT INTO workflow_contacts VALUES('flow','dm-id',1,0,0,0)")
        self.assertEqual(summary(self.store)['used'],1)
        self.assertTrue(admit(self.store,'comment-id'));self.assertTrue(admit(self.store,'dm-id'))
        self.assertEqual(summary(self.store)['used'],1)
