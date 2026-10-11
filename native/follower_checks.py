"""Durable follower rechecks inside Instagram's inbound reply window."""
import time

DELAYS = (5, 15, 30, 60, 120, 300, 900, 1800)

class FollowerChecks:
    def __init__(self, store, factory, deliver, clock=time.time):
        self.store, self.factory, self.deliver, self.clock = store, factory, deliver, clock
        store.execute('''CREATE TABLE IF NOT EXISTS follower_checks (
            recipient_id TEXT PRIMARY KEY,event_key TEXT NOT NULL,inbound_at REAL NOT NULL,
            next_at REAL NOT NULL,attempts INTEGER NOT NULL DEFAULT 0,state TEXT NOT NULL DEFAULT 'waiting',
            detail TEXT NOT NULL DEFAULT '')''')
    def schedule(self, recipient, key, inbound):
        self.store.execute('''INSERT INTO follower_checks(recipient_id,event_key,inbound_at,next_at)
            VALUES(?,?,?,?) ON CONFLICT(recipient_id) DO UPDATE SET
            event_key=excluded.event_key,inbound_at=max(inbound_at,excluded.inbound_at),
            next_at=excluded.next_at,attempts=0,state='waiting',detail='' ''',
            (recipient,key,inbound,self.clock()+DELAYS[0]))
    def cancel(self, recipient):
        self.store.execute("UPDATE follower_checks SET state='done' WHERE recipient_id=?",(recipient,))
    def run_one(self, config):
        now = self.clock()
        jobs = self.store.execute("SELECT * FROM follower_checks WHERE state='waiting' AND next_at<=? ORDER BY next_at LIMIT 1",(now,))
        if not jobs: return False
        job=jobs[0]; recipient=job['recipient_id']
        if not 0 <= now-job['inbound_at'] < 86400:
            self.store.execute("UPDATE follower_checks SET state='expired',detail='Inbound reply window closed.' WHERE recipient_id=?",(recipient,))
            return True
        try:
            following=self.factory(config).call('GET',recipient,fields='is_user_follow_business').get('is_user_follow_business')
        except Exception: following=None
        if following is not True:
            attempt=job['attempts']+1
            delay=DELAYS[min(attempt,len(DELAYS)-1)]
            self.store.execute('UPDATE follower_checks SET attempts=?,next_at=?,detail=? WHERE recipient_id=?',
                (attempt,now+delay,'Waiting for Meta to confirm following; no repeat prompt sent.',recipient))
            return True
        try:
            # A separate durable send claim is essential: the earlier prompt is not a link receipt.
            detail=self.deliver(job['event_key'],recipient,config,deferred=True)
            self.store.execute("UPDATE follower_checks SET state='done',detail=? WHERE recipient_id=?",(detail,recipient))
        except Exception:
            self.store.execute("UPDATE follower_checks SET state='review',detail='Link delivery needs review; not retried automatically.' WHERE recipient_id=?",(recipient,))
        return True
