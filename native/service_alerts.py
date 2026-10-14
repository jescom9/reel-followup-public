"""Owner-verified, deduplicated operational replies within Instagram's reply window."""
import hashlib,json,time
try:from .profiles import read_values
except ImportError:from profiles import read_values

class ServiceAlerts:
    def __init__(self,registry,clock=time.time):self.registry,self.clock=registry,clock
    def initialize(self,store):
        store.execute('''CREATE TABLE IF NOT EXISTS service_alert_subscription (sender_id TEXT PRIMARY KEY,target_id TEXT NOT NULL,inbound_at REAL NOT NULL,last_signature TEXT NOT NULL DEFAULT '',last_sent REAL NOT NULL DEFAULT 0)''')
    def recipient_name(self):return read_values(self.registry.project/'.env').get('REEL_ALERT_USERNAME','').lstrip('@').casefold()
    def subscribe(self,source,sender,target,stamp,key):
        if not self.recipient_name() or target.store.config.get('username','').casefold()!=self.recipient_name():return False
        self.initialize(source.store);self.refresh(source,sender,stamp)
        source.store.execute('''INSERT INTO service_alert_subscription(sender_id,target_id,inbound_at) VALUES(?,?,?) ON CONFLICT(sender_id) DO UPDATE SET target_id=excluded.target_id,inbound_at=max(inbound_at,excluded.inbound_at)''',(sender,str(target.store.config['account_id']),stamp))
        source.store.flow_once('ops:subscribed:'+key,lambda:self.registry.graph(dict(source.store.config)).send({'id':sender},'Service alerts are on for @'+self.recipient_name()+'. I can reply for 24 hours after your latest message. Send alerts again to reopen that window.'))
        return True
    def refresh(self,source,sender,stamp):
        self.initialize(source.store);source.store.execute('UPDATE service_alert_subscription SET inbound_at=max(inbound_at,?) WHERE sender_id=?',(stamp,sender))
    def check(self,report):
        for identity in self.registry.listing():
            if not identity['enabled'] or not self.registry.campaign_setup.enabled(identity):continue
            found=self.registry.find_account(identity['account_id'])
            if not found:continue
            source=found[1];self.initialize(source.store)
            for row in source.store.execute('SELECT * FROM service_alert_subscription'):
                if not 0<=self.clock()-row['inbound_at']<86400:continue
                target=self.registry.find_account(row['target_id'])
                if not target or target[1].store.config.get('username','').casefold()!=self.recipient_name():continue
                items=report['capacity']['alerts'];signature=hashlib.sha256(json.dumps(sorted(items)).encode()).hexdigest()
                if row['last_signature']==signature:continue
                if row['last_sent'] and self.clock()-row['last_sent']<1800:continue
                text=('Service check:\n'+'\n'.join('• '+s for s in items[:6]) if items else 'Service check: website, worker and Neon are available. The encrypted standby backup is current.')+'\nDetails: Admin → Resources in your dashboard.'
                key='ops:check:'+row['sender_id']+':'+signature+':'+str(int(row['last_sent']))
                # The durable claim prevents an uncertain send from being repeated.
                try:
                    # Preserve any prior cloud-mode outcome before moving operational
                    # alerts to local claims. Customer campaigns still require Neon.
                    if source.store.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='local_flow_actions'"):
                        old=source.store.execute('SELECT state,receipt FROM local_flow_actions WHERE account_id=? AND action_id=?',(source.store.config['account_id'],key))
                        if old:source.store.execute('INSERT OR IGNORE INTO actions(id,state,receipt) VALUES(?,?,?)',(key,'sent' if old[0]['state']=='sent' else 'review',old[0]['receipt']))
                    source.store.once(key,lambda:self.registry.graph(dict(source.store.config)).send({'id':row['sender_id']},text))
                    source.store.execute('UPDATE service_alert_subscription SET last_signature=?,last_sent=? WHERE sender_id=?',(signature,self.clock(),row['sender_id']))
                except Exception:pass
