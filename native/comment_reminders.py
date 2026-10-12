"""One public reminder per accepted opening, cancelled after any interaction."""
from datetime import datetime
import time

DEFAULT_TEXT='Hey, this is the official account. Check your DMs or find our link in the bio.'

class CommentReminders:
    def __init__(self,store,factory,resolver,clock=time.time):
        self.store,self.factory,self.resolver,self.clock=store,factory,resolver,clock
        store.execute('''CREATE TABLE IF NOT EXISTS comment_reminders (
            opening_key TEXT PRIMARY KEY,flow_id TEXT NOT NULL,comment_id TEXT NOT NULL,
            media_id TEXT NOT NULL,recipient_id TEXT NOT NULL,opened_at REAL NOT NULL,next_at REAL NOT NULL,
            state TEXT NOT NULL DEFAULT 'waiting',detail TEXT NOT NULL DEFAULT '')''')
    def schedule(self,flow,key,value,recipient,receipt):
        opened=receipt.get('_reel_opened_at')
        # Old receipts without an acceptance timestamp are not retroactively notified.
        if not flow.get('comment_reminder_enabled') or not opened:return
        self.store.execute('''INSERT OR IGNORE INTO comment_reminders
            (opening_key,flow_id,comment_id,media_id,recipient_id,opened_at,next_at) VALUES(?,?,?,?,?,?,?)''',
            (key,flow['id'],str(value['id']),str(value['media']['id']),recipient,opened,opened+flow.get('comment_reminder_after_hours',24)*3600))
    def finish(self,key,state,detail):
        self.store.execute('UPDATE comment_reminders SET state=?,detail=? WHERE opening_key=?',(state,detail,key))
    def run_one(self,config,choices):
        now=self.clock()
        active=[f for f in choices if f['enabled'] and f.get('comment_reminder_enabled')]
        if not active:return False
        identifiers=[f['id'] for f in active];placeholders=','.join('?' for f in identifiers)
        rows=self.store.execute("SELECT * FROM comment_reminders WHERE state='waiting' AND next_at<=? AND flow_id IN ("+placeholders+") ORDER BY next_at LIMIT 1",[now,*identifiers])
        if not rows:return False
        job=rows[0];key=job['opening_key'];flow=next(f for f in active if f['id']==job['flow_id'])
        if flow.get('comment_reminder_account','self')!='self':
            self.finish(key,'blocked','Cross-account collaboration is no longer supported. Use this Instagram account.');return True
        # Honour edited delays before claiming a public reply.
        due=job['opened_at']+flow.get('comment_reminder_after_hours',24)*3600
        if due>now:self.store.execute('UPDATE comment_reminders SET next_at=? WHERE opening_key=?',(due,key));return True
        contact=self.store.execute('SELECT inbound_at FROM workflow_contacts WHERE flow_id=? AND recipient_id=?',(flow['id'],job['recipient_id']))
        if contact and contact[0]['inbound_at']>=job['opened_at']:
            self.finish(key,'cancelled','This person interacted with the opening.');return True
        api=self.factory(config)
        try:
            conversations=api.call('GET',config['account_id']+'/conversations',platform='instagram',user_id=job['recipient_id'],fields='id,participants',limit=10).get('data',[])
            conversation=next((c for c in conversations if any(str(p.get('id'))==job['recipient_id'] for p in c.get('participants',{}).get('data',[]))),None)
            if conversation:
                messages=api.call('GET',conversation['id'],fields='messages.limit(100){created_time,from}').get('messages',{}).get('data',[])
                incoming=[datetime.fromisoformat(m['created_time'].replace('Z','+00:00')).timestamp() for m in messages if str(m.get('from',{}).get('id'))==job['recipient_id']]
                if incoming and max(incoming)>=job['opened_at']:
                    self.finish(key,'cancelled','Live inbox confirms an interaction.');return True
        except Exception:
            self.store.execute('UPDATE comment_reminders SET next_at=?,detail=? WHERE opening_key=?',(now+300,'Inbox check unavailable; reminder postponed.',key));return True
        try:
            reply_config,claim=self.resolver(flow.get('comment_reminder_account','self'))
        except ValueError as error:
            if 'paused' in str(error):
                self.store.execute('UPDATE comment_reminders SET next_at=?,detail=? WHERE opening_key=?',(now+300,str(error),key))
            else:self.finish(key,'blocked',str(error))
            return True
        reply=self.factory(reply_config)
        try:
            post=reply.call('GET',job['media_id'],fields='id,owner')
            own={str(reply_config['account_id']),*map(str,reply_config.get('account_aliases',[]))}
            owner=post.get('owner',{});owner=owner.get('id') if isinstance(owner,dict) else owner
            if str(owner) not in own:
                self.finish(key,'blocked','Selected account does not own the media. Instagram comment moderation cannot post as that account; no fallback used.');return True
            comment=reply.call('GET',job['comment_id'],fields='id,text')
            if str(comment.get('id') or job['comment_id'])!=job['comment_id']:raise ValueError('Comment identity mismatch.')
        except Exception:
            self.finish(key,'blocked','Selected account cannot access this comment for moderation. No fallback account used.');return True
        try:
            action='rf-comment-reminder:'+str(config['account_id'])+':'+key
            claim(action,lambda:reply.call('POST',job['comment_id']+'/replies',{'message':flow['comment_reminder_text']}))
            self.finish(key,'sent','Instagram accepted the public comment reminder.')
        except Exception:
            self.finish(key,'review','Public reply was not confirmed; inspect before retrying.')
        return True
    def stats(self):
        return [dict(r) for r in self.store.execute("SELECT flow_id,'reminder' AS kind,state,count(*) AS count FROM comment_reminders GROUP BY flow_id,state")]
