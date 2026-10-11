"""Local durable archive, contacts and delivery receipts using SQLite only."""
import json,os,sqlite3,time
from datetime import datetime,timezone
from pathlib import Path
try:
    from .neon_http import ArchiveError
except ImportError:
    from neon_http import ArchiveError

def timestamp(value):
    if not value:return 0
    if isinstance(value,(float,int)):return float(value)
    try:return datetime.fromisoformat(str(value).replace('Z','+00:00')).timestamp()
    except ValueError:return 0

class LocalStorage:
    def __init__(self,folder):self.folder=Path(folder)
    def __enter__(self):
        self.folder.mkdir(parents=True,exist_ok=True,mode=0o700)
        path=self.folder/'events.sqlite';self.db=sqlite3.connect(path,timeout=30)
        self.db.row_factory=sqlite3.Row;os.chmod(path,0o600)
        self.db.executescript("""
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS archive_records(account_id TEXT,conversation_id TEXT,record_type TEXT,record_id TEXT,
            conversation_updated_at TEXT,message_created_at TEXT,participants TEXT,payload TEXT,
            PRIMARY KEY(account_id,conversation_id,record_type,record_id));
        CREATE TABLE IF NOT EXISTS local_flow_actions(account_id TEXT,action_id TEXT,state TEXT,receipt TEXT,
            PRIMARY KEY(account_id,action_id));
        CREATE TABLE IF NOT EXISTS local_flow_contacts(account_id TEXT,recipient_id TEXT,opened INTEGER DEFAULT 0,
            link_sent INTEGER DEFAULT 0,inbound_at REAL DEFAULT 0,media_id TEXT DEFAULT '',PRIMARY KEY(account_id,recipient_id));
        CREATE TABLE IF NOT EXISTS local_deliveries(account_id TEXT,conversation_id TEXT,rule_key TEXT,recipient_id TEXT,
            source_message_id TEXT,state TEXT,receipt TEXT DEFAULT '{}',detail TEXT DEFAULT '',
            PRIMARY KEY(account_id,conversation_id,rule_key),UNIQUE(account_id,recipient_id,rule_key));
        """)
        return self
    def __exit__(self,*args):self.db.close()
    def execute(self,sql,args=()):
        with self.db:
            cursor=self.db.execute(sql,args);return cursor.fetchall(),cursor.rowcount
    def overview(self,data):
        account=data['ig_account_id'];rule=data.get('rule_key','');phrase=data.get('phrase','').casefold()
        records,_=self.execute("SELECT * FROM archive_records WHERE account_id=?",(account,))
        messages=[dict(r) for r in records if r['record_type']=='message'];latest={};inbound={}
        for row in sorted(messages,key=lambda r:(timestamp(r['message_created_at']),r['record_id']),reverse=True):
            payload=json.loads(row['payload']);cid=row['conversation_id'];sender=str(payload.get('from',{}).get('id',''))
            if sender!=account:inbound[cid]=max(inbound.get(cid,0),timestamp(row['message_created_at']))
            if cid not in latest:latest[cid]=row
        saved,_=self.execute("SELECT * FROM local_deliveries WHERE account_id=? AND rule_key=?",(account,rule))
        deliveries={r['conversation_id']:dict(r) for r in saved};rows=[]
        for cid,row in latest.items():
            p=json.loads(row['payload']);sender=str(p.get('from',{}).get('id',''))
            pieces=[p.get('message') or '']
            for attachment in p.get('attachments',{}).get('data',[]) if p.get('attachments') else []:
                card=attachment.get('generic_template') or {};pieces += [card.get('title',''),card.get('subtitle','')]
            preview=' '.join(pieces);recipient=next((r for r in p.get('to',{}).get('data',[]) if str(r.get('id'))!=account),{})
            recipient=p.get('from',{}) if sender!=account else recipient
            delivery=deliveries.get(cid,{})
            match=sender==account and phrase in preview.casefold()
            state=delivery.get('state') or ('not_matching' if not match else 'unknown_recipient' if not recipient.get('id') else 'window_closed' if not 0<=time.time()-inbound.get(cid,0)<86400 else 'ready')
            rows.append({'conversation_id':cid,'source_message_id':row['record_id'],'recipient_id':str(recipient.get('id') or ''),
                'username':recipient.get('username',''),'preview':preview,'latest_at':row['message_created_at'],
                'inbound_time':datetime.fromtimestamp(inbound[cid],timezone.utc).isoformat() if inbound.get(cid) else None,
                'status':state,'delivery_detail':delivery.get('detail',''),'is_match':match})
        rows.sort(key=lambda r:timestamp(r['latest_at']),reverse=True)
        conversations=[r for r in records if r['record_type']=='conversation']
        stats={'conversations':len(conversations),'messages':len(messages),'unavailable':sum(json.loads(r['payload']).get('archive_sync_state')=='incomplete' for r in conversations),
            'matches':sum(r['is_match'] for r in rows),'eligible':sum(r['is_match'] and r['status']=='ready' for r in rows),
            'window_closed':sum(r['is_match'] and r['status']=='window_closed' for r in rows),'sent':sum(r['status']=='sent' for r in rows),
            'rejected':sum(r['status']=='rejected' for r in rows),'needs_review':sum(r['status'] in ('review','attempting','rejected') for r in rows)}
        if data.get('targets'):
            return {'targets':[r for r in rows if r['is_match'] and (r['status']=='ready' or data.get('retry_rejected') and r['status']=='rejected' and 0<=time.time()-timestamp(r['inbound_time'])<86400)]}
        visible=[r for r in rows if data.get('view')=='all' or r['is_match'] or r['status'] in ('sent','rejected','review','attempting')]
        page=max(0,int(data.get('page',0)))
        return {'stats':stats,'rows':visible[page*30:page*30+30],'total':len(visible),'page':page}
    def request(self,data):
        account=str(data.get('ig_account_id',''))
        if data.get('done'):return {'done':True}
        if 'flow_action_claim' in data:
            v=data['flow_action_claim'];args=[v['ig_account_id'],v['action_id']]
            _,count=self.execute("INSERT OR IGNORE INTO local_flow_actions VALUES(?,?,'attempting','{}')",args)
            rows,_=self.execute('SELECT state,receipt FROM local_flow_actions WHERE account_id=? AND action_id=?',args)
            return {'claimed':count==1,'state':rows[0]['state'],'receipt':json.loads(rows[0]['receipt'])}
        if 'flow_action_finish' in data:
            v=data['flow_action_finish']
            if v['state'] not in ('sent','rejected','review'):raise ArchiveError('Invalid action state.')
            self.execute("UPDATE local_flow_actions SET state=?,receipt=? WHERE account_id=? AND action_id=? AND state='attempting'",
                [v['state'],json.dumps(v.get('receipt',{})),v['ig_account_id'],v['action_id']]);return {'recorded':True}
        if 'flow_contact_get' in data:
            v=data['flow_contact_get'];args=[v['ig_account_id'],v['recipient_id']]
            rows,_=self.execute('SELECT * FROM local_flow_contacts WHERE account_id=? AND recipient_id=?',args)
            contact=dict(rows[0]) if rows else {'opened':False,'link_sent':False,'inbound_at':0,'media_id':''}
            contact['opened']=bool(contact.get('opened'));contact['link_sent']=bool(contact.get('link_sent'))
            return {'contact':contact}
        if 'flow_contact_put' in data:
            v=data['flow_contact_put']
            self.execute("""INSERT INTO local_flow_contacts VALUES(?,?,?,?,?,?) ON CONFLICT(account_id,recipient_id) DO UPDATE SET
                opened=max(opened,excluded.opened),link_sent=max(link_sent,excluded.link_sent),
                inbound_at=max(inbound_at,excluded.inbound_at),media_id=CASE WHEN excluded.media_id='' THEN media_id ELSE excluded.media_id END""",
                [v['ig_account_id'],v['recipient_id'],bool(v.get('opened')),bool(v.get('link_sent')),v.get('inbound_at',0),v.get('media_id','')]);return {'recorded':True}
        if data.get('overview') or data.get('targets'):return self.overview(data)
        if 'claim' in data:
            v=data['claim'];args=[v['ig_account_id'],v['conversation_id'],v['rule_key'],v['recipient_id'],v['source_message_id']]
            _,count=self.execute("INSERT OR IGNORE INTO local_deliveries(account_id,conversation_id,rule_key,recipient_id,source_message_id,state) VALUES(?,?,?,?,?,'attempting')",args)
            if not count and v.get('retry_rejected'):
                _,count=self.execute("UPDATE local_deliveries SET state='attempting',source_message_id=? WHERE account_id=? AND conversation_id=? AND rule_key=? AND state='rejected'",
                    [v['source_message_id'],v['ig_account_id'],v['conversation_id'],v['rule_key']])
            return {'claimed':count==1}
        if 'finish' in data:
            v=data['finish']
            if v['state'] not in ('sent','review','rejected'):raise ArchiveError('Invalid delivery state.')
            self.execute("UPDATE local_deliveries SET state=?,receipt=?,detail=? WHERE account_id=? AND conversation_id=? AND rule_key=? AND state='attempting'",
                [v['state'],json.dumps(v.get('receipt',{})),v.get('detail',''),v['ig_account_id'],v['conversation_id'],v['rule_key']]);return {'recorded':True}
        if data.get('manifest'):
            rows,_=self.execute("SELECT * FROM archive_records WHERE account_id=? AND record_type='conversation'",[account])
            return {'manifest':[{'conversation_id':r['conversation_id'],'conversation_updated_at':r['conversation_updated_at'],
                **{key:json.loads(r['payload']).get(key) for key in ['archive_next_cursor','archive_next_conversation_cursor','archive_schema_version']},
                'archive_state':json.loads(r['payload']).get('archive_sync_state'),
                'archive_schema_version':str(json.loads(r['payload']).get('archive_schema_version')) if json.loads(r['payload']).get('archive_schema_version') is not None else None} for r in rows]}
        if 'index_cursor' in data:
            v=data['index_cursor'];rows,_=self.execute("SELECT payload FROM archive_records WHERE account_id=? AND conversation_id=? AND record_type='conversation'",[v['ig_account_id'],v['conversation_id']])
            for row in rows:
                p=json.loads(row['payload'])
                if v.get('cursor'):p['archive_next_conversation_cursor']=v['cursor']
                else:p.pop('archive_next_conversation_cursor',None)
                self.execute("UPDATE archive_records SET payload=? WHERE account_id=? AND conversation_id=? AND record_type='conversation'",[json.dumps(p),v['ig_account_id'],v['conversation_id']])
            return {'checkpoint':True}
        if data.get('webhook_stats'):
            rows,_=self.execute("SELECT name FROM sqlite_master WHERE name='events'")
            events,_=self.execute('SELECT state,created FROM events') if rows else ([],0)
            return {'stats':{'received':len(events),'pending':sum(r['state']=='pending' for r in events),
                'done':sum(r['state']=='done' for r in events),'review':sum(r['state']=='review' for r in events),'imported':0,
                'last_received':datetime.fromtimestamp(max(r['created'] for r in events),timezone.utc).isoformat() if events else None}}
        if data.get('webhook_pull'):return {'events':[]}
        if data.get('webhook_finish'):return {'recorded':True}
        if not isinstance(data.get('records'),list):raise ArchiveError('Unsupported local storage operation.')
        for v in data['records']:
            self.execute("""INSERT INTO archive_records VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(account_id,conversation_id,record_type,record_id)
                DO UPDATE SET conversation_updated_at=excluded.conversation_updated_at,message_created_at=excluded.message_created_at,participants=excluded.participants,payload=excluded.payload""",
                [v['ig_account_id'],v['conversation_id'],v['record_type'],v['record_id'],v.get('conversation_updated_at'),v.get('message_created_at'),
                json.dumps(v.get('participants',[])),json.dumps(v['payload'])])
        return {'saved':len(data['records'])}
