"""Account-wide contact admission; self-hosted accounts remain unlimited."""
import time,uuid

def initialize(store):
    store.execute('CREATE TABLE IF NOT EXISTS plan_contacts (recipient_id TEXT PRIMARY KEY,created_at REAL NOT NULL)')
    store.execute('CREATE TABLE IF NOT EXISTS plan_contact_aliases (alias TEXT PRIMARY KEY,recipient_id TEXT NOT NULL)')
    # Count existing automation contacts once across flows, including the legacy store.
    store.execute('INSERT OR IGNORE INTO plan_contacts SELECT coalesce(a.recipient_id,w.recipient_id),? FROM workflow_contacts w LEFT JOIN plan_contact_aliases a ON a.alias=w.recipient_id WHERE w.opened=1',(time.time(),))
    store.execute('INSERT OR IGNORE INTO plan_contacts SELECT coalesce(a.recipient_id,c.id),? FROM contacts c LEFT JOIN plan_contact_aliases a ON a.alias=c.id',(time.time(),))
    if store.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='local_flow_contacts'"):
        store.execute('INSERT OR IGNORE INTO plan_contacts SELECT coalesce(a.recipient_id,c.recipient_id),? FROM local_flow_contacts c LEFT JOIN plan_contact_aliases a ON a.alias=c.recipient_id WHERE c.account_id=? AND (c.opened=1 OR c.link_sent=1)',(time.time(),str(store.config['account_id'])))

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
        alias=store.execute('SELECT recipient_id FROM plan_contact_aliases WHERE alias=?',(recipient,))
        if alias:recipient=alias[0]['recipient_id']
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

def reconcile(store,comment_author,dm_recipient):
    # Meta can use different IDs in comment and DM receipts for the same person.
    if not getattr(store,'config',{}).get('managed_plan') or comment_author==dm_recipient:return
    initialize(store)
    with store.lock:
        old=store.execute('SELECT recipient_id FROM plan_contact_aliases WHERE alias=?',(comment_author,))
        source=old[0]['recipient_id'] if old else comment_author
        new=store.execute('SELECT recipient_id FROM plan_contact_aliases WHERE alias=?',(dm_recipient,))
        target=new[0]['recipient_id'] if new else dm_recipient
        if source!=target:
            store.execute('DELETE FROM plan_contacts WHERE recipient_id=?',(source,))
            store.execute('INSERT OR IGNORE INTO plan_contacts VALUES(?,?)',(target,time.time()))
            store.execute('UPDATE plan_contact_aliases SET recipient_id=? WHERE recipient_id=?',(target,source))
        for alias in (source,comment_author,dm_recipient):
            store.execute('INSERT INTO plan_contact_aliases VALUES(?,?) ON CONFLICT(alias) DO UPDATE SET recipient_id=excluded.recipient_id',(alias,target))
