"""Owner-verified campaign setup through the operator's Instagram inbox."""
import hashlib,json,re,secrets,time
try:
    from .profiles import read_values
    from .workflows import flows,validate_flows
except ImportError:
    from profiles import read_values
    from workflows import flows,validate_flows

TEMPLATE_EXAMPLE="""Campaign:
Name: My bike tips
Keyword: TIPS
Link: [your HTTPS link]
Follow required: yes
Message: Thanks for following! Here are my bike tips 👇
Button: Get the tips"""
TEMPLATE="""Campaign:
Name:
Keyword:
Link:
Follow required: yes
Message:
Button:"""


def draft_from_text(text):
    fields={}
    for line in text.splitlines():
        if not line.strip():continue
        key,separator,value=line.partition(':');key=key.strip().casefold()
        if not separator or key not in ('campaign','name','keyword','link','follow required','message','button'):
            raise ValueError('Use the template fields: Name, Keyword, Link, Follow required, Message and Button.')
        if key in fields:raise ValueError('Use each template field once.')
        fields[key]=value.strip()
    if not all(fields.get(k) for k in ('name','keyword','link')):
        raise ValueError('Fill in Name, Keyword and Link before sending the template.')
    if ',' in fields['keyword']:raise ValueError('Use one keyword in each campaign template.')
    following=fields.get('follow required','yes').casefold()
    if following not in ('yes','no','ja','nein'):raise ValueError('Follow required must be yes or no.')
    candidate={'id':'setup-'+secrets.token_hex(8),'name':fields['name'],'keywords':[fields['keyword']],
        'enabled':True,'require_follow':following in ('yes','ja'),'link_button':True,'link_url':fields['link'],
        'media_scope':'all','media_ids':[],'opening_text':'Follow this account, then tap Following for your link 👇',
        'follow_text':'Follow this account and tap Following 👇','link_text':fields.get('message') or 'Here’s your link 👇',
        'button_text':fields.get('button') or 'Open link','public_reply':True,'public_reply_text':'Hey! Check your DMs for the link 👋',
        'followup_enabled':False,'followup_delay_minutes':60,'followup_text':'How has your experience been? 😊',
        'comment_reminder_enabled':False,'comment_reminder_after_hours':24,'comment_reminder_text':'Hey, check the link in my bio 👋','comment_reminder_account':'self'}
    return validate_flows([candidate])[0]


def matches_keyword(config,keyword):
    # Saved flow order supplies a deterministic newest choice for legacy duplicates.
    return [f for f in flows(config) if any(k.casefold()==keyword.casefold() for k in f['keywords'])]


def collision_signature(config,keyword):
    return hashlib.sha256(json.dumps(matches_keyword(config,keyword),sort_keys=True,separators=(',',':')).encode()).hexdigest()


class CampaignSetup:
    def __init__(self,registry,clock=time.time):self.registry,self.clock=registry,clock
    def settings(self):return read_values(self.registry.project/'.env')
    def enabled(self,config):
        name=self.settings().get('REEL_CAMPAIGN_SETUP_USERNAME','').strip().lstrip('@').casefold()
        return bool(name and config.get('verified') and config.get('username','').casefold()==name)
    def ready(self):
        return any(row['enabled'] and self.enabled({'verified':row['verified'],'username':row['username']}) for row in self.registry.listing())
    def signup_url(self):
        url=self.settings().get('REEL_CAMPAIGN_SETUP_SIGNUP_URL','https://reelfollowups.app/connect/')
        # The operator selects this URL; user input never controls the sign-in destination.
        return url if url.startswith('https://') else 'https://reelfollowups.app/connect/'
    def initialize(self,store):
        store.execute('''CREATE TABLE IF NOT EXISTS campaign_setup_requests (
            id TEXT PRIMARY KEY,event_key TEXT UNIQUE NOT NULL,sender_id TEXT NOT NULL,
            target_id TEXT NOT NULL,generation TEXT NOT NULL,candidate TEXT NOT NULL,
            collision_signature TEXT NOT NULL,expires_at REAL NOT NULL,state TEXT NOT NULL DEFAULT 'pending',
            result_flow_id TEXT NOT NULL DEFAULT '')''')
        store.execute('DELETE FROM campaign_setup_requests WHERE expires_at<?',(self.clock()-30*86400,))
    def generation(self,app):return str(app.store.config.get('managed_plan',{}).get('generation') or app.store.config.get('session_not_before',0))
    def owner(self,source_config,sender):
        profile=self.registry.graph(source_config).call('GET',sender,fields='id,username')
        username=str(profile.get('username') or '').casefold()
        if not username or (profile.get('id') and str(profile['id'])!=sender):return None
        for row in self.registry.listing():
            if not row['verified'] or row['username'].casefold()!=username:continue
            found=self.registry.find_account(row['account_id'])
            if not found:continue
            _,app=found
            # Check the connected account live, protecting recycled or renamed handles.
            live=self.registry.graph(dict(app.store.config)).call('GET','me',fields='user_id,username')
            if str(live.get('user_id') or live.get('id'))==str(row['account_id']) and str(live.get('username') or '').casefold()==username:
                return row['profile_id'],app
        return None
    def send(self,store,api,key,sender,text):return store.flow_once('setup:'+key,lambda:api.send({'id':sender},text))
    def buttons(self,store,api,key,sender,title,buttons):
        message={'attachment':{'type':'template','payload':{'template_type':'generic','elements':[{'title':title,'buttons':buttons}]}}}
        return store.flow_once('setup:'+key,lambda:api.call('POST',api.c['account_id']+'/messages',{'recipient':{'id':sender},'message':message}))
    def connect_prompt(self,store,api,key,sender):
        self.buttons(store,api,key,sender,'Connect your Instagram account to create a campaign.',[{'type':'web_url','title':'Connect Instagram','url':self.signup_url()}])
    def preview(self,store,api,key,sender,target,candidate):
        self.initialize(store);config=dict(target.store.config);signature=collision_signature(config,candidate['keywords'][0])
        old=store.execute('SELECT * FROM campaign_setup_requests WHERE event_key=?',(key,))
        if old:request=dict(old[0])
        else:
            request={'id':secrets.token_hex(16),'target_id':str(config['account_id']),'generation':self.generation(target),'collision_signature':signature}
            store.execute('INSERT INTO campaign_setup_requests(id,event_key,sender_id,target_id,generation,candidate,collision_signature,expires_at) VALUES(?,?,?,?,?,?,?,?)',
                (request['id'],key,sender,request['target_id'],request['generation'],json.dumps(candidate),signature,self.clock()+900))
        matches=matches_keyword(config,candidate['keywords'][0]);chosen=matches[-1] if matches else candidate
        if matches and not chosen['link_url']:raise ValueError('This keyword belongs to an unfinished draft. Finish it in your dashboard or choose a different keyword.')
        summary=('Already used: reuse '+chosen['name'] if matches else 'Create: '+chosen['name'])+'\nKeyword: '+candidate['keywords'][0]
        # Full link and current behavior appear in a separate plain message before confirmation.
        detail=f"@{config['username']} · {chosen['name']}\nKeyword: {candidate['keywords'][0]}\nLink: {chosen['link_url']}\nFollow required: {'yes' if chosen['require_follow'] else 'no'}"
        if matches:detail+='\nThis keyword already exists. We’ll use the latest existing campaign without changing it.'
        elif not config.get('enabled'):detail+='\nYour account is paused. The campaign will wait until you resume it.'
        self.send(store,api,key+':details',sender,detail)
        self.buttons(store,api,key+':preview',sender,summary[:80],[{'type':'postback','title':'Confirm campaign','payload':'RF_SETUP_CONFIRM:'+request['id']},{'type':'postback','title':'Cancel','payload':'RF_SETUP_CANCEL:'+request['id']}])
    def confirmation(self,store,api,key,sender,target,request_id,cancel=False):
        self.initialize(store);rows=store.execute('SELECT * FROM campaign_setup_requests WHERE id=? AND sender_id=?',(request_id,sender))
        if not rows:self.send(store,api,key,sender,'This request is unavailable. Tap Send template to start again.');return 'Unknown or unrelated setup request.'
        request=dict(rows[0])
        if request['target_id']!=str(target.store.config['account_id']) or request['generation']!=self.generation(target):
            self.send(store,api,key,sender,'Your workspace changed. Send a new campaign template.');return 'Workspace identity changed.'
        if request['state']=='confirmed':
            self.send(store,api,key,sender,'This campaign is already saved. Find it in your dashboard.');return 'Already confirmed; no repeated changes.'
        if request['state']!='pending' or request['expires_at']<=self.clock():
            self.send(store,api,key,sender,'This confirmation expired. Send a new campaign template.');return 'Setup confirmation expired.'
        if cancel:
            store.execute("UPDATE campaign_setup_requests SET state='cancelled' WHERE id=?",(request_id,))
            self.send(store,api,key,sender,'Cancelled. Your campaigns are unchanged.');return 'Setup cancelled.'
        candidate=json.loads(request['candidate'])
        with target.lifecycle:
            # Deletion/reconnection and edits can occur while the owner is reviewing the preview.
            found=self.registry.find_account(request['target_id'])
            if not found or found[1] is not target or target.stop.is_set() or self.generation(target)!=request['generation']:
                self.send(store,api,key,sender,'Open your dashboard to reconnect before creating a campaign.');return 'Workspace unavailable.'
            latest=store.execute('SELECT state FROM campaign_setup_requests WHERE id=?',(request_id,))[0]
            if latest['state']!='pending':
                self.send(store,api,key,sender,'This request has already been handled. Find your campaigns in the dashboard.');return 'No repeated setup change.'
            config=dict(target.store.config)
            if request['collision_signature']!=collision_signature(config,candidate['keywords'][0]):
                store.execute("UPDATE campaign_setup_requests SET state='superseded' WHERE id=?",(request_id,))
                self.preview(store,api,key+':changed',sender,target,candidate);return 'Keyword changed; a new preview needs confirmation.'
            current=flows(config);matches=matches_keyword(config,candidate['keywords'][0]);chosen=matches[-1] if matches else candidate
            if not matches:
                target.store.save({**config,'flows':validate_flows([*current,candidate]),'workflow_mode':'manychat'})
            store.execute("UPDATE campaign_setup_requests SET state='confirmed',result_flow_id=? WHERE id=?",(chosen['id'],request_id))
        state='active' if config.get('enabled') and chosen['enabled'] else 'paused'
        self.send(store,api,key,sender,f"{chosen['name']} is {state}.\nKeyword: {candidate['keywords'][0]}\nManage it: https://reelfollowups.app/dashboard/#flows")
        return 'Campaign confirmed; existing keyword reused.' if matches else 'Campaign created after owner confirmation.'
    def process(self,source,key,event,config):
        if not self.enabled(config) or event.get('kind')!='message':return None
        value=event.get('value') or {};sender=str(value.get('sender',{}).get('id') or '')
        try:stamp=float(value.get('timestamp') or 0)/1000
        except (ValueError,TypeError):return 'Invalid setup message timestamp.'
        if not sender or sender in {str(config['account_id']),*map(str,config.get('account_aliases',[]))} or not 0<=self.clock()-stamp<86400:
            return 'Setup message outside the reply window.'
        api=self.registry.graph(config);store=source.store
        try:owner=self.owner(config,sender)
        except Exception:
            self.send(store,api,key,sender,'I couldn’t verify your Instagram account. Please set up your campaign in https://reelfollowups.app/dashboard/')
            return 'Owner verification unavailable; no workspace changed.'
        if not owner:self.connect_prompt(store,api,key,sender);return 'Unconnected sender directed to sign-in.'
        _,target=owner
        alerts=getattr(self.registry,'service_alerts',None)
        if alerts:alerts.refresh(source,sender,stamp)
        message=value.get('message',{});postback=value.get('postback',{})
        payload=message.get('quick_reply',{}).get('payload') or postback.get('payload') or ''
        if payload=='RF_SETUP_TEMPLATE':
            self.send(store,api,key+':example',sender,TEMPLATE_EXAMPLE)
            self.send(store,api,key+':blank',sender,TEMPLATE)
            return 'Campaign example and blank template sent.'
        for prefix,cancel in [('RF_SETUP_CONFIRM:',False),('RF_SETUP_CANCEL:',True)]:
            if payload.startswith(prefix):return self.confirmation(store,api,key,sender,target,payload[len(prefix):],cancel)
        text=str(message.get('text') or '')
        if alerts and text.strip().casefold()=='alerts' and alerts.subscribe(source,sender,target,stamp,key):return 'Owner-verified service alerts subscribed.'
        if len(text)>3000:self.send(store,api,key,sender,'Keep the campaign template under 3,000 characters.');return 'Setup message too long.'
        if re.search(r'^\s*(Campaign|Name|Keyword|Link)\s*:',text,re.I|re.M):
            try:
                candidate=draft_from_text(text)
                with target.lifecycle:
                    validate_flows([*flows(target.store.config),candidate]) if not matches_keyword(target.store.config,candidate['keywords'][0]) else None
                    self.preview(store,api,key,sender,target,candidate)
            except ValueError as error:self.send(store,api,key,sender,str(error))
            return 'Campaign draft previewed or validation explained.'
        self.buttons(store,api,key,sender,'Create a campaign for @'+target.store.config['username'],[{'type':'postback','title':'Send template','payload':'RF_SETUP_TEMPLATE'},{'type':'web_url','title':'My dashboard','url':'https://reelfollowups.app/dashboard/#flows'}])
        return 'Campaign setup menu sent.'
