"""Durable, paced public replies on media owned by the selected account."""
import json
import re
import time


class PublicReplies:
    def __init__(self, store, factory=None, clock=time.time, recover=False):
        self.s, self.factory, self.clock = store, factory, clock
        store.execute('''CREATE TABLE IF NOT EXISTS public_reply_batches (
            id TEXT PRIMARY KEY, account_id TEXT NOT NULL, media_id TEXT NOT NULL,
            keyword TEXT NOT NULL, message TEXT NOT NULL, state TEXT NOT NULL,
            next_at REAL NOT NULL, interval_seconds REAL NOT NULL, detail TEXT NOT NULL, dedupe_texts TEXT NOT NULL)''')
        store.execute('''CREATE TABLE IF NOT EXISTS public_reply_jobs (
            batch_id TEXT NOT NULL, comment_id TEXT NOT NULL, state TEXT NOT NULL,
            receipt TEXT NOT NULL DEFAULT '{}', detail TEXT NOT NULL DEFAULT '',
            PRIMARY KEY(batch_id,comment_id))''')
        if recover:
            store.execute("UPDATE public_reply_batches SET state='paused',detail='Interrupted send requires review.' WHERE id IN (SELECT batch_id FROM public_reply_jobs WHERE state='sending')")
            store.execute("UPDATE public_reply_jobs SET state='review',detail='Interrupted send; inspect Instagram before retrying.' WHERE state='sending'")

    def create(self, identifier, media_id, keyword, message, targets, skip=(), interval=30, dedupe_texts=()):
        if not identifier or not str(media_id).isdigit() or not keyword.strip() or not message.strip():
            raise ValueError('Batch ID, media ID, keyword and message are required.')
        if interval < 30:
            raise ValueError('Public reply batches require at least 30 seconds between replies.')
        account = str(self.s.config['account_id'])
        if not account or not self.s.config.get('verified'):
            raise ValueError('Verify the sender before creating a batch.')
        existing = self.s.execute('SELECT * FROM public_reply_batches WHERE id=?', (identifier,))
        contract = (account, str(media_id), keyword, message)
        if existing and tuple(existing[0][key] for key in ('account_id','media_id','keyword','message')) != contract:
            raise ValueError('Existing batch sender, media, keyword or message differs.')
        if existing:
            return self.status(identifier)
        skip = set(map(str, skip))
        pattern = re.compile(r'(?<!\w)' + re.escape(keyword) + r'(?!\w)', re.I)
        # The paused batch cannot send until all targets are committed and explicitly resumed.
        with self.s.lock, self.s.db:
            self.s.db.execute('INSERT INTO public_reply_batches VALUES (?,?,?,?,?,?,?,?,?,?)',
                       (identifier, *contract, 'paused', 0, interval, 'Ready for explicit resume.', json.dumps(list(dedupe_texts))))
            for target in targets:
                cid = str(target['id'])
                if not cid.isdigit() or not pattern.search(target.get('text','')):
                    continue
                self.s.db.execute('INSERT OR IGNORE INTO public_reply_jobs(batch_id,comment_id,state,detail) VALUES (?,?,?,?)',
                           (identifier, cid, 'skipped' if cid in skip else 'pending', 'Previously replied.' if cid in skip else ''))
        return self.status(identifier)

    def status(self, identifier=None):
        batches = self.s.execute('SELECT * FROM public_reply_batches' + (' WHERE id=?' if identifier else ''), (identifier,) if identifier else ())
        return [{**dict(batch), 'counts': {r['state']: r['n'] for r in self.s.execute('SELECT state,count(*) AS n FROM public_reply_jobs WHERE batch_id=? GROUP BY state',(batch['id'],))}} for batch in batches]

    def control(self, identifier, action):
        if action not in ('resume','pause'):
            raise ValueError('Choose resume or pause.')
        if action == 'resume' and self.s.execute("SELECT 1 FROM public_reply_jobs WHERE batch_id=? AND state IN ('sending','review','rejected') LIMIT 1",(identifier,)):
            raise ValueError('Inspect unresolved sends before resuming this batch.')
        self.s.execute('UPDATE public_reply_batches SET state=?,detail=? WHERE id=?',('running' if action=='resume' else 'paused','',identifier))
        return self.status(identifier)

    def pause(self, identifier, detail):
        self.s.execute("UPDATE public_reply_batches SET state='paused',detail=? WHERE id=?",(detail,identifier))

    def run_one(self, config):
        now = self.clock()
        if not config.get('enabled') or not config.get('verified'):
            return False
        batches = self.s.execute("SELECT * FROM public_reply_batches WHERE state='running' AND next_at<=? ORDER BY next_at LIMIT 1",(now,))
        if not batches:
            return False
        batch = batches[0]; identifier = batch['id']
        if str(config['account_id']) != batch['account_id']:
            self.pause(identifier,'Sender identity changed; no fallback used.'); return True
        jobs = self.s.execute("SELECT * FROM public_reply_jobs WHERE batch_id=? AND state='pending' ORDER BY rowid LIMIT 1",(identifier,))
        if not jobs:
            self.s.execute("UPDATE public_reply_batches SET state='complete',detail='All targets processed.' WHERE id=?",(identifier,)); return True
        job = jobs[0]; cid = job['comment_id']; api = self.factory(config)
        self.s.execute('UPDATE public_reply_batches SET next_at=? WHERE id=?',(now+batch['interval_seconds'],identifier))
        try:
            media = api.call('GET',batch['media_id'],fields='id,owner')
            owner = media.get('owner',{}); owner = owner.get('id') if isinstance(owner,dict) else owner
            if str(owner) not in {str(config['account_id']), *map(str,config.get('account_aliases',[]))}:
                self.pause(identifier,'Sender does not own this media.'); return True
            comment = api.call('GET',cid,fields='id,text,media')
            actual_media = comment.get('media',{}); actual_media = actual_media.get('id') if isinstance(actual_media,dict) else actual_media
            if str(comment.get('id')) != cid or str(actual_media) != batch['media_id']:
                self.pause(identifier,'Comment identity or media differs from the approved target.'); return True
            if not re.search(r'(?<!\w)' + re.escape(batch['keyword']) + r'(?!\w)',comment.get('text',''),re.I):
                self.s.execute("UPDATE public_reply_jobs SET state='skipped',detail='Keyword no longer matches.' WHERE batch_id=? AND comment_id=?",(identifier,cid)); return True
            approved = {batch['message'], *json.loads(batch['dedupe_texts'])}
            after = None; seen = set()
            while True:
                page = api.call('GET',cid+'/replies',fields='id,text',limit=100,**({'after':after} if after else {}))
                if any(re.sub(r'^@\S+\s+', '', r.get('text','')).strip() in approved for r in page.get('data',[])):
                    self.s.execute("UPDATE public_reply_jobs SET state='skipped',detail='Approved reply already exists.' WHERE batch_id=? AND comment_id=?",(identifier,cid)); return True
                paging = page.get('paging',{})
                if not paging.get('next'): break
                after = paging.get('cursors',{}).get('after')
                if not after or after in seen: raise ValueError('Reply pagination could not be verified.')
                seen.add(after)
        except Exception as error:
            self.pause(identifier,'Instagram read failed; no reply attempted. ' + str(error)); return True
        claimed = self.s.execute("UPDATE public_reply_jobs SET state='sending' WHERE batch_id=? AND comment_id=? AND state='pending' AND EXISTS (SELECT 1 FROM public_reply_batches WHERE id=? AND state='running') RETURNING comment_id",(identifier,cid,identifier))
        if not claimed:
            return False
        self.s.execute('UPDATE public_reply_batches SET next_at=? WHERE id=?',(self.clock()+batch['interval_seconds'],identifier))
        try:
            receipt = api.call('POST',cid+'/replies',{'message':batch['message']})
            if not receipt.get('id'):
                raise ValueError('No reply receipt returned.')
            self.s.execute("UPDATE public_reply_jobs SET state='sent',receipt=?,detail='' WHERE batch_id=? AND comment_id=?",(json.dumps(receipt),identifier,cid))
        except Exception as error:
            state = 'rejected' if getattr(error,'code',None) is not None else 'review'
            self.s.execute('UPDATE public_reply_jobs SET state=?,detail=? WHERE batch_id=? AND comment_id=?',(state,str(error),identifier,cid))
            self.pause(identifier,'Instagram send stopped: ' + str(error))
        return True
