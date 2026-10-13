"""Authenticated Pi bridge: token enrollment, signed events and scoped controls."""
import hashlib,hmac,json,re,sqlite3,time
from pathlib import Path
from contextlib import closing
try:
    from .profiles import read_values
    from .workflows import flows,validate_flows
    from .webhook_queue import queued_event
    from . import hosted_history,hosted_metrics,hosted_activity,hosted_media
    from .storage import StorageBridge,backend_name
except ImportError:
    from profiles import read_values
    from workflows import flows,validate_flows
    from webhook_queue import queued_event
    import hosted_history,hosted_metrics,hosted_activity,hosted_media
    from storage import StorageBridge,backend_name

class HostService:
    def __init__(self,registry,clock=time.time):
        self.registry,self.clock=registry,clock
        self.folder=registry.project/'native/.local';self.path=self.folder/'host-requests.sqlite'
        with closing(sqlite3.connect(self.path)) as db:
            db.execute('CREATE TABLE IF NOT EXISTS requests (nonce TEXT PRIMARY KEY,created REAL NOT NULL)');db.commit()
        self.path.chmod(0o600)
    def values(self):return read_values(self.registry.project/'.env')
    def authenticate(self,path,raw,headers):
        secret=self.values().get('REEL_PI_SERVICE_SECRET','')
        stamp=headers.get('X-Reel-Time','');nonce=headers.get('X-Reel-Nonce','')
        if len(secret)<32 or not re.fullmatch(r'\d{10}',stamp) or not re.fullmatch(r'[a-f0-9]{32}',nonce):return False
        if abs(self.clock()-int(stamp))>90:return False
        signed='\n'.join(['reel-pi-v1',stamp,nonce,'POST',path,hashlib.sha256(raw).hexdigest()])
        expected=hmac.new(secret.encode(),signed.encode(),hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected,headers.get('X-Reel-Signature','')):return False
        try:
            with closing(sqlite3.connect(self.path,timeout=30)) as db:
                db.execute('DELETE FROM requests WHERE created<?',(self.clock()-180,))
                db.execute('INSERT INTO requests VALUES(?,?)',(nonce,self.clock()));db.commit()
            return True
        except sqlite3.IntegrityError:return False
    def reserved(self,config):
        ids={v.strip() for v in self.values().get('REEL_RESERVED_ACCOUNT_IDS','').split(',') if v.strip()}
        return bool(ids.intersection({str(config.get('account_id','')),*map(str,config.get('account_aliases',[]))}))
    def handle(self,path,data):
        if path=='/host/health':return {'ready':True,'storage':'encrypted-sqlite','accounts':len(self.registry.apps)}
        if path=='/host/connect':return self.registry.connect_hosted(data)
        found=self.registry.find_account(str(data.get('account_id') or ''))
        if path=='/host/events':
            if not found:return {'managed':False,'saved':0}
            _,app=found;items=data.get('events')
            if not isinstance(items,list) or len(items)>1000:raise ValueError('Invalid event batch.')
            for event in items:
                if not isinstance(event,dict) or not isinstance(event.get('payload'),dict) or event['payload'].get('kind') not in ('message','comment'):raise ValueError('Invalid event.')
                incoming={'event_id':event['id'],'payload':event['payload'],'received':event['payload'].get('received',self.clock()),'ig_account_id':data['account_id']}
                key,payload=queued_event(incoming,app.store.config['account_id']);app.store.enqueue(key,payload)
            return {'managed':True,'saved':len(items)}
        if path!='/host/portal' or not found:raise ValueError('Account is not connected on this host.')
        identifier,app=found;config=dict(app.store.config);op=data.get('operation');value=data.get('data') or {}
        if op=='status':
            history=None
            if backend_name(app.store.env_file)=='sqlite':
                with StorageBridge(app.store.env_file,app.store.folder):pass
                history=hosted_history.summary(app.store)
            return {'username':config['username'],'account_id':config['account_id'],'enabled':config['enabled'],'flows':flows(config),
                'metrics':hosted_metrics.summary(app.store,flows(config),include_legacy=history is not None),'history':history,'reserved':self.reserved(config),'credentials':{'stored':bool(app.store.vault.get()),'expires_at':config.get('token_expires_at',0)}}
        if op=='media.list':return hosted_media.list_media(app,self.registry.graph,value)
        if op=='activity.list':
            local=backend_name(app.store.env_file)=='sqlite'
            if local:
                with StorageBridge(app.store.env_file,app.store.folder):pass
            return hosted_activity.list_activity(app.store,flows(config),value,local_history=local)
        if op in ('archive.list','archive.conversation'):
            if backend_name(app.store.env_file)!='sqlite':raise ValueError('This archive is available in the private Pi dashboard. Contact the host to enable it here.')
            with StorageBridge(app.store.env_file,app.store.folder):pass
            return hosted_history.chats(app.store,value) if op=='archive.list' else hosted_history.conversation(app.store,value)
        if op=='account.toggle':
            if not isinstance(value.get('enabled'),bool):raise ValueError('Invalid account pause setting.')
            if value['enabled'] and self.reserved(config):raise ValueError('This account runs on another installation. Ask the host to migrate it before activating this workspace.')
            config.update(enabled=value['enabled'],workflow_mode='manychat')
            if value['enabled'] and not config.get('campaign_started_at'):config['campaign_started_at']=self.clock()
        elif op=='flows.save':
            selected=validate_flows(value.get('flows'))
            hosted_media.verify_new_selections(app,self.registry.graph,selected,flows(config))
            config['flows']=selected;config['workflow_mode']='manychat'
            placeholders=','.join('?' for f in config['flows'])
            app.store.execute("UPDATE workflow_jobs SET state='cancelled',detail='Flow removed.' WHERE state IN ('waiting','waiting_inbound') AND flow_id NOT IN ("+placeholders+")",[f['id'] for f in config['flows']])
        elif op=='flows.toggle':
            if value.get('setting') not in ('enabled','followup_enabled') or not isinstance(value.get('value'),bool):raise ValueError('Invalid flow pause setting.')
            current=flows(config);target=next((f for f in current if f['id']==value.get('id')),None)
            if not target:raise ValueError('Flow does not exist.')
            target[value['setting']]=value['value'];config['flows']=validate_flows(current)
        else:raise ValueError('Unsupported account operation.')
        app.store.save(config);return {'saved':True}
