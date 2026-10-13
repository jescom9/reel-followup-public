"""Account-wide contact admission; self-hosted accounts remain unlimited."""
import time,uuid

def initialize(store):
    store.execute('CREATE TABLE IF NOT EXISTS plan_contacts (recipient_id TEXT PRIMARY KEY,created_at REAL NOT NULL)')
    # Count existing automation contacts once across flows, including the legacy store.
    store.execute('INSERT OR IGNORE INTO plan_contacts SELECT recipient_id,? FROM workflow_contacts WHERE opened=1',(time.time(),))
    store.execute('INSERT OR IGNORE INTO plan_contacts SELECT id,? FROM contacts',(time.time(),))
    if store.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='local_flow_contacts'"):
        store.execute('INSERT OR IGNORE INTO plan_contacts SELECT recipient_id,? FROM local_flow_contacts WHERE account_id=? AND (opened=1 OR link_sent=1)',(time.time(),str(store.config['account_id'])))

def managed(store):
    initialize(store)
    if not store.config.get('managed_plan'):
        store.save({**store.config,'managed_plan':{'name':'free','source':'free','generation':uuid.uuid4().hex}})
    return summary(store)

def summary(store):
    initialize(store);plan=store.config.get('managed_plan') or {}
    used=store.execute('SELECT count(*) n FROM plan_contacts')[0]['n']
    pro=plan.get('name')=='pro' and (plan.get('source')=='promotion' or plan.get('valid_until',0)>time.time())
    return {'name':'pro' if pro else 'free','source':plan.get('source','free'),'limit':5000 if pro else 50,'used':used,
            'generation':plan.get('generation',''),'subscription_id':plan.get('subscription_id',''),'customer_id':plan.get('customer_id',''),'remaining':max(0,(5000 if pro else 50)-used)}

def admit(store,recipient):
    if not getattr(store,'config',{}).get('managed_plan'):return True
    initialize(store)
    with store.lock:
        if store.execute('SELECT recipient_id FROM plan_contacts WHERE recipient_id=?',(recipient,)):return True
        if summary(store)['remaining']<=0:return False
        store.execute('INSERT OR IGNORE INTO plan_contacts VALUES(?,?)',(recipient,time.time()));return True

def apply(store,value):
    managed(store);plan=dict(store.config['managed_plan'])
    if value.get('generation')!=plan['generation']:raise ValueError('This checkout belongs to an earlier workspace. Start again from Plans.')
    if value.get('source') not in ('promotion','stripe'):raise ValueError('Invalid plan activation.')
    if value['source']=='stripe' and not isinstance(value.get('valid_until'),(int,float)):raise ValueError('Missing subscription expiry.')
    # A late webhook cannot replace a newer subscription.
    if value.get('subscription_id') and plan.get('subscription_id') and value['subscription_id']!=plan['subscription_id']:raise ValueError('Subscription does not match this workspace.')
    if value.get('event_created',0)<plan.get('event_created',0):return summary(store)
    plan.update({key:value[key] for key in ('source','valid_until','subscription_id','customer_id','session_id','event_created') if key in value})
    plan['name']='pro';store.save({**store.config,'managed_plan':plan});return summary(store)
