#!/usr/bin/env python3
"""Single-account Instagram automation for Mac or Raspberry Pi."""
import hashlib, hmac, json, os, re, secrets, sqlite3, threading, time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
try:
    from .followup import NeonBridge, ArchiveError, PHRASE, TEXT, RULE, deliver, message_page
    from .manychat import ManychatFlow
    from .follower_checks import FollowerChecks
    from .workflows import WorkflowEngine,flows,validate_flows
    from .hosted_media import verify_new_selections
    from .historical_comments import HistoricalComments
    from .webhook_queue import queued_event
    from .neon_http import NeonHTTP
    from .storage import backend_name,delivery_mode
    from .local_storage import LocalStorage
    from .token_vault import TokenVault
    from .public_replies import PublicReplies
except ImportError:
    from followup import NeonBridge, ArchiveError, PHRASE, TEXT, RULE, deliver, message_page
    from manychat import ManychatFlow
    from follower_checks import FollowerChecks
    from workflows import WorkflowEngine,flows,validate_flows
    from hosted_media import verify_new_selections
    from historical_comments import HistoricalComments
    from webhook_queue import queued_event
    from neon_http import NeonHTTP
    from storage import backend_name,delivery_mode
    from local_storage import LocalStorage
    from token_vault import TokenVault
    from public_replies import PublicReplies

ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = ROOT.parent
ENV_FILE = PROJECT_ROOT / '.env'
DATA = ROOT / '.local'
DAY = 86400
PAYLOADS = {'BF_LINK', 'BF_FOLLOW'}
DEFAULTS = dict(account_id='', app_id='', access_token='', app_secret='', verify_token='', api_version='v22.0', media_id='', keyword='Fit', enabled=False, verified=False, username='', public_reply=True, public_webhook_origin='', campaign_started_at=0,
    workflow_mode='poll',account_aliases=[],webhook_verified=False)

def read_env(path=None):
    path=Path(path or ENV_FILE)
    values = {}
    if path.exists():
        for line in path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                values[key.strip()] = value.strip().strip('"').strip("'")
    return values

def account_identity(profile, config):
    account_id = str(profile.get('user_id') or profile.get('id') or '')
    if not account_id or not profile.get('username'):
        raise ValueError('Instagram did not return a verified account identity.')
    if config.get('account_id') and account_id != str(config['account_id']):
        raise ValueError('The token belongs to another account. Use a separate worker installation for that account.')
    aliases = sorted({str(profile[key]) for key in ('user_id', 'id') if profile.get(key)})
    return account_id, aliases

def save_instagram_env(config,path=None):
    path=Path(path or ENV_FILE)
    # Preserve other project settings. This file is ignored by Git and restricted to the owner.
    lines = path.read_text().splitlines() if path.exists() else []
    managed = {'IG_APP_ID': str(config.get('app_id', '')), 'IG_APP_SECRET': str(config.get('app_secret', '')), 'IG_ACCESS_TOKEN': ''}
    out, seen = [], set()
    for line in lines:
        key = line.split('=', 1)[0].strip() if '=' in line else ''
        if key in managed:
            if key not in seen: out.append(f'{key}={managed[key]}'); seen.add(key)
        else: out.append(line)
    for key, value in managed.items():
        if key not in seen: out.append(f'{key}={value}')
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as f: f.write('\n'.join(out).rstrip() + '\n')
    os.chmod(path, 0o600)

class MetaError(Exception):
    def __init__(self,message,code=None,subcode=None,diagnostic=''):
        super().__init__(message)
        self.code,self.subcode,self.diagnostic = code,subcode,diagnostic

class Graph:
    def __init__(self, config): self.c = config
    def call(self, method, path, data=None, **query):
        url = 'https://graph.instagram.com/' + self.c['api_version'] + '/' + path
        if query: url += '?' + urlencode(query)
        req = Request(url, data=None if data is None else json.dumps(data).encode(), method=method,
                      headers={'Authorization': 'Bearer ' + self.c['access_token'], 'Content-Type': 'application/json'})
        for attempt in range(3 if method == 'GET' else 1):
            try:
                with urlopen(req, timeout=30) as response: return json.load(response)
            except HTTPError as e:
                # Never expose response bodies or credentials through the dashboard.
                try: meta = json.load(e).get('error', {})
                except Exception: meta = {}
                code,subcode = meta.get('code','unknown'),meta.get('error_subcode')
                diagnostic = str(meta.get('message',''))
                for secret in (self.c.get('access_token'),self.c.get('app_secret')):
                    if secret: diagnostic = diagnostic.replace(secret,'[redacted]')
                raise MetaError(f'Meta rejected the request (HTTP {e.code}, code {code}).',code,subcode,diagnostic) from None
            except (URLError, TimeoutError, OSError):
                if method == 'GET' and attempt < 2:
                    time.sleep(attempt + 1)
                    continue
                if method == 'GET': raise MetaError('Instagram read timed out after retries; saved pages are retained for resume.') from None
                raise MetaError('Network result unknown; inspect Instagram before retrying a send.') from None
    def send(self, recipient, text, button=None):
        message = {'text': text}
        if button:
            label, payload = button
            message['quick_replies'] = [{'content_type': 'text', 'title': label, 'payload': payload}]
        return self.call('POST', self.c['account_id'] + '/messages', {'recipient': recipient, 'message': message})
    def send_button(self,recipient,text,label,payload,quick=False):
        if quick: return self.send(recipient,text,(label,payload))
        message={'attachment':{'type':'template','payload':{'template_type':'generic',
            'elements':[{'title':text,'buttons':[{'type':'postback','title':label,'payload':payload}]}]}}}
        return self.call('POST',self.c['account_id']+'/messages',{'recipient':recipient,'message':message})
    def send_link(self,recipient,text,label,url):
        message={'attachment':{'type':'template','payload':{'template_type':'generic',
            'elements':[{'title':text,'buttons':[{'type':'web_url','title':label,'url':url}]}]}}}
        return self.call('POST',self.c['account_id']+'/messages',{'recipient':recipient,'message':message})

class Store:
    def __init__(self, folder,env_file=None):
        self.env_file=Path(env_file or ENV_FILE)
        self.folder = Path(folder); self.folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.folder, 0o700)
        self.lock = threading.RLock()
        self.vault = TokenVault(self.folder)
        self.db = sqlite3.connect(self.folder / 'events.sqlite', check_same_thread=False)
        os.chmod(self.folder / 'events.sqlite', 0o600)
        self.db.row_factory = sqlite3.Row
        self.db.executescript('''
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS events (id TEXT PRIMARY KEY, payload TEXT, state TEXT, detail TEXT, created REAL);
        CREATE TABLE IF NOT EXISTS actions (id TEXT PRIMARY KEY, state TEXT, receipt TEXT);
        CREATE TABLE IF NOT EXISTS contacts (id TEXT PRIMARY KEY, inbound REAL DEFAULT 0, link_sent INTEGER DEFAULT 0);
        ''')
        self.db.execute("UPDATE events SET state='review',detail='Interrupted processing; inspect delivery before retrying.' WHERE state='processing'")
        self.db.commit()
        self.path = self.folder / 'config.json'
        self.config = {**DEFAULTS, **(json.loads(self.path.read_text()) if self.path.exists() else {})}
        env = read_env(self.env_file)
        self.config.update(app_id=env.get('IG_APP_ID', self.config['app_id']), app_secret=env.get('IG_APP_SECRET', self.config['app_secret']), access_token=env.get('IG_ACCESS_TOKEN', self.config['access_token']))
        credential=self.vault.get()
        if env.get('IG_ACCESS_TOKEN'):
            self.vault.put(env['IG_ACCESS_TOKEN'],self.config.get('account_id',''),self.config.get('app_id',''))
            if self.folder.resolve() in (self.env_file.parent.resolve(),(self.env_file.parent/'native/.local').resolve()):save_instagram_env(self.config,self.env_file)
        elif credential:
            self.config['access_token']=credential['access_token']
            self.config['token_expires_at']=credential.get('expires_at',0)
        elif self.config['access_token']:
            self.vault.put(self.config['access_token'],self.config.get('account_id',''),self.config.get('app_id',''))
        self.config['link_url'] = env.get('REEL_LINK_URL') or self.config.get('link_url') or 'https://example.com/'
        link = urlsplit(self.config['link_url'])
        if link.scheme != 'https' or not link.netloc or link.username or link.password:
            raise ValueError('REEL_LINK_URL must be a public HTTPS URL without embedded credentials.')
        if env.get('IG_WEBHOOK_VERIFY_TOKEN'):
            if self.config['verify_token'] != env['IG_WEBHOOK_VERIFY_TOKEN']:
                self.config['webhook_verified'] = False
            self.config['verify_token'] = env['IG_WEBHOOK_VERIFY_TOKEN']
        if self.config['enabled'] and not self.config['campaign_started_at']:
            self.config['enabled'] = False
        if not self.config['verify_token']:
            self.config['verify_token'] = secrets.token_hex(24); self.save(self.config)
    def save(self, config):
        with self.lock:
            if config.get('access_token'):self.vault.put(config['access_token'],config.get('account_id',''),config.get('app_id',''),config.get('token_expires_at',0))
            save_instagram_env(config,self.env_file)
            temp = self.path.with_suffix('.tmp')
            fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            persisted = {k:v for k,v in config.items() if k not in ('access_token', 'app_secret')}
            with os.fdopen(fd, 'w') as f: json.dump(persisted, f)
            os.replace(temp, self.path); self.config = dict(config)
    def execute(self, sql, args=()):
        with self.lock:
            cur = self.db.execute(sql, args); rows = cur.fetchall(); self.db.commit(); return rows
    def ingest(self, body):
        c = self.config
        own={str(c['account_id']),*map(str,c.get('account_aliases',[]))}
        for entry in body.get('entry', []):
            if str(entry.get('id')) not in own: continue
            changes = entry.get('changes', [])
            if entry.get('field'): changes = [entry] + changes
            for change in changes:
                value = change.get('value', {})
                if change.get('field') == 'comments' and value.get('id'):
                    self.enqueue('comment:' + str(value['id']), {'kind': 'comment', 'value': value})
            for msg in entry.get('messaging', []):
                message = msg.get('message', {})
                if message.get('is_echo') or str(msg.get('sender', {}).get('id')) in own: continue
                if str(msg.get('recipient', {}).get('id')) not in own: continue
                post = msg.get('postback', {})
                mid = message.get('mid') or post.get('mid')
                if not mid and not (post.get('payload') and msg.get('timestamp')): continue
                if not (message or post): continue
                identity=[msg.get('sender',{}).get('id'),c['account_id'],msg.get('timestamp'),post.get('payload'),post.get('title'),mid]
                digest=hashlib.sha256(json.dumps(identity,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
                key='postback:'+digest if post.get('payload') else 'message:'+str(mid or digest)
                normalized={**msg,'recipient':{**msg.get('recipient',{}),'id':c['account_id']}}
                self.enqueue(key, {'kind': 'message', 'value': normalized})
    def enqueue(self, key, value):
        self.execute('INSERT OR IGNORE INTO events VALUES (?,?,?,?,?)', (key, json.dumps(value), 'pending', '', time.time()))
    def once(self, key, callback):
        # Claim before network I/O: crash/timeout never causes blind duplicate sends.
        with self.lock:
            old = self.db.execute('SELECT state,receipt FROM actions WHERE id=?', (key,)).fetchone()
            if old:
                if old['state'] == 'sent': return json.loads(old['receipt'])
                raise MetaError('Previous send outcome needs manual review; not sent again.')
            self.db.execute('INSERT INTO actions VALUES (?, ?, ?)', (key, 'attempting', '{}')); self.db.commit()
        try:
            receipt = callback()
            if not (receipt.get('message_id') or receipt.get('id')):
                raise MetaError('No message receipt returned; inspect delivery before retrying.')
        except Exception:
            self.execute("UPDATE actions SET state='review' WHERE id=?", (key,)); raise
        self.execute("UPDATE actions SET state='sent',receipt=? WHERE id=?", (json.dumps(receipt), key))
        return receipt
    def flow_once(self,key,callback):
        identity={'ig_account_id':self.config['account_id'],'action_id':key}
        with NeonBridge(self.env_file,self.folder) as db:
            claim=db.request({'flow_action_claim':identity})
            if not claim.get('claimed'):
                if claim.get('state')=='sent': return claim['receipt']
                raise MetaError('This flow send is already claimed or needs review; it was not sent again.')
            if backend_name(self.env_file)=='neon':
                with LocalStorage(self.folder) as local:local.request({'flow_action_claim':identity})
            try:
                receipt=callback()
                if not (receipt.get('message_id') or receipt.get('id')): raise MetaError('No message receipt returned; inspect delivery before retrying.')
            except Exception as error:
                state='rejected' if isinstance(error,MetaError) and error.code is not None else 'review'
                db.request({'flow_action_finish':{**identity,'state':state}})
                if backend_name(self.env_file)=='neon':
                    with LocalStorage(self.folder) as local:local.request({'flow_action_finish':{**identity,'state':state}})
                raise
            db.request({'flow_action_finish':{**identity,'state':'sent','receipt':receipt}})
            if backend_name(self.env_file)=='neon':
                with LocalStorage(self.folder) as local:
                    local.request({'flow_action_claim':identity})
                    local.request({'flow_action_finish':{**identity,'state':'sent','receipt':receipt}})
            return receipt
    def flow_contact_get(self,sender):
        with NeonBridge(self.env_file,self.folder) as db:
            return db.request({'flow_contact_get':{'ig_account_id':self.config['account_id'],'recipient_id':sender}})['contact']
    def flow_contact_put(self,sender,**values):
        with NeonBridge(self.env_file,self.folder) as db:
            db.request({'flow_contact_put':{'ig_account_id':self.config['account_id'],'recipient_id':sender,**values}})

class Engine:
    def __init__(self, store, graph_factory=Graph, clock=time.time):
        self.s,self.factory,self.clock=store,graph_factory,clock
        self.setup_handler=None
        self.manychat=ManychatFlow(store,graph_factory,clock)
        self.checks=FollowerChecks(store,graph_factory,self.manychat.send_verified_link,clock)
        self.manychat.checks=self.checks
        self.workflows=WorkflowEngine(store,graph_factory,self.manychat,clock)
        self.next_workflow_check=0
        self.public_replies=PublicReplies(store,graph_factory,clock,recover=True)
        self.historical=HistoricalComments(store,graph_factory,self.workflows,clock,recover=True)
    def run_one(self):
        c = dict(self.s.config)
        if not (c['enabled'] and c['verified']): return False
        if self.public_replies.run_one(c): return True
        if self.historical.run_one(c): return True
        if c.get('workflow_mode')=='manychat' and self.clock()>=self.next_workflow_check:
            self.next_workflow_check=self.clock()+2
            if self.workflows.run_one(c): return True
        rows = self.s.execute("SELECT * FROM events WHERE state='pending' ORDER BY created LIMIT 1")
        if not rows: return self.workflows.run_one(c) if c.get('workflow_mode')=='manychat' else False
        event = rows[0]; self.s.execute("UPDATE events SET state='processing' WHERE id=?", (event['id'],))
        try:
            detail = self.process(event['id'], json.loads(event['payload']), c)
            self.s.execute("UPDATE events SET state='done',detail=? WHERE id=?", (detail, event['id']))
        except Exception as e:
            detail = str(e) if isinstance(e, MetaError) else 'Processing failed. Check configuration; event retained for review.'
            self.s.execute("UPDATE events SET state='review',detail=? WHERE id=?", (detail, event['id']))
        if c.get('workflow_mode')=='manychat' and delivery_mode(self.s.env_file)=='neon':
            result=self.s.execute('SELECT state,detail FROM events WHERE id=?',(event['id'],))[0]
            try:
                with NeonHTTP(self.s.env_file) as db:
                    payload=json.loads(event['payload'])
                    db.request({'webhook_finish':{'ig_account_id':payload.get('queue_account_id') or c['account_id'],'event_id':payload.get('queue_event_id') or event['id'],
                        'state':'done' if result['state']=='done' else 'review','detail':result['detail']}})
            except Exception: pass  # The local event and global send claims are already durable.
        return True
    def process(self, key, event, c):
        if self.setup_handler:
            result=self.setup_handler(key,event,c)
            if result is not None:return result
        if c.get('workflow_mode')=='manychat': return self.workflows.process(key,event,c)
        api = self.factory(c); v = event['value']; now = self.clock()
        if event['kind'] == 'comment':
            sender = str(v.get('from', {}).get('id', ''))
            media = str(v.get('media', {}).get('id', ''))
            if not sender or sender == c['account_id'] or media != c['media_id'] or v.get('parent_id'):
                return 'Comment outside campaign.'
            if not re.search(r'(?<!\w)' + re.escape(c['keyword']) + r'(?!\w)', v.get('text', ''), re.I):
                return 'Keyword not matched.'
            # Use the actual creation timestamp, not webhook receipt time.
            comment = api.call('GET', str(v['id']), fields='timestamp')
            created = datetime.fromisoformat(comment['timestamp'].replace('Z', '+00:00')).timestamp()
            if created<float(c.get('campaign_started_at') or 0):return 'Comment predates the enabled campaign.'
            if not 0 <= now - created < 7 * DAY: return 'Comment outside private-reply window.'
            opening_key = f"opening:{media}:{sender}"
            self.s.once(opening_key, lambda: api.send({'comment_id': str(v['id'])},
                'Here is your link: '+c['link_url']))
            if c['public_reply']:
                self.s.once(opening_key + ':public', lambda: api.call('POST', str(v['id']) + '/replies', {'message': 'Sent you a message! Check it out!'}))
            return 'Opening DM accepted; public reply follows successful delivery.'
        sender = str(v.get('sender', {}).get('id', ''))
        stamp = float(v.get('timestamp', 0)) / 1000
        if not sender or not 0 <= now - stamp < DAY: return 'Message outside 24-hour response window.'
        self.s.execute('INSERT INTO contacts(id,inbound) VALUES (?,?) ON CONFLICT(id) DO UPDATE SET inbound=MAX(inbound,excluded.inbound)', (sender, stamp))
        message, post = v.get('message', {}), v.get('postback', {})
        payload = message.get('quick_reply', {}).get('payload') or post.get('payload')
        if payload not in PAYLOADS: return 'Message retained; no campaign button matched.'
        # Require an actual campaign opening for this contact, not arbitrary button text.
        opened = self.s.execute("SELECT id FROM actions WHERE id=? AND state='sent'", (f"opening:{c['media_id']}:{sender}",))
        if not opened: return 'No matching campaign opening.'
        sent = self.s.execute('SELECT link_sent FROM contacts WHERE id=?', (sender,))[0]['link_sent']
        if sent:
            self.s.once(key + ':return', lambda: api.send({'id': sender}, 'Here is your link again: '+c['link_url']))
            return 'Returning-user link sent.'
        try:
            # Deliberately no cache: every response button reads current Meta status.
            status = api.call('GET', sender, fields='is_user_follow_business').get('is_user_follow_business')
        except MetaError: status = None
        if status is True:
            self.s.once(key + ':link', lambda: api.send({'id': sender}, 'Here is your link: '+c['link_url']))
            self.s.execute('UPDATE contacts SET link_sent=1 WHERE id=?', (sender,))
            return 'Follower verified; link accepted by Meta.'
        if status is False:
            text = f"Bitte folge @{c['username']}, um meine Arbeit zu unterstützen 🥹🫶🏽 Drücke anschließend „Ich folge dir“ 😊👇"
            label = 'Ich folge dir'
        else:
            text = 'Ich kann gerade nicht prüfen, ob du mir folgst. Bitte versuche es später noch einmal 😊'
            label = 'Erneut prüfen'
        self.s.once(key + ':follow', lambda: api.send({'id': sender}, text, (label, 'BF_FOLLOW')))
        return 'Follow prompt sent.' if status is False else 'Status unavailable; retry offered.'

class App:
    def __init__(self, folder=DATA,env_file=None):
        self.store = Store(folder,env_file); self.nonce = secrets.token_urlsafe(32); self.stop = threading.Event()
        self.lifecycle=threading.RLock()
        self.threads=[]
        self.thread_lock=threading.Lock()
        self.engine = Engine(self.store)
        self.next_poll = 0
        self.poll_status = 'Waiting for campaign to be enabled.'
        self.archive_lock = threading.Lock()
        self.archive = {'state':'idle','detail':'Chat archive has not synced yet.','conversations':0,'messages':0,'updated':None}
        self.followup_lock = threading.Lock()
        self.followup = {'state':'idle','detail':'Check matching chats, then send to everyone with an open reply window.',
            'processed':0,'total':0,'sent':0,'skipped':0,'review':0,'text':TEXT}
        self.dashboard_lock = threading.Lock()
        self.dashboard = {'state':'loading','stats':{},'rows':[],'total':0,'page':0}
        self.webhook_status={'state':'idle','detail':'Webhook service is paused.','stats':{},'url':self.webhook_url}
    def start_task(self,task):
        with self.thread_lock:
            if self.stop.is_set():return
            self.threads=[t for t in self.threads if t.is_alive()]
            thread=threading.Thread(target=task,daemon=True);self.threads.append(thread);thread.start()
    @property
    def webhook_url(self):
        values=read_env(self.store.env_file)
        return values.get('REEL_WEBHOOK_URL') or (self.store.config.get('public_webhook_origin','').rstrip('/')+'/webhook' if self.store.config.get('public_webhook_origin') else 'https://reelfollowups.app/api/instagram/webhook' if delivery_mode(self.store.env_file)=='neon' else '')
    def webhook_worker(self):
        while not self.stop.is_set():
            c=dict(self.store.config)
            if delivery_mode(self.store.env_file)!='neon':
                try:
                    with LocalStorage(self.store.folder) as db:stats=db.request({'webhook_stats':True,'ig_account_id':c['account_id']})['stats']
                    self.webhook_status={'state':'ready','detail':'Direct signed webhooks are stored on this host.','stats':stats,'url':self.webhook_url}
                except Exception:self.webhook_status={'state':'error','detail':'Local webhook storage unavailable.','stats':{},'url':self.webhook_url}
                self.stop.wait(5);continue
            if c['verified']:
                try:
                    with NeonHTTP(self.store.env_file) as db:
                        if c.get('workflow_mode')=='manychat':
                            events=db.request({'webhook_pull':True,'ig_account_id':c['account_id'],'account_aliases':c.get('account_aliases',[])}).get('events',[])
                            for event in events:
                                identifier,payload=queued_event(event,c['account_id'])
                                self.store.enqueue(identifier,payload)
                                saved=self.store.execute('SELECT state,detail FROM events WHERE id=?',(identifier,))[0]
                                db.request({'webhook_finish':{'ig_account_id':event.get('ig_account_id') or c['account_id'],'event_id':event['event_id'],'state':'done' if saved['state']=='done' else 'imported','detail':saved['detail']}})
                        stats=db.request({'webhook_stats':True,'ig_account_id':c['account_id'],'account_aliases':c.get('account_aliases',[])})['stats']
                    self.webhook_status={'state':'ready','detail':'Cloud events are saved in Neon. Replies run while this service is running.','stats':stats,'url':self.webhook_url}
                except Exception:
                    self.webhook_status={'state':'error','detail':'Could not read the webhook queue. Saved events remain in Neon for retry.','stats':self.webhook_status.get('stats',{}),'url':self.webhook_url}
            self.stop.wait(5 if c.get('workflow_mode')=='manychat' else 30)
    def chat_overview(self, page=0, view='matches'):
        with NeonBridge(self.store.env_file,self.store.folder) as db:
            return db.request({'overview':True,'ig_account_id':self.store.config['account_id'],
                'phrase':PHRASE,'rule_key':RULE,'page':page,'view':view})
    def refresh_dashboard(self):
        if not self.dashboard_lock.acquire(blocking=False): return
        try:
            result = self.chat_overview()
            self.dashboard = {'state':'ready',**result}
        except Exception:
            self.dashboard = {**self.dashboard,'state':'error','detail':'Could not load the archive. Try refreshing.'}
        finally: self.dashboard_lock.release()
    def dashboard_worker(self):
        while not self.stop.is_set():
            if self.store.config['verified'] or backend_name(self.store.env_file)=='sqlite': self.refresh_dashboard()
            self.stop.wait(3600 if backend_name(self.store.env_file)=='neon' else 30)
    def start_followup(self, retry_rejected=False):
        c = dict(self.store.config)
        if not c['verified']: raise ValueError('Verify your Instagram account before sending follow-ups.')
        with self.followup_lock:
            if self.followup['state'] == 'sending': return False
            self.followup = {'state':'sending','detail':'Checking matching chats against the live inbox…',
                'processed':0,'total':0,'sent':0,'skipped':0,'review':0,'text':TEXT}
        def run():
            try:
                api = Graph(c)
                profile = api.call('GET','me',fields='user_id,username')
                account_identity(profile, c)
                with NeonBridge(self.store.env_file,self.store.folder) as db:
                    targets = db.request({'targets':True,'ig_account_id':c['account_id'],'rule_key':RULE,'phrase':PHRASE,
                        'retry_rejected':retry_rejected}).get('targets',[])
                    self.followup['total'] = len(targets)
                    for target in targets:
                        if self.stop.is_set(): break
                        try: state = deliver(api,db,self.store,target,c,retry_rejected=retry_rejected)
                        except (MetaError,ArchiveError): state = 'review'
                        self.followup['processed'] += 1
                        if state == 'sent': self.followup['sent'] += 1
                        elif state in ('review','rejected'): self.followup['review'] += 1
                        else: self.followup['skipped'] += 1
                        self.followup['detail'] = f'Checked {self.followup["processed"]} of {len(targets)} chats · {self.followup["sent"]} sent · {self.followup["skipped"]} skipped · {self.followup["review"]} need review.'
                        self.store.execute('INSERT INTO events VALUES (?,?,?,?,?)',
                            ('followup-result:' + secrets.token_hex(12),json.dumps({'kind':'followup-result'}),
                             'done' if state=='sent' else 'review' if state in ('review','rejected') else 'skipped',
                             f'@{target.get("username") or "Instagram user"}: follow-up {state}.',time.time()))
                        self.stop.wait(1)
                self.followup['state'] = 'ready'
                if not targets: self.followup['detail'] = 'No unsent matching chats have an open reply window right now.'
            except Exception as error:
                self.followup.update(state='error',detail=str(error) if isinstance(error,(MetaError,ValueError,ArchiveError)) else 'The batch stopped. Saved delivery receipts prevent duplicate sends.')
            self.refresh_dashboard()
        self.start_task(run)
        return True
    def sync_chat_history(self):
        c = dict(self.store.config)
        if not (c['verified'] and c['account_id'] and c['access_token']):
            raise ValueError('Verify your Instagram account before syncing chat history.')
        with NeonBridge(self.store.env_file,self.store.folder) as db:
            _saved_result = db.request({'manifest':True,'ig_account_id':c['account_id']})
            manifest_result = _saved_result
            manifest = {str(row['conversation_id']):row for row in manifest_result.get('manifest',[])}
            saved_index_marker = next(((key,row.get('archive_next_conversation_cursor')) for key,row in manifest.items()
                if row.get('archive_next_conversation_cursor')), None)
            api = Graph(c)
            saved_conversations = 0
            saved_messages = 0
            unavailable_conversations = 0
            unchanged_conversations = 0
            scanned_conversations = 0
            conversation_cursor = saved_index_marker[1] if saved_index_marker else None
            conversation_marker_id = saved_index_marker[0] if saved_index_marker else None
            seen_conversation_cursors = {conversation_cursor} if conversation_cursor else set()
            while True:
                query = {'platform':'instagram','fields':'id,participants,updated_time','limit':'100'}
                if conversation_cursor: query['after'] = conversation_cursor
                try:
                    page = api.call('GET', c['account_id'] + '/conversations', **query)
                except MetaError as e:
                    if conversation_cursor and '(HTTP 400, code 100)' in str(e):
                        _saved_result = db.request({'index_cursor':{'ig_account_id':c['account_id'],
                            'cursor':None,'conversation_id':conversation_marker_id}})
                        _saved_result
                        conversation_cursor = None; conversation_marker_id = None; seen_conversation_cursors.clear()
                        continue
                    raise
                conversations = page.get('data', [])
                if not conversations:
                    if conversation_marker_id:
                        _saved_result = db.request({'index_cursor':{'ig_account_id':c['account_id'],
                            'cursor':None,'conversation_id':conversation_marker_id}})
                        _saved_result
                    break
                for conversation in conversations:
                    conversation_id = str(conversation.get('id') or '')
                    if not conversation_id: continue
                    scanned_conversations += 1
                    participant_data = conversation.get('participants') or []
                    participants = participant_data.get('data', []) if isinstance(participant_data, dict) else participant_data
                    if not isinstance(participants, list): participants = []
                    old = manifest.get(conversation_id)
                    try:
                        unchanged = old and old.get('archive_schema_version') == '3' and old.get('archive_state') == 'complete' and old.get('conversation_updated_at') and \
                            datetime.fromisoformat(str(old['conversation_updated_at']).replace('Z','+00:00')).timestamp() == \
                            datetime.fromisoformat(str(conversation.get('updated_time','')).replace('Z','+00:00')).timestamp()
                    except (ValueError, TypeError): unchanged = False
                    if unchanged:
                        unchanged_conversations += 1
                        self.archive.update(conversations=scanned_conversations, messages=saved_messages,
                            detail=f'Scanned {scanned_conversations} conversations; {unchanged_conversations} unchanged, {saved_messages} messages written so far.')
                        continue
                    resume_cursor = old.get('archive_next_cursor') if old and old.get('archive_schema_version') == '3' and old.get('archive_state') == 'syncing' else None
                    conv_record = {'ig_account_id':c['account_id'],'conversation_id':conversation_id,
                        'record_type':'conversation','record_id':conversation_id,
                        'conversation_updated_at':conversation.get('updated_time'),'message_created_at':None,
                        'participants':participants,'payload':{**conversation,'archive_schema_version':3,'archive_sync_state':'syncing',
                            **({'archive_next_cursor':resume_cursor} if resume_cursor else {})}}
                    _saved_result = db.request({'records':[conv_record]})
                    result = _saved_result; saved_conversations += int(result.get('saved', 0))
                    self.archive.update(conversations=saved_conversations, messages=saved_messages,
                        detail=f'Scanned {scanned_conversations} conversations; {unchanged_conversations} unchanged, {saved_messages} messages written so far.')
                    message_cursor = resume_cursor
                    seen_message_cursors = {resume_cursor} if resume_cursor else set()
                    try:
                        while True:
                            edge = message_page(api,conversation_id,message_cursor)
                            records = []
                            for message in edge.get('data', []):
                                message_id = str(message.get('id') or '')
                                if not message_id: continue
                                records.append({'ig_account_id':c['account_id'],'conversation_id':conversation_id,
                                    'record_type':'message','record_id':message_id,
                                    'conversation_updated_at':conversation.get('updated_time'),
                                    'message_created_at':message.get('created_time'),
                                    'participants':participants,'payload':message})
                            if records:
                                _saved_result = db.request({'records':records})
                                result = _saved_result; saved_messages += int(result.get('saved', 0))
                                self.archive.update(conversations=saved_conversations, messages=saved_messages,
                                    detail=f'Scanned {scanned_conversations} conversations; {unchanged_conversations} unchanged, {saved_messages} messages written so far.')
                            paging = edge.get('paging', {})
                            next_cursor = paging.get('cursors', {}).get('after')
                            if not paging.get('next') or not next_cursor or next_cursor in seen_message_cursors: break
                            conv_record['payload'] = {**conversation,'archive_schema_version':3,'archive_sync_state':'syncing','archive_next_cursor':next_cursor}
                            _saved_result = db.request({'records':[conv_record]})
                            _saved_result
                            seen_message_cursors.add(next_cursor); message_cursor = next_cursor
                    except MetaError as e:
                        if '(HTTP 400, code 100)' not in str(e): raise
                        unavailable_conversations += 1
                        conv_record['payload'] = {**conversation,'archive_schema_version':3,'archive_sync_state':'incomplete','archive_sync_error':str(e)}
                        _saved_result = db.request({'records':[conv_record]})
                        _saved_result
                        continue
                    conv_record['payload'] = {**conversation,'archive_schema_version':3,'archive_sync_state':'complete'}
                    _saved_result = db.request({'records':[conv_record]})
                    _saved_result
                paging = page.get('paging', {})
                next_cursor = paging.get('cursors', {}).get('after')
                has_next = bool(paging.get('next') and next_cursor and next_cursor not in seen_conversation_cursors)
                page_last_id = str(conversations[-1].get('id') or '')
                if page_last_id:
                    if conversation_marker_id and conversation_marker_id != page_last_id:
                        _saved_result = db.request({'index_cursor':{'ig_account_id':c['account_id'],
                            'cursor':None,'conversation_id':conversation_marker_id}})
                        _saved_result
                    _saved_result = db.request({'index_cursor':{'ig_account_id':c['account_id'],
                        'cursor':next_cursor if has_next else None,'conversation_id':page_last_id}})
                    _saved_result
                if not has_next: break
                seen_conversation_cursors.add(next_cursor); conversation_cursor = next_cursor; conversation_marker_id = page_last_id
            return saved_conversations, saved_messages, unavailable_conversations, unchanged_conversations
    def start_archive_sync(self):
        with self.archive_lock:
            if self.archive['state'] == 'syncing': return False
            self.archive = {'state':'syncing','detail':'Reading every available conversation and message page, saving as each page arrives.','conversations':0,'messages':0,'updated':None}
        def run():
            try:
                conversations, messages, unavailable, unchanged = self.sync_chat_history()
                detail = f'Scanned the full conversation list; saved or refreshed {conversations} conversation records and {messages} messages. {unchanged} unchanged conversations skipped.'
                if unavailable: detail += f' Meta did not allow message history for {unavailable} conversation(s); marked those for retry.'
                self.archive = {'state':'ready','detail':detail,'conversations':conversations,'messages':messages,'updated':time.time()}
            except Exception as e:
                detail = str(e) if isinstance(e, (MetaError, ValueError, ArchiveError)) else 'Sync stopped. Previously saved pages remain in Neon; check the local connection and retry.'
                self.archive = {**self.archive,'state':'error','detail':detail,'updated':time.time()}
            self.refresh_dashboard()
        self.start_task(run)
        return True
    def poll_comments(self):
        c = dict(self.store.config)
        if not (c['enabled'] and c['verified'] and c['media_id'] and c['access_token']): return
        api = Graph(c); after = None; found = 0; earliest = None
        for _ in range(10):
            query = {'fields':'id,text,timestamp,from,parent_id', 'limit':'100'}
            if after: query['after'] = after
            result = api.call('GET', c['media_id'] + '/comments', **query)
            comments = result.get('data', [])
            if not comments: break
            stamps=[]
            for comment in comments:
                stamp_text = comment.get('timestamp')
                if not comment.get('id') or not stamp_text: continue
                stamp = datetime.fromisoformat(stamp_text.replace('Z', '+00:00')).timestamp()
                stamps.append(stamp); earliest = stamp if earliest is None else min(earliest, stamp)
                if stamp < float(c.get('campaign_started_at') or 0): continue
                value = {**comment, 'media':comment.get('media') or {'id':c['media_id']}}
                self.store.enqueue('comment:' + str(comment['id']), {'kind':'comment', 'value':value}); found += 1
            after = result.get('paging', {}).get('cursors', {}).get('after')
            if not after or not result.get('paging', {}).get('next'): break
            if stamps and min(stamps) < float(c.get('campaign_started_at') or 0): break
        self.poll_status = f'Polled comments; {found} recent item(s) checked.'
    def worker(self):
        while not self.stop.is_set():
            c = self.store.config
            if c['enabled'] and c['verified'] and c.get('workflow_mode')!='manychat' and time.monotonic() >= self.next_poll:
                try: self.poll_comments(); self.next_poll = time.monotonic() + 60
                except Exception as e:
                    self.poll_status = str(e) if isinstance(e, MetaError) else 'Comment poll failed; check token permissions and selected Reel.'
                    self.next_poll = time.monotonic() + 60
            if not self.engine.run_one(): self.stop.wait(1)
    def archive_worker(self):
        next_sync = 0
        while not self.stop.is_set():
            c = self.store.config
            if c['verified'] and c['access_token'] and time.monotonic() >= next_sync:
                self.start_archive_sync()
                next_sync = time.monotonic() + (3600 if backend_name(self.store.env_file)=='neon' else 900)
            self.stop.wait(2 if not c['verified'] else 15)
    def public_config(self):
        return {**{k:v for k,v in self.store.config.items() if k not in ('access_token', 'app_secret')},'flows':flows(self.store.config)}

class Handler(BaseHTTPRequestHandler):
    server_version = 'ReelFollowup/1'
    def log_message(self, *args): pass
    @property
    def app(self):
        if self.server.ingress:return self.server.app
        return self.server.accounts.get(self.headers.get('X-Reel-Account','default')) if hasattr(self.server,'accounts') else self.server.app
    def reply(self, status, data, content='application/json'):
        raw = json.dumps(data).encode() if content == 'application/json' else data if isinstance(data,bytes) else data.encode()
        self.send_response(status); self.send_header('Content-Type', content if content.startswith('image/') else content + '; charset=utf-8')
        self.send_header('Content-Length', str(len(raw))); self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff'); self.send_header('X-Frame-Options', 'DENY')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; frame-ancestors 'none'; form-action 'self'")
        self.end_headers(); self.wfile.write(raw)
    def local(self):
        port = self.server.server_port
        hosts = {f'localhost:{port}', f'127.0.0.1:{port}'}
        hosts.update(host.strip() for host in read_env().get('REEL_DASHBOARD_HOSTS', '').split(',') if host.strip())
        return self.headers.get('Host') in hosts
    def do_GET(self):
        path = urlsplit(self.path)
        if self.server.ingress:
            if path.path != '/webhook': return self.reply(404, {})
            q = parse_qs(path.query); cfg = self.app.store.config
            if q.get('hub.mode') == ['subscribe'] and hmac.compare_digest(q.get('hub.verify_token', [''])[0], cfg['verify_token']):
                return self.reply(200, q.get('hub.challenge', [''])[0], 'text/plain')
            return self.reply(403, {})
        if not self.local(): return self.reply(403, {})
        try:self.app
        except ValueError:return self.reply(404,{'error':'Unknown account workspace.'})
        if path.path == '/api/status':
            rows = self.app.store.execute('SELECT state,detail,created FROM events ORDER BY created DESC LIMIT 30')
            return self.reply(200, {'config':self.app.public_config(), 'nonce':self.app.nonce, 'poll_status':self.app.poll_status,
                'connector_url':read_env(self.app.store.env_file).get('REEL_CONNECTOR_URL',''),
                'archive':self.app.archive,'dashboard':self.app.dashboard,'followup':self.app.followup,'workflow_stats':self.app.engine.workflows.stats(),
                'webhook':self.app.webhook_status,'events':[dict(r) for r in rows],
                'storage':{'backend':backend_name(self.app.store.env_file),'delivery':delivery_mode(self.app.store.env_file)},
                'accounts':self.server.accounts.listing() if hasattr(self.server,'accounts') else [],
                'profile_id':self.headers.get('X-Reel-Account','default')})
        if path.path == '/api/chats':
            try:
                q = parse_qs(path.query)
                return self.reply(200,self.app.chat_overview(page=max(0,int(q.get('page',['0'])[0])),view=q.get('view',['matches'])[0]))
            except Exception: return self.reply(503,{'error':'Could not load chats from Neon. Try again.'})
        if path.path == '/assets/reel-followup.png':
            return self.reply(200,(PROJECT_ROOT/'assets/reel-followup.png').read_bytes(),'image/png')
        files = {'/':('index.html','text/html'), '/app.js':('app.js','application/javascript'), '/style.css':('style.css','text/css')}
        if path.path in files:
            name, kind = files[path.path]; return self.reply(200, (ROOT / name).read_text(), kind)
        return self.reply(404, {})
    def do_POST(self):
        try:
            size = int(self.headers.get('Content-Length', '0'))
            if not 0 < size <= 1024 * 1024: return self.reply(413, {})
            raw = self.rfile.read(size)
            if self.server.ingress:
                if self.path.startswith('/host/'):
                    if not hasattr(self.server,'host_service') or not self.server.host_service.authenticate(self.path,raw,self.headers):return self.reply(403,{'error':'Host authentication denied.'})
                    try:return self.reply(200,self.server.host_service.handle(self.path,json.loads(raw)))
                    except ValueError as error:return self.reply(400,{'error':str(error)})
                    except Exception:return self.reply(400,{'error':'Host could not complete this account request.'})
                if self.path != '/webhook': return self.reply(404, {})
                secret = self.app.store.config['app_secret']
                expected = 'sha256=' + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
                if not secret or not hmac.compare_digest(expected, self.headers.get('X-Hub-Signature-256','')):
                    return self.reply(403, {})
                body = json.loads(raw)
                if body.get('object') != 'instagram': return self.reply(400, {})
                if hasattr(self.server,'accounts'):self.server.accounts.ingest(body)
                else:self.app.store.ingest(body)
                return self.reply(200, {'accepted':True})
            if not self.local() or self.headers.get('Origin') != 'http://' + self.headers.get('Host', '') or not hmac.compare_digest(self.headers.get('X-Local-Token',''),self.app.nonce):
                return self.reply(403, {})
            data = json.loads(raw); c = dict(self.app.store.config)
            if self.path == '/api/accounts/create':
                token=str(data.get('access_token') or '').strip()
                if not token or len(token)>8192 or any(ch in token for ch in '\r\n\x00'):raise ValueError('Paste a valid single-line Instagram access token.')
                if delivery_mode(self.app.store.env_file)=='direct' and not c['app_secret']:raise ValueError('Self-hosting requires your own Meta app secret in the private .env before adding accounts.')
                account=self.server.accounts.create({**data,'access_token':token})
                return self.reply(201,{'message':'Account verified and saved. Its worker starts paused.','profile_id':account})
            if self.path == '/api/config':
                credentials_changed = any(data.get(key) for key in ('app_id','access_token','app_secret','api_version'))
                for key in ('app_id','access_token','app_secret','api_version','keyword'):
                    if data.get(key): c[key] = str(data[key]).strip()
                if 'media_id' in data:
                    c['media_id'] = str(data['media_id']).strip()
                if 'public_webhook_origin' in data:
                    origin = str(data['public_webhook_origin']).strip().rstrip('/')
                    parsed = urlsplit(origin)
                    if origin and (parsed.scheme != 'https' or not parsed.netloc or parsed.path or parsed.query or parsed.fragment):
                        raise ValueError('Enter only the public HTTPS tunnel origin, for example https://example.trycloudflare.com.')
                    c['public_webhook_origin'] = origin
                if not re.fullmatch(r'v\d+\.\d+', c['api_version']): raise ValueError('Use a Graph API version such as v22.0.')
                if c['media_id'] and not c['media_id'].isdigit(): raise ValueError('Select a numeric Instagram media ID, not the Reel shortcode.')
                if c['app_id'] and not c['app_id'].isdigit(): raise ValueError('Meta App ID must contain digits only.')
                if not 1 <= len(c['keyword']) <= 50: raise ValueError('Keyword must contain 1–50 characters.')
                if credentials_changed: c.update(enabled=False,verified=False)
                self.app.store.save(c)
                return self.reply(200, {'message':'Saved privately. Verify the account before enabling.'})
            if self.path == '/api/verify':
                if not c['app_id'] or not c['access_token']: raise ValueError('Enter the dedicated automation app ID and its Instagram access token first.')
                if delivery_mode(self.app.store.env_file)=='direct' and not c['app_secret']:raise ValueError('Self-hosting requires your own Meta app secret in the private .env before verification.')
                profile = Graph(c).call('GET','me',fields='user_id,username')
                account_id, aliases = account_identity(profile, c)
                c.update(account_id=account_id,account_aliases=aliases,username=profile['username'],verified=True,enabled=False)
                self.app.store.save(c); return self.reply(200, {'message':f"Verified @{c['username']}. Select your Reel or configure webhook mode."})
            if self.path == '/api/sync-chats':
                if not c['verified']: raise ValueError('Verify your Instagram account before syncing chat history.')
                started = self.app.start_archive_sync()
                return self.reply(202 if started else 200, {'message':'Full chat sync started.' if started else 'A full chat sync is already running.'})
            if self.path in ('/api/followups/send','/api/followups/retry-rejected'):
                started = self.app.start_followup(retry_rejected=self.path.endswith('retry-rejected'))
                return self.reply(202 if started else 200,{'message':'Follow-up batch started.' if started else 'The batch is already running.'})
            if self.path == '/api/media':
                if not c['verified']: raise ValueError('Verify your Instagram account first.')
                result = Graph(c).call('GET','me/media',fields='id,caption,permalink,media_type',limit='50')
                return self.reply(200, {'media':result.get('data',[])})
            if self.path == '/api/flows/toggle':
                current=flows(c);setting=data.get('setting');value=data.get('value')
                if setting not in ('enabled','followup_enabled') or not isinstance(value,bool):raise ValueError('Invalid pause setting.')
                target=next((f for f in current if f['id']==data.get('id')),None)
                if not target:raise ValueError('This flow no longer exists.')
                if setting=='enabled' and value and not c['verified']:raise ValueError('Verify this account before enabling a flow.')
                target[setting]=value;c['flows']=validate_flows(current)
                self.app.store.save(c)
                return self.reply(200,{'message':('Resumed' if value else 'Paused')+' '+('flow.' if setting=='enabled' else 'follow-ups.')})
            if self.path == '/api/flows':
                checked=validate_flows(data.get('flows'))
                verify_new_selections(self.app,Graph,checked,flows(c))
                if not c['verified'] and any(f['enabled'] for f in checked):raise ValueError('Unverified accounts can save only paused drafts.')
                c['flows']=checked
                placeholders=','.join('?' for f in c['flows'])
                self.app.store.execute("UPDATE workflow_jobs SET state='cancelled',detail='Flow removed.' WHERE state IN ('waiting','waiting_inbound') AND flow_id NOT IN ("+placeholders+")",[f['id'] for f in c['flows']])
                c['workflow_mode']='manychat'
                self.app.store.save(c)
                return self.reply(200,{'message':'Flows saved. Each flow and its follow-ups use their own pause switch.'})
            if self.path == '/api/manychat':
                if not c['verified']: raise ValueError('Verify your Instagram account first.')
                keyword=str(data.get('keyword') or c['keyword']).strip()
                if not 1<=len(keyword)<=50: raise ValueError('Enter a keyword between 1 and 50 characters.')
                profile=Graph(c).call('GET','me',fields='user_id,username')
                _, aliases = account_identity(profile, c)
                if c.get('workflow_mode')!='manychat':c['enabled']=False
                c.update(workflow_mode='manychat',keyword=keyword,account_aliases=aliases,username=profile['username'])
                if data.get('enabled') is True:
                    if hasattr(self.server,'host_service') and self.server.host_service.reserved(c):raise ValueError('This account is reserved on another installation; migrate it before activation.')
                    challenge = secrets.token_hex(16)
                    parsed = urlsplit(self.app.webhook_url)
                    if parsed.scheme != 'https' or not parsed.netloc or parsed.query or parsed.fragment:
                        raise ValueError('Configure REEL_WEBHOOK_URL with your public HTTPS callback URL.')
                    verification_url = self.app.webhook_url + '?' + urlencode({'hub.mode':'subscribe','hub.verify_token':c['verify_token'],'hub.challenge':challenge})
                    try:
                        with urlopen(verification_url, timeout=15) as response:
                            verified = response.read(1025).decode() == challenge
                    except Exception: verified = False
                    if not verified: raise ValueError('The callback did not verify. Match the verification token and finish Meta webhook setup.')
                    c['webhook_verified'] = True
                    c.update(enabled=True,campaign_started_at=time.time())
                elif data.get('enabled') is False: c['enabled']=False
                self.app.store.save(c)
                return self.reply(200,{'message':'Webhook service enabled for all your Reels.' if c['enabled'] else 'Webhook service saved; reply sending is paused.'})
            if self.path == '/api/enable':
                enable = data.get('enabled') is True
                if enable:
                    if hasattr(self.server,'host_service') and self.server.host_service.reserved(c):raise ValueError('This account is reserved on another installation; migrate it before activation.')
                    if not c['verified'] or not c['media_id']: raise ValueError('Verify your account and select a Reel first.')
                    media = Graph(c).call('GET',c['media_id'],fields='id,owner')
                    owner = media.get('owner',{}); owner = owner.get('id') if isinstance(owner,dict) else owner
                    if str(owner) != c['account_id']: raise ValueError('Could not confirm that the connected account owns this Reel.')
                    c['campaign_started_at'] = time.time()
                    c['workflow_mode']='poll'
                c['enabled'] = enable; self.app.store.save(c)
                return self.reply(200, {'message':'Automation enabled.' if enable else 'Automation paused.'})
            return self.reply(404,{})
        except (ValueError, KeyError, MetaError) as e:
            return self.reply(400, {'error':str(e) if isinstance(e,(ValueError,MetaError)) else 'Unexpected API response. Check your Meta setup.'})
        except Exception:
            return self.reply(500, {'error':'Request failed. Settings and events have been preserved.'})

def serve():
    os.umask(0o077)
    try:
        from .accounts import AccountRegistry
    except ImportError:
        from accounts import AccountRegistry
    registry=AccountRegistry(PROJECT_ROOT,App,Graph,DEFAULTS)
    try:
        from .host_service import HostService
    except ImportError:
        from host_service import HostService
    host_service=HostService(registry)
    app=registry.get('default');servers=[]
    for port,ingress in ((3130,False),(3131,True)):
        server=ThreadingHTTPServer(('127.0.0.1',port),Handler)
        server.app,server.ingress,server.accounts=app,ingress,registry;server.host_service=host_service;servers.append(server)
    registry.start()
    threading.Thread(target=servers[1].serve_forever,daemon=True).start()
    print('Dashboard http://localhost:3130 — account workers run in Python',flush=True)
    try:servers[0].serve_forever()
    finally:
        registry.stop()
        for server in servers:server.server_close()

if __name__ == '__main__':serve()
