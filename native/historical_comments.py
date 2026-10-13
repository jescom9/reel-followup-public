"""Reviewed, paced launches for earlier comments without bypassing DM windows."""
import hashlib,json,re,secrets,time
from datetime import datetime
try:
    from .storage import StorageBridge,backend_name
except ImportError:
    from storage import StorageBridge,backend_name

DAY=86400

def timestamp(value):
    try:return datetime.fromisoformat(str(value).replace('Z','+00:00')).timestamp()
    except (ValueError,TypeError):return 0

def fingerprint(flow):
    fields=('id','keywords','media_scope','media_ids','link_url','require_follow','link_button','opening_text','follow_text','link_text','button_text','public_reply_text')
    return hashlib.sha256(json.dumps({k:flow.get(k) for k in fields},sort_keys=True).encode()).hexdigest()

def matches(flow,text):
    return any(re.search(r'(?<!\w)'+re.escape(word)+r'(?!\w)',text or '',re.I) for word in flow['keywords'])

class HistoricalComments:
    def __init__(self,store,factory,workflows,clock=time.time,recover=False):
        self.s,self.factory,self.workflows,self.clock=store,factory,workflows,clock
        store.execute('''CREATE TABLE IF NOT EXISTS historical_runs (
            id TEXT PRIMARY KEY,account_id TEXT NOT NULL,flow_id TEXT NOT NULL,contract TEXT NOT NULL,
            old_text TEXT NOT NULL,state TEXT NOT NULL,next_at REAL NOT NULL,interval_seconds REAL NOT NULL,
            created_at REAL NOT NULL,detail TEXT NOT NULL DEFAULT '',excluded INTEGER NOT NULL DEFAULT 0)''')
        store.execute('''CREATE TABLE IF NOT EXISTS historical_jobs (
            run_id TEXT NOT NULL,comment_id TEXT NOT NULL,media_id TEXT NOT NULL,sender_id TEXT NOT NULL,
            payload TEXT NOT NULL,created_at REAL NOT NULL,state TEXT NOT NULL DEFAULT 'pending',
            dm_accepted INTEGER NOT NULL DEFAULT 0,public_accepted INTEGER NOT NULL DEFAULT 0,
            detail TEXT NOT NULL DEFAULT '',PRIMARY KEY(run_id,comment_id))''')
        if recover:
            store.execute("UPDATE historical_runs SET state='paused',detail='Interrupted send requires review.' WHERE id IN (SELECT run_id FROM historical_jobs WHERE state='processing')")
            store.execute("UPDATE historical_jobs SET state='review',detail='Interrupted send; inspect delivery before retrying.' WHERE state='processing'")
    def _paged(self,api,path,fields,max_rows=2000):
        rows=[];after=None;seen=set()
        while True:
            result=api.call('GET',path,fields=fields,limit=100,**({'after':after} if after else {}))
            rows.extend(result.get('data',[]))
            if len(rows)>max_rows:raise ValueError('Too many comments for one launch. Select fewer Reels and preview again.')
            paging=result.get('paging') or {}
            if not paging.get('next'):return rows
            after=(paging.get('cursors') or {}).get('after')
            if not after or after in seen:raise ValueError('Instagram pagination could not be completed. Try preview again.')
            seen.add(after)
    def preview(self,config,flow,old_text,excluded_authors=(),excluded_ids=()):
        if backend_name(self.s.env_file)!='sqlite':raise ValueError('Earlier-comment launches are unavailable for this account. Contact support.')
        if not config.get('verified') or not config.get('access_token'):raise ValueError('Reconnect Instagram before previewing comments.')
        if not isinstance(old_text,str) or not old_text.strip() or len(old_text.encode('utf-16-le'))//2>300:raise ValueError('Enter an older-comment reply with up to 300 characters.')
        with StorageBridge(self.s.env_file,self.s.folder):pass
        api=self.factory(dict(config));now=self.clock();account=str(config['account_id'])
        media=self._paged(api,account+'/media','id,media_product_type',500)
        selected=set(flow.get('media_ids',[]));old_records=[];excluded=0
        owners={account,*map(str,config.get('account_aliases',[])),*map(str,excluded_ids)}
        names={str(n).casefold() for n in [config.get('username',''),*excluded_authors] if n}
        done=self.s.execute("""SELECT j.comment_id,j.sender_id FROM historical_jobs j JOIN historical_runs r ON r.id=j.run_id
            WHERE r.account_id=? AND r.flow_id=? AND r.state!='draft' AND j.state IN ('sent','review','rejected','processing')""",(account,flow['id']))
        notified_comments={r['comment_id'] for r in done};notified_senders={r['sender_id'] for r in done}
        for reel in media:
            mid=str(reel.get('id') or '')
            if reel.get('media_product_type')!='REELS' or (flow.get('media_scope','all')=='selected' and mid not in selected):continue
            comments=self._paged(api,mid+'/comments','id,text,timestamp,from,hidden')
            for comment in comments:
                cid=str(comment.get('id') or '');author=comment.get('from') or {};sid=str(author.get('id') or '');created=timestamp(comment.get('timestamp'))
                if not matches(flow,comment.get('text')):continue
                if not re.fullmatch(r'\d+',cid) or not sid or sid in owners or str(author.get('username') or '').casefold() in names or comment.get('hidden') or not 0<created<=now or cid in notified_comments or sid in notified_senders:
                    excluded+=1;continue
                old_records.append({'id':cid,'text':comment.get('text') or '', 'timestamp':comment['timestamp'],'from':author,'media':{'id':mid}})
        # One launch notice per person, using their newest matching comment.
        rows=[];seen=set()
        for comment in sorted(old_records,key=lambda row:timestamp(row['timestamp']),reverse=True):
            sid=str(comment['from']['id'])
            if sid in seen:excluded+=1;continue
            seen.add(sid);rows.append(comment)
        identifier='earlier-'+secrets.token_hex(8)
        with self.s.lock,self.s.db:
            self.s.db.execute('INSERT INTO historical_runs VALUES(?,?,?,?,?,?,?,?,?,?,?)',(identifier,account,flow['id'],fingerprint(flow),old_text.strip(),'draft',0,60,now,'Preview only; no messages sent.',excluded))
            for comment in rows:
                self.s.db.execute('INSERT INTO historical_jobs(run_id,comment_id,media_id,sender_id,payload,created_at) VALUES(?,?,?,?,?,?)',(identifier,comment['id'],comment['media']['id'],str(comment['from']['id']),json.dumps(comment),timestamp(comment['timestamp'])))
        return self.status(config,identifier)[0]
    def status(self,config,identifier=None):
        query='SELECT * FROM historical_runs WHERE account_id=?';args=[str(config['account_id'])]
        if identifier:query+=' AND id=?';args.append(identifier)
        query+=' ORDER BY created_at DESC LIMIT 30';result=[];now=self.clock()
        for raw in self.s.execute(query,args):
            run=dict(raw);counts={r['state']:r['n'] for r in self.s.execute('SELECT state,count(*) n FROM historical_jobs WHERE run_id=? GROUP BY state',(run['id'],))}
            totals=self.s.execute('SELECT coalesce(sum(dm_accepted),0) dm,coalesce(sum(public_accepted),0) public FROM historical_jobs WHERE run_id=?',(run['id'],))[0]
            recent=self.s.execute("SELECT count(*) n FROM historical_jobs WHERE run_id=? AND created_at>? AND state='pending'",(run['id'],now-7*DAY))[0]['n']
            visible={k:run[k] for k in ('id','flow_id','state','next_at','interval_seconds','created_at','detail','excluded','old_text')}
            visible.update(counts=counts,total=sum(counts.values()),dm_accepted=totals['dm'],public_accepted=totals['public'],private_eligible=recent,older_pending=counts.get('pending',0)-recent,
                estimate_seconds=max(0,run['next_at']-now)+max(0,counts.get('pending',0)-1)*run['interval_seconds'] if run['state']=='running' and config['enabled'] else None)
            result.append(visible)
        return result
    def control(self,config,identifier,action,flow):
        if action not in ('start','pause'):raise ValueError('Choose start or pause.')
        rows=self.s.execute('SELECT * FROM historical_runs WHERE id=? AND account_id=?',(identifier,str(config['account_id'])))
        if not rows:raise ValueError('Earlier-comment run does not exist in this account.')
        run=rows[0]
        if action=='start':
            if run['contract']!=fingerprint(flow):raise ValueError('Save the final flow settings and create a new preview before launching.')
            if not config['enabled'] or not flow['enabled']:raise ValueError('Activate this account and flow before launching earlier comments.')
            if self.s.execute("SELECT 1 FROM historical_jobs WHERE run_id=? AND state IN ('processing','review','rejected') LIMIT 1",(identifier,)):raise ValueError('Inspect unresolved sends before restarting this launch.')
            if self.s.execute("SELECT 1 FROM historical_runs r WHERE r.account_id=? AND r.flow_id=? AND r.id!=? AND r.state IN ('running','paused') AND EXISTS(SELECT 1 FROM historical_jobs j WHERE j.run_id=r.id AND j.state='pending') LIMIT 1",(str(config['account_id']),flow['id'],identifier)):raise ValueError('Another earlier-comment run for this flow is still pending.')
        self.s.execute('UPDATE historical_runs SET state=?,detail=? WHERE id=?',('running' if action=='start' else 'paused','' if action=='start' else 'Paused by account owner.',identifier))
        return self.status(config,identifier)[0]
    def _pause(self,run,detail):self.s.execute("UPDATE historical_runs SET state='paused',detail=? WHERE id=?",(detail,run['id']))
    def run_one(self,config):
        if not config.get('enabled') or not config.get('verified'):return False
        now=self.clock();runs=self.s.execute("SELECT * FROM historical_runs WHERE account_id=? AND state='running' AND next_at<=? ORDER BY created_at LIMIT 1",(str(config['account_id']),now))
        if not runs:return False
        run=runs[0]
        try:
            from .workflows import flows
        except ImportError:
            from workflows import flows
        flow=next((f for f in flows(config) if f['id']==run['flow_id']),None)
        if not flow or run['contract']!=fingerprint(flow):self._pause(run,'Flow changed. Review and create a new preview.');return True
        if not flow['enabled']:return False
        jobs=self.s.execute("SELECT * FROM historical_jobs WHERE run_id=? AND state='pending' ORDER BY created_at DESC LIMIT 1",(run['id'],))
        if not jobs:self.s.execute("UPDATE historical_runs SET state='complete',detail='All earlier comments processed.' WHERE id=?",(run['id'],));return True
        job=jobs[0];api=self.factory(dict(config));own={str(config['account_id']),*map(str,config.get('account_aliases',[]))}
        try:
            media=api.call('GET',job['media_id'],fields='id,owner,media_product_type')
            comment=api.call('GET',job['comment_id'],fields='id,text,timestamp,media,from,hidden')
            if str((media.get('owner') or {}).get('id')) not in own or media.get('media_product_type')!='REELS' or str(comment.get('id'))!=job['comment_id'] or str((comment.get('media') or {}).get('id'))!=job['media_id'] or str((comment.get('from') or {}).get('id'))!=job['sender_id']:
                self._pause(run,'Comment or media ownership changed; nothing sent.');return True
            if comment.get('hidden') or not matches(flow,comment.get('text')):
                self.s.execute("UPDATE historical_jobs SET state='skipped',detail='Comment hidden or keyword no longer matches.' WHERE run_id=? AND comment_id=?",(run['id'],job['comment_id']));return True
            created=timestamp(comment.get('timestamp'))
            if not 0<created<=now:self._pause(run,'Comment timestamp could not be verified.');return True
            recent=now-created<7*DAY;reply=flow['public_reply_text'] if recent else run['old_text']
            replies=self._paged(api,job['comment_id']+'/replies','id,text',1000)
            if any(re.sub(r'^@\S+\s+','',str(r.get('text') or '')).strip() in (flow['public_reply_text'].strip(),run['old_text'].strip()) for r in replies):
                self.s.execute("UPDATE historical_jobs SET state='skipped',detail='Launch reply already exists.' WHERE run_id=? AND comment_id=?",(run['id'],job['comment_id']));return True
        except Exception:
            self._pause(run,'Instagram read failed; no reply attempted. Refresh and review before retrying.');return True
        if not self.s.config.get('enabled'):return False
        try:
            from .plans import admit
        except ImportError:
            from plans import admit
        if not admit(self.s,job['sender_id']):
            self._pause(run,'Contact limit reached. Upgrade from Plans, then resume this launch.');return True
        claimed=self.s.execute("UPDATE historical_jobs SET state='processing' WHERE run_id=? AND comment_id=? AND state='pending' AND EXISTS (SELECT 1 FROM historical_runs WHERE id=? AND state='running') RETURNING comment_id",(run['id'],job['comment_id'],run['id']))
        if not claimed:return False
        self.s.execute('UPDATE historical_runs SET next_at=? WHERE id=?',(now+run['interval_seconds'],run['id']))
        try:
            if recent:
                canonical=('mc-opening:v1:' if flow['id']=='legacy' else 'rf-opening:'+flow['id']+':')+job['media_id']+':'+job['sender_id']
                previous=self.s.execute('SELECT state,receipt FROM local_flow_actions WHERE account_id=? AND action_id=?',(str(config['account_id']),canonical))
                if previous:
                    if previous[0]['state']!='sent':raise ValueError('Previous opening requires review.')
                    receipt=json.loads(previous[0]['receipt'])
                else:
                    def send_opening():
                        recipient={'comment_id':job['comment_id']}
                        if flow['require_follow']:return api.send_button(recipient,flow['opening_text'],'Following','RF_FOLLOW:'+flow['id'])
                        if flow['link_button']:return api.send_link(recipient,flow['link_text'],flow['button_text'],flow['link_url'])
                        return api.send(recipient,flow['link_text']+' '+flow['link_url'])
                    receipt=self.s.flow_once('historical-opening:'+flow['id']+':'+job['comment_id'],lambda:self.workflows.record_opening(send_opening))
                    self.s.flow_once(canonical,lambda:receipt)
                recipient=str(receipt.get('recipient_id') or job['sender_id'])
                self.workflows.put(flow['id'],recipient,opened=True,link_sent=not flow['require_follow'])
                if not flow['require_follow']:self.workflows.schedule(flow,recipient,'followup','historical:'+job['comment_id'],0)
                self.s.execute('UPDATE historical_jobs SET dm_accepted=1 WHERE run_id=? AND comment_id=?',(run['id'],job['comment_id']))
            # For old comments this is a public invitation to comment again; no DM is claimed.
            self.s.flow_once('historical-public:'+flow['id']+':'+job['comment_id'],lambda:api.call('POST',job['comment_id']+'/replies',{'message':reply}))
            self.s.execute("UPDATE historical_jobs SET state='sent',public_accepted=1,detail=? WHERE run_id=? AND comment_id=?",('Opening and launch reply accepted.' if recent else 'Older-comment launch reply accepted; new comment needed for DM.',run['id'],job['comment_id']))
        except Exception as error:
            state='rejected' if getattr(error,'code',None) is not None else 'review'
            self.s.execute('UPDATE historical_jobs SET state=?,detail=? WHERE run_id=? AND comment_id=?',(state,'Send not confirmed; inspect before retrying.',run['id'],job['comment_id']))
            self._pause(run,'Instagram send stopped; '+str(error)[:180]+' Review before retrying.')
        return True
