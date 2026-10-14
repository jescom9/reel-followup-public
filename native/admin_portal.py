"""Audited support inspection for explicitly configured Instagram administrators."""
import json,re,time
try:
    from .profiles import read_values
    from .workflows import flows
    from .storage import StorageBridge,backend_name
    from . import hosted_metrics,hosted_activity,hosted_history
except ImportError:
    from profiles import read_values
    from workflows import flows
    from storage import StorageBridge,backend_name
    import hosted_metrics,hosted_activity,hosted_history

OPERATIONS={'admin.overview','admin.inspect','admin.events','admin.activity','admin.archive.list','admin.archive.conversation','admin.audit','admin.resources'}


class AdminPortal:
    def __init__(self,registry,clock=time.time):self.registry,self.clock=registry,clock
    def allowed(self,config):
        ids={part.strip() for part in read_values(self.registry.project/'.env').get('REEL_ADMIN_ACCOUNT_IDS','').split(',') if re.fullmatch(r'\d{1,32}',part.strip())}
        return bool(config.get('verified') and str(config.get('account_id')) in ids)
    def table(self,store,name):return bool(store.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?",(name,)))
    def states(self,store,table,scoped=False):
        if not self.table(store,table):return {}
        where=' WHERE account_id=?' if scoped else ''
        args=(store.config['account_id'],) if scoped else ()
        return {row['state']:row['n'] for row in store.execute('SELECT state,count(*) n FROM '+table+where+' GROUP BY state',args)}
    def counts(self,store):
        events=self.states(store,'events');jobs=self.states(store,'workflow_jobs');reminders=self.states(store,'comment_reminders')
        actions=self.states(store,'actions');local=self.states(store,'local_flow_actions',True)
        return {'events':events,'jobs':jobs,'reminders':reminders,'actions':actions,'flow_actions':local,
            'events_review':events.get('review',0),
            'jobs_review':sum(states.get(key,0) for states in (jobs,reminders) for key in ('review','blocked','rejected')),
            'actions_review':sum(states.get(key,0) for states in (actions,local) for key in ('review','attempting','rejected')),
            'pending_events':events.get('pending',0)+events.get('processing',0)}
    def plan(self,store):
        saved=store.config.get('managed_plan') or {};pro=saved.get('name')=='pro' and saved.get('valid_until',0)>self.clock()
        used=store.execute('SELECT count(*) n FROM plan_contacts')[0]['n'] if self.table(store,'plan_contacts') else 0
        return {'name':'pro' if pro else 'free','used':used,'limit':5000 if pro else 50,
            'valid_until':saved.get('valid_until',0),'trial_end':saved.get('trial_end',0),'source':saved.get('source','free'),'has_subscription':bool(saved.get('subscription_id'))}
    def scrub(self,value,config):
        if isinstance(value,dict):return {k:self.scrub(v,config) for k,v in value.items() if k not in ('access_token','app_secret','verify_token','password','receipt','customer_id','subscription_id')}
        if isinstance(value,list):return [self.scrub(v,config) for v in value]
        if not isinstance(value,str):return value
        for secret in (config.get('access_token'),config.get('app_secret'),config.get('verify_token')):
            if secret:value=value.replace(str(secret),'[redacted]')
        return re.sub(r'(?i)((?:access_token|app_secret|password|token|api_key|secret)=)[^\s&#]+',r'\1[redacted]',value)
    def snapshot(self,app):
        c=dict(app.store.config);items=flows(c);counts=self.counts(app.store)
        metrics=hosted_metrics.summary(app.store,items,include_legacy=self.table(app.store,'local_flow_contacts'))
        return {'account_id':str(c['account_id']),'username':c['username'],'enabled':bool(c.get('enabled')),'verified':bool(c.get('verified')),
            'plan':self.plan(app.store),'flow_count':len(items),'active_flows':sum(f['enabled'] for f in items),'metrics':metrics,'failures':counts,
            'credentials':{'stored':bool(c.get('access_token')),'expires_at':c.get('token_expires_at',0)}}
    def audit(self,actor,operation,target):
        actor.store.execute('''CREATE TABLE IF NOT EXISTS admin_audit (
            id INTEGER PRIMARY KEY AUTOINCREMENT,actor_id TEXT NOT NULL,operation TEXT NOT NULL,
            target_id TEXT NOT NULL,created REAL NOT NULL)''')
        actor.store.execute('DELETE FROM admin_audit WHERE created<?',(self.clock()-90*86400,))
        actor.store.execute('INSERT INTO admin_audit(actor_id,operation,target_id,created) VALUES(?,?,?,?)',(str(actor.store.config['account_id']),operation,target,self.clock()))
    def events(self,store,data):
        page=hosted_history.page_number(data.get('page',0));state=data.get('state','review')
        if state not in ('all','review','pending','processing','done'):raise ValueError('Invalid event state.')
        where='' if state=='all' else ' WHERE state=?';args=[] if state=='all' else [state]
        total=store.execute('SELECT count(*) n FROM events'+where,args)[0]['n'];rows=[]
        for row in store.execute('SELECT id,state,detail,created,payload FROM events'+where+' ORDER BY created DESC,id DESC LIMIT 30 OFFSET ?',[*args,page*30]):
            try:event=json.loads(row['payload'])
            except (TypeError,ValueError):event={}
            value=event.get('value') or {};text=(value.get('message') or {}).get('text') or value.get('text') or (value.get('postback') or {}).get('title') or ''
            rows.append({'id':row['id'],'state':row['state'],'detail':row['detail'],'created':row['created'],'kind':event.get('kind','unknown'),
                'sender_id':str((value.get('sender') or value.get('from') or {}).get('id') or ''),'preview':str(text)[:240]})
        return {'rows':rows,'total':total,'page':page}
    def handle(self,actor,operation,data):
        if not self.allowed(actor.store.config):raise ValueError('Administrator access is required.')
        if operation not in OPERATIONS or not isinstance(data,dict):raise ValueError('Unsupported administrator operation.')
        target_id=str(data.get('target_account_id') or '')
        if operation not in ('admin.overview','admin.audit','admin.resources') and not re.fullmatch(r'\d{1,32}',target_id):raise ValueError('Choose a connected account to inspect.')
        self.audit(actor,operation,target_id)
        if operation=='admin.resources':return self.registry.resources.report()
        if operation=='admin.audit':
            page=hosted_history.page_number(data.get('page',0));rows=actor.store.execute('SELECT actor_id,operation,target_id,created FROM admin_audit ORDER BY id DESC LIMIT 30 OFFSET ?',(page*30,))
            return {'rows':[dict(row) for row in rows],'page':page}
        if operation=='admin.overview':
            rows=[]
            for identity in self.registry.listing():
                if not identity['verified']:continue
                found=self.registry.find_account(identity['account_id'])
                if not found:continue
                _,app=found
                with app.lifecycle:
                    if app.stop.is_set():continue
                    try:row=self.snapshot(app)
                    except Exception:row={'account_id':identity['account_id'],'username':identity['username'],'available':False,'error':'Workspace inspection unavailable.'}
                    rows.append(row)
            ready=[r for r in rows if r.get('available',True)]
            totals={'accounts':len(rows),'active_accounts':sum(r['enabled'] for r in ready),'contacts':sum(r['plan']['used'] for r in ready),
                'active_flows':sum(r['active_flows'] for r in ready),'events_review':sum(r['failures']['events_review'] for r in ready),
                'jobs_review':sum(r['failures']['jobs_review'] for r in ready),'actions_review':sum(r['failures']['actions_review'] for r in ready),
                'pending_events':sum(r['failures']['pending_events'] for r in ready),'unavailable_accounts':len(rows)-len(ready)}
            return {'accounts':rows,'totals':totals,'server_time':self.clock()}
        found=self.registry.find_account(target_id)
        if not found:raise ValueError('This account is no longer connected.')
        _,app=found
        with app.lifecycle:
            if self.registry.find_account(target_id)!=found or app.stop.is_set():raise ValueError('This workspace is unavailable.')
            c=dict(app.store.config)
            if backend_name(app.store.env_file)=='sqlite':
                with StorageBridge(app.store.env_file,app.store.folder):pass
            if operation=='admin.inspect':
                result={**self.snapshot(app),'flows':flows(c),'history':hosted_history.summary(app.store)}
            elif operation=='admin.events':result=self.events(app.store,data)
            elif operation=='admin.activity':
                result=hosted_activity.list_activity(app.store,flows(c),data,local_history=self.table(app.store,'archive_records'))
                result['historical_runs']=app.engine.historical.status(c)
            elif operation=='admin.archive.list':result=hosted_history.chats(app.store,data)
            else:result=hosted_history.conversation(app.store,data)
            return self.scrub(result,c)
