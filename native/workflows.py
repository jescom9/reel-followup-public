"""Editable keyword flows with durable, isolated contacts and follow-up jobs."""
import json,re,secrets,time
from datetime import datetime
from urllib.parse import urlsplit
try:
    from .manychat import OPENING,LINK,PUBLIC_REPLY
    from .plans import admit,reconcile
    from .comment_reminders import CommentReminders,DEFAULT_TEXT
except ImportError:
    from manychat import OPENING,LINK,PUBLIC_REPLY
    from plans import admit,reconcile
    from comment_reminders import CommentReminders,DEFAULT_TEXT

DEFAULT_FOLLOWUP='Hi, ich hoffe, dir hat’s geholfen. Teile dein Ergebnis gerne mit deinen Freunden.'

def flows(config):
    if 'flows' in config:
        items=[{**{'comment_reminder_enabled':False,'comment_reminder_after_hours':24,'comment_reminder_text':DEFAULT_TEXT,'comment_reminder_account':'self','media_scope':'all','media_ids':[]},**f} for f in config['flows']]
        for item in items:
            if item['comment_reminder_account']!='self':
                item.update(comment_reminder_account='self',comment_reminder_enabled=False)
        return items
    return [{'id':'legacy','name':'Reel link','keywords':[config.get('keyword') or 'Fit'],
        'enabled':True,'require_follow':True,'link_button':False,'link_url':config.get('link_url') or LINK,
        'opening_text':OPENING if config.get('username')=='jescojm' else 'Tippe auf Following, nachdem du meinem Account folgst 👇',
        'follow_text':'Folge meinem Account und tippe danach auf Following 👇',
        'link_text':'Hier ist dein kostenloses Bikefitting:' if config.get('username')=='jescojm' else 'Hier ist dein Link:',
        'button_text':'Open link','public_reply':config.get('public_reply',True),'public_reply_text':PUBLIC_REPLY,
        'followup_enabled':True,'followup_delay_minutes':60,'followup_text':DEFAULT_FOLLOWUP,
        'comment_reminder_enabled':False,'comment_reminder_after_hours':24,'comment_reminder_text':DEFAULT_TEXT,'comment_reminder_account':'self'}]

def validate_flows(items):
    if not isinstance(items,list) or not 1<=len(items)<=20:raise ValueError('Save between 1 and 20 flows.')
    result=[];ids=set();words={}
    for item in items:
        if not isinstance(item,dict):raise ValueError('Invalid flow settings.')
        fid=str(item.get('id') or secrets.token_hex(8))
        if not re.fullmatch(r'[a-zA-Z0-9_-]{1,40}',fid) or fid in ids:raise ValueError('Flow IDs must be unique.')
        ids.add(fid)
        scope=item.get('media_scope','all');media=item.get('media_ids',[])
        if scope not in ('all','selected') or not isinstance(media,list) or len(media)>50 or any(not isinstance(mid,str) or not re.fullmatch(r'\d{1,32}',mid) for mid in media) or len(set(media))!=len(media):raise ValueError('Choose all Reels or up to 50 unique Instagram Reel IDs.')
        if scope=='selected' and not media:raise ValueError('Select at least one Reel for this flow.')
        media=media if scope=='selected' else []
        keywords=item.get('keywords')
        if isinstance(keywords,str):keywords=keywords.split(',')
        if not isinstance(keywords,list) or not 1<=len(keywords)<=10:raise ValueError('Enter 1–10 comma-separated keywords for each flow.')
        keywords=[str(word).strip() for word in keywords]
        for word in keywords:
            if not 1<=len(word)<=50:raise ValueError('Keywords must be 1–50 characters long.')
            owners=words.setdefault(word.casefold(),[])
            if any(scope=='all' or old['scope']=='all' or set(media).intersection(old['media']) for old in owners):raise ValueError('Keywords must be unique across flows that target the same Reel.')
            owners.append({'scope':scope,'media':media})
        url=str(item.get('link_url') or '').strip();parsed=urlsplit(url)
        if (url or item.get('enabled')) and (parsed.scheme!='https' or not parsed.netloc or parsed.username or parsed.password or any(ch in url for ch in '\r\n\x00')):
            raise ValueError('Each flow needs an HTTPS link without embedded credentials.')
        entry={'id':fid,'keywords':keywords,'link_url':url,'media_scope':scope,'media_ids':media}
        for key,limit in [('name',60),('opening_text',80),('follow_text',80),('link_text',80),('button_text',20),('public_reply_text',300),('followup_text',1000)]:
            text=str(item.get(key) or '').strip()
            if not text or len(text.encode('utf-16-le'))//2>limit:raise ValueError(f'{key.replace("_"," ").capitalize()} must contain 1–{limit} characters (emoji can count as two).')
            entry[key]=text
        for key in ['enabled','require_follow','link_button','public_reply','followup_enabled']:
            if not isinstance(item.get(key),bool):raise ValueError('Flow switches must be true or false.')
            entry[key]=item[key]
        delay=item.get('followup_delay_minutes',60)
        if isinstance(delay,bool) or not isinstance(delay,(int,float)) or not 1<=delay<=1380:raise ValueError('Follow-up delay must be between 1 and 1380 minutes.')
        entry['followup_delay_minutes']=delay
        reminder=item.get('comment_reminder_enabled',False)
        hours=item.get('comment_reminder_after_hours',24)
        if not isinstance(reminder,bool) or isinstance(hours,bool) or not isinstance(hours,(int,float)) or not 1<=hours<=168:raise ValueError('Reminder delay must be 1–168 hours.')
        text=str(item.get('comment_reminder_text') or DEFAULT_TEXT).strip()
        if not 1<=len(text)<=300:raise ValueError('Reminder text must be 1–300 characters.')
        sender=str(item.get('comment_reminder_account') or 'self')
        if sender!='self':raise ValueError('Comment reminders must use this Instagram account. Cross-account collaboration is no longer supported.')
        entry.update(comment_reminder_enabled=reminder,comment_reminder_after_hours=hours,comment_reminder_text=text,comment_reminder_account=sender)
        result.append(entry)
    return result

class WorkflowEngine:
    def __init__(self,store,factory,legacy,clock=time.time):
        self.store,self.factory,self.legacy,self.clock=store,factory,legacy,clock
        store.execute('''CREATE TABLE IF NOT EXISTS workflow_contacts (
            flow_id TEXT NOT NULL,recipient_id TEXT NOT NULL,opened INTEGER NOT NULL DEFAULT 0,
            link_sent INTEGER NOT NULL DEFAULT 0,inbound_at REAL NOT NULL DEFAULT 0,updated_at REAL NOT NULL,
            PRIMARY KEY(flow_id,recipient_id))''')
        store.execute('''CREATE TABLE IF NOT EXISTS workflow_jobs (
            flow_id TEXT NOT NULL,recipient_id TEXT NOT NULL,kind TEXT NOT NULL,event_key TEXT NOT NULL,
            inbound_at REAL NOT NULL,next_at REAL NOT NULL,attempts INTEGER NOT NULL DEFAULT 0,
            state TEXT NOT NULL DEFAULT 'waiting',detail TEXT NOT NULL DEFAULT '',
            PRIMARY KEY(flow_id,recipient_id,kind))''')
        self.reply_resolver=lambda selected:(dict(self.store.config),self.store.flow_once) if selected=='self' else self.unknown_sender()
        self.reminders=CommentReminders(store,factory,lambda selected:self.reply_resolver(selected),clock)
        old=store.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='follower_checks'")
        if old:
            store.execute("""INSERT OR IGNORE INTO workflow_jobs(flow_id,recipient_id,kind,event_key,inbound_at,next_at,attempts,state,detail)
                SELECT 'legacy',recipient_id,'follow',event_key,inbound_at,next_at,attempts,state,detail FROM follower_checks WHERE state='waiting'""")
            legacy_flow=next((f for f in flows(store.config) if f['id']=='legacy'),None) if hasattr(store,'config') else None
            if legacy_flow:
                store.execute("""INSERT OR IGNORE INTO workflow_jobs(flow_id,recipient_id,kind,event_key,inbound_at,next_at)
                    SELECT 'legacy',recipient_id,'followup',event_key,inbound_at,? FROM follower_checks
                    WHERE state='done' AND detail='Follower verified; link accepted.' AND inbound_at>?""",
                    (self.clock()+legacy_flow['followup_delay_minutes']*60,self.clock()-86400))
    def record_opening(self,send):
        started=self.clock();return {**send(),'_reel_opened_at':started}
    def unknown_sender(self):raise ValueError('This reminder account is not connected.')
    def contact(self,fid,recipient):
        rows=self.store.execute('SELECT * FROM workflow_contacts WHERE flow_id=? AND recipient_id=?',(fid,recipient))
        local=dict(rows[0]) if rows else {}
        if fid=='legacy':
            old=self.store.flow_contact_get(recipient)
            local={**local,'opened':bool(local.get('opened') or old.get('opened')),
                'link_sent':bool(local.get('link_sent') or old.get('link_sent')),
                'inbound_at':max(local.get('inbound_at',0),old.get('inbound_at',0))}
        return local
    def put(self,fid,recipient,opened=False,link_sent=False,inbound=0):
        self.store.execute('''INSERT INTO workflow_contacts VALUES(?,?,?,?,?,?)
            ON CONFLICT(flow_id,recipient_id) DO UPDATE SET opened=max(opened,excluded.opened),
            link_sent=max(link_sent,excluded.link_sent),inbound_at=max(inbound_at,excluded.inbound_at),updated_at=excluded.updated_at''',
            (fid,recipient,int(opened),int(link_sent),inbound,self.clock()))
    def schedule(self,flow,recipient,kind,key,inbound):
        delay=5 if kind=='follow' else flow['followup_delay_minutes']*60
        self.store.execute('''INSERT INTO workflow_jobs(flow_id,recipient_id,kind,event_key,inbound_at,next_at)
            VALUES(?,?,?,?,?,?) ON CONFLICT(flow_id,recipient_id,kind) DO UPDATE SET
            event_key=excluded.event_key,inbound_at=max(inbound_at,excluded.inbound_at),
            next_at=CASE WHEN workflow_jobs.state='waiting' THEN min(next_at,excluded.next_at) ELSE excluded.next_at END,
            state=CASE WHEN workflow_jobs.state IN ('sent','review') THEN workflow_jobs.state ELSE 'waiting' END''',
            (flow['id'],recipient,kind,key,inbound,self.clock()+delay))
    def finish(self,job,state,detail):
        self.store.execute('UPDATE workflow_jobs SET state=?,detail=? WHERE flow_id=? AND recipient_id=? AND kind=?',
            (state,detail,job['flow_id'],job['recipient_id'],job['kind']))
    def send_link(self,key,recipient,flow,config,inbound,deferred=False):
        fid=flow['id'];contact=self.contact(fid,recipient);api=self.factory(config)
        if not contact.get('opened'):return 'No recorded opening for this flow.'
        if deferred and contact.get('link_sent'):return 'Link already delivered; no repeat link sent.'
        def send():
            if flow['link_button']:return api.send_link({'id':recipient},flow['link_text'],flow['button_text'],flow['link_url'])
            return api.send({'id':recipient},flow['link_text']+' '+flow['link_url']+'\n\nWorks best in Chrome on Mac/Windows 😊')
        response='rf-response:'+fid+':'+key
        if contact.get('link_sent'):
            self.store.flow_once(response,send)
        else:
            self.store.flow_once(response,lambda:self.store.flow_once('rf-link:'+fid+':'+recipient,send))
        self.put(fid,recipient,opened=True,link_sent=True,inbound=inbound)
        if fid=='legacy':self.store.flow_contact_put(recipient,link_sent=True,inbound_at=inbound)
        # A paused follow-up can be resumed later; the job does not send while paused.
        self.schedule(flow,recipient,'followup',key,inbound)
        self.store.execute("UPDATE workflow_jobs SET state='sent',detail='Link delivered.' WHERE flow_id=? AND recipient_id=? AND kind='follow'",(fid,recipient))
        return 'Link accepted; follow-up scheduled or paused.'
    def process(self,key,event,config):
        choices=flows(config);value=event['value'];now=self.clock();api=self.factory(config)
        own={str(config['account_id']),*map(str,config.get('account_aliases',[]))}
        if event['kind']=='comment':
            media=str(value.get('media',{}).get('id') or '')
            flow=next((f for f in choices if f['enabled'] and (f.get('media_scope','all')=='all' or media in f.get('media_ids',[])) and any(re.search(r'(?<!\w)'+re.escape(word)+r'(?!\w)',value.get('text',''),re.I) for word in f['keywords'])),None)
            if not flow:return 'No active keyword flow matched.'
            sender=str(value.get('from',{}).get('id') or '');media=str(value.get('media',{}).get('id') or '')
            if not sender or sender in own or not media or value.get('parent_id'):return 'Comment outside this Reel flow.'
            if event.get('received',now)<float(config.get('campaign_started_at') or 0):return 'Comment received before this campaign started.'
            post=api.call('GET',media,fields='id,owner,media_product_type')
            if str(post.get('owner',{}).get('id')) not in own or post.get('media_product_type')!='REELS':return 'Comment is not on a Reel owned by this account.'
            comment=api.call('GET',str(value['id']),fields='timestamp')
            created=datetime.fromisoformat(comment['timestamp'].replace('Z','+00:00')).timestamp()
            if not 0<=now-created<7*86400:return 'Comment outside the private-reply window.'
            if not admit(self.store,sender):return 'Contact limit reached. Upgrade from Plans to admit new contacts.'
            fid=flow['id'];opening_key=f'mc-opening:v1:{media}:{sender}' if fid=='legacy' else f'rf-opening:{fid}:{media}:{sender}'
            accepted=False
            def opening(action):
                nonlocal accepted
                receipt=self.record_opening(action);accepted=True;return receipt
            if flow['require_follow']:
                receipt=self.store.flow_once(opening_key,lambda:opening(lambda:api.send_button({'comment_id':str(value['id'])},flow['opening_text'],'Following','RF_FOLLOW:'+fid)))
            elif flow['link_button']:
                receipt=self.store.flow_once(opening_key,lambda:opening(lambda:api.send_link({'comment_id':str(value['id'])},flow['link_text'],flow['button_text'],flow['link_url'])))
            else:
                receipt=self.store.flow_once(opening_key,lambda:opening(lambda:api.send({'comment_id':str(value['id'])},flow['link_text']+' '+flow['link_url'])))
            recipient=str(receipt.get('recipient_id') or sender)
            reconcile(self.store,sender,recipient)
            self.put(fid,recipient,opened=True,link_sent=not flow['require_follow'])
            if accepted:self.reminders.schedule(flow,opening_key,value,recipient,receipt)
            if not flow['require_follow']:self.schedule(flow,recipient,'followup',key,0)
            if flow['public_reply']:
                self.store.flow_once(('mc-public:v1:' if fid=='legacy' else 'rf-public:'+fid+':')+str(value['id']),lambda:api.call('POST',str(value['id'])+'/replies',{'message':flow['public_reply_text']}))
            return f'{flow["name"]}: opening accepted.'
        sender=str(value.get('sender',{}).get('id') or '');stamp=float(value.get('timestamp') or 0)/1000
        if not sender or sender in own or not 0<=now-stamp<86400:return 'Message outside the 24-hour reply window.'
        # Any inbound message opens the reply window for follow-ups on already delivered flows.
        self.store.execute('UPDATE workflow_contacts SET inbound_at=max(inbound_at,?) WHERE recipient_id=?',(stamp,sender))
        self.store.execute("UPDATE workflow_jobs SET inbound_at=max(inbound_at,?),next_at=CASE WHEN state='waiting_inbound' THEN min(next_at,?) ELSE next_at END,state=CASE WHEN state='waiting_inbound' THEN 'waiting' ELSE state END WHERE recipient_id=?",(stamp,now,sender))
        message=value.get('message',{});postback=value.get('postback',{})
        payload=message.get('quick_reply',{}).get('payload') or postback.get('payload') or ''
        fid=payload.split(':',1)[1] if payload.startswith(('RF_FOLLOW:','RF_LINK:')) else None
        if payload in ('BF_FOLLOW','BF_LINK') or payload.startswith('ACT::'):fid='legacy'
        if not fid:
            text=' '.join(str(postback.get('title') or message.get('text') or '').casefold().split())
            if text not in ('following','ich folge','ich folge dir','send me the link','send mir den link'):return 'Inbound saved; no flow button matched.'
            contacts=self.store.execute('SELECT flow_id FROM workflow_contacts WHERE recipient_id=? AND opened=1 ORDER BY updated_at DESC LIMIT 1',(sender,))
            fid=contacts[0]['flow_id'] if contacts else 'legacy'
        flow=next((f for f in choices if f['id']==fid and f['enabled']),None)
        if not flow:return 'This keyword flow is paused or no longer exists.'
        if payload.startswith('ACT::'):
            title=' '.join(str(postback.get('title') or '').casefold().split())
            if title not in ('following','ich folge','ich folge dir','send me the link','send mir den link'):return 'Unrelated legacy button ignored.'
        contact=self.contact(fid,sender)
        if not contact.get('opened'):return 'No recorded opening for this flow.'
        self.put(fid,sender,opened=True,inbound=stamp)
        if fid=='legacy':self.store.flow_contact_put(sender,inbound_at=stamp)
        if not flow['require_follow']:return self.send_link(key,sender,flow,config,stamp)
        try:following=api.call('GET',sender,fields='is_user_follow_business').get('is_user_follow_business')
        except Exception:following=None
        if following is True:return self.send_link(key,sender,flow,config,stamp)
        self.schedule(flow,sender,'follow',key,stamp)
        # One stable postback prompt per contact, not a new prompt for every impatient tap.
        text=flow['follow_text'] if following is False else 'Follower-Status wird geprüft. Tippe auf Following zum erneuten Prüfen 👇'
        self.store.flow_once('rf-prompt:'+fid+':'+sender,lambda:api.send_button({'id':sender},text,'Following','RF_FOLLOW:'+fid))
        return 'Follower recheck scheduled; no repeated prompt.'
    def run_one(self,config):
        now=self.clock();choices={f['id']:f for f in flows(config)}
        if self.reminders.run_one(config,list(choices.values())):return True
        active=[f for f in choices.values() if f['enabled']]
        if not active:return False
        conditions=' OR '.join("(flow_id=? AND (kind='follow' OR ?))" for f in active)
        args=[now]
        for f in active:args.extend([f['id'],int(f['followup_enabled'])])
        jobs=self.store.execute("SELECT * FROM workflow_jobs WHERE state IN ('waiting','waiting_inbound') AND next_at<=? AND ("+conditions+") ORDER BY next_at LIMIT 1",args)
        for job in jobs:
            flow=choices.get(job['flow_id'])
            if not flow:self.finish(job,'cancelled','Flow removed.');return True
            if not flow['enabled'] or (job['kind']=='followup' and not flow['followup_enabled']):continue
            contact=self.contact(flow['id'],job['recipient_id']);inbound=max(job['inbound_at'],contact.get('inbound_at',0))
            if job['kind']=='follow' and not 0<=now-inbound<86400:
                self.finish(job,'expired','24-hour reply window closed; no message sent.');return True
            api=self.factory(config)
            if job['kind']=='follow':
                if contact.get('link_sent'):self.finish(job,'sent','Link already delivered.');return True
                try:following=api.call('GET',job['recipient_id'],fields='is_user_follow_business').get('is_user_follow_business')
                except Exception:following=None
                if flow['require_follow'] and following is not True:
                    delays=(15,30,60,120,300,900,1800);attempt=job['attempts']+1
                    self.store.execute('UPDATE workflow_jobs SET attempts=?,next_at=? WHERE flow_id=? AND recipient_id=? AND kind=?',
                        (attempt,now+delays[min(attempt-1,len(delays)-1)],flow['id'],job['recipient_id'],job['kind']));return True
                try:self.send_link(job['event_key'],job['recipient_id'],flow,config,inbound,deferred=True);self.finish(job,'sent','Follower confirmed; link delivered.')
                except Exception:self.finish(job,'review','Delivery outcome needs review; not retried automatically.')
                return True
            # Re-read the live inbox rather than sending from an old local window timestamp.
            try:
                conversations=api.call('GET',config['account_id']+'/conversations',platform='instagram',user_id=job['recipient_id'],fields='id,participants',limit=10).get('data',[])
                conv=next((v for v in conversations if any(str(p.get('id'))==job['recipient_id'] for p in v.get('participants',{}).get('data',[]))),None)
                if not conv:raise ValueError('Conversation unavailable')
                recent=api.call('GET',conv['id'],fields='messages.limit(100){id,created_time,from,message}').get('messages',{}).get('data',[])
                inbound_messages=[datetime.fromisoformat(m['created_time'].replace('Z','+00:00')).timestamp() for m in recent if str(m.get('from',{}).get('id'))==job['recipient_id']]
                if not inbound_messages:
                    self.finish(job,'waiting_inbound','Waiting for an actual inbound reply; URL clicks alone do not open the reply window.')
                    self.store.execute("UPDATE workflow_jobs SET next_at=? WHERE flow_id=? AND recipient_id=? AND kind='followup'",(now+1800,flow['id'],job['recipient_id']))
                    return True
                if not 0<=now-max(inbound_messages)<86400:self.finish(job,'expired','Live inbox has no open 24-hour reply window.');return True
            except Exception:
                self.store.execute('UPDATE workflow_jobs SET next_at=?,detail=? WHERE flow_id=? AND recipient_id=? AND kind=?',
                    (now+300,'Could not check live inbox; send postponed.',flow['id'],job['recipient_id'],job['kind']));return True
            try:
                self.store.flow_once('rf-followup:'+flow['id']+':'+job['recipient_id'],lambda:api.send({'id':job['recipient_id']},flow['followup_text']))
                self.finish(job,'sent','Instagram accepted the follow-up.')
            except Exception:self.finish(job,'review','Follow-up delivery needs review; not retried automatically.')
            return True
        return False
    def stats(self):
        return [dict(row) for row in self.store.execute('SELECT flow_id,kind,state,count(*) AS count FROM workflow_jobs GROUP BY flow_id,kind,state')]+self.reminders.stats()
