"""Fixed, single-account comment → button → follower-check flow."""
import re,time
from datetime import datetime

DAY=86400
OPENING='Hi 🤗 Folge @jescojm und unterstütze meine Arbeit. Tippe auf Following 👇'
FOLLOW_BUTTON='Following'
PUBLIC_REPLY='Sent you a message! Check it out!'
LINK='https://bikefitting.fit/'
BUTTON_PAYLOADS={'send me the link':'BF_LINK','send mir den link':'BF_LINK','ich folge':'BF_FOLLOW','ich folge dir':'BF_FOLLOW','following':'BF_FOLLOW'}

class ManychatFlow:
    def __init__(self,store,graph_factory,clock=time.time): self.store,self.factory,self.clock=store,graph_factory,clock; self.checks=None
    def process(self,key,event,c):
        api=self.factory(c);now=self.clock();value=event['value']
        username=c.get('username') or 'jescojm'
        link=c.get('link_url') or LINK
        # Keep generic-template titles below Meta's 80 UTF-16-code-unit limit.
        opening=f'Hi 🤗 Folge @{username}. Tippe auf Following 👇'
        if username=='jescojm': opening=OPENING
        own={str(c['account_id']),*map(str,c.get('account_aliases',[]))}
        if event['kind']=='comment':
            sender=str(value.get('from',{}).get('id') or '')
            media=str(value.get('media',{}).get('id') or '')
            if not sender or sender in own or not media or value.get('parent_id'): return 'Comment outside this Reel flow.'
            if not re.search(r'(?<!\w)'+re.escape(c['keyword'])+r'(?!\w)',value.get('text',''),re.I): return 'Keyword not matched.'
            if event.get('received',now)<float(c.get('campaign_started_at') or 0): return 'Comment received before this campaign started.'
            post=api.call('GET',media,fields='id,owner,media_product_type')
            if str(post.get('owner',{}).get('id')) not in own or post.get('media_product_type')!='REELS': return 'The comment is not on a Reel owned by the connected account.'
            comment=api.call('GET',str(value['id']),fields='timestamp')
            created=datetime.fromisoformat(comment['timestamp'].replace('Z','+00:00')).timestamp()
            if not 0<=now-created<7*DAY: return 'Comment outside the seven-day private-reply window.'
            opening_key=f'mc-opening:v1:{media}:{sender}'
            receipt=self.store.flow_once(opening_key,lambda:api.send_button({'comment_id':str(value['id'])},opening,FOLLOW_BUTTON,'BF_FOLLOW'))
            recipient=str(receipt.get('recipient_id') or sender)
            self.store.flow_contact_put(recipient,opened=True,media_id=media)
            if c.get('public_reply',True):
                self.store.flow_once('mc-public:v1:'+str(value['id']),lambda:api.call('POST',str(value['id'])+'/replies',{'message':PUBLIC_REPLY}))
            return 'Opening DM accepted; public confirmation accepted.'
        sender=str(value.get('sender',{}).get('id') or '')
        stamp=float(value.get('timestamp') or 0)/1000
        if not sender or sender in own or not 0<=now-stamp<DAY: return 'Message outside the 24-hour response window.'
        message,postback=value.get('message',{}),value.get('postback',{})
        payload=message.get('quick_reply',{}).get('payload') or postback.get('payload')
        if not payload or str(payload).startswith('ACT::'):
            text=' '.join(str(postback.get('title') or message.get('text') or '').casefold().split())
            payload=BUTTON_PAYLOADS.get(text)
        if payload not in ('BF_LINK','BF_FOLLOW'): return 'Message retained; no flow button matched.'
        contact=self.store.flow_contact_get(sender)
        if not contact.get('opened'): return 'No opening DM from this flow was recorded for this contact.'
        self.store.flow_contact_put(sender,inbound_at=stamp)
        try: following=api.call('GET',sender,fields='is_user_follow_business').get('is_user_follow_business')
        except Exception: following=None
        if following is True:
            result=self.send_verified_link(key,sender,c)
            if self.checks: self.checks.cancel(sender)
            return result
        if self.checks: self.checks.schedule(sender,key,stamp)
        if following is False:
            text=f'Folge @{username} und tippe auf Following 👇'
        else:
            text='Follower-Status wird geprüft. Tippe auf Following zum erneuten Prüfen 👇'
        self.store.flow_once('mc-response:'+key,lambda:api.send_button({'id':sender},text,FOLLOW_BUTTON,'BF_FOLLOW'))
        return 'Follow prompt accepted; automatic recheck scheduled.' if following is False else 'Follower status unavailable; automatic recheck scheduled.'
    def send_verified_link(self,key,sender,c,deferred=False):
        api=self.factory(c);contact=self.store.flow_contact_get(sender)
        if not contact.get('opened'): return 'No opening DM from this flow was recorded for this contact.'
        link=c.get('link_url') or LINK
        if contact.get('link_sent'):
            if deferred: return 'Link already delivered; no repeat link sent.'
            self.store.flow_once('mc-link-response:'+key,lambda:api.send({'id':sender},'Hier kommst du wieder zu deinem Dashboard: '+link+' 😊'))
            return 'Follower verified; returning contact received the dashboard link.'
        title='Hier ist dein kostenloses Bikefitting: ' if c.get('username','jescojm')=='jescojm' else 'Hier ist dein Link: '
        self.store.flow_once('mc-link-response:'+key,lambda:self.store.flow_once('mc-link:v1:'+sender,lambda:api.send({'id':sender},title+link+'\n\nWorks best in Chrome on Mac/Windows 😊')))
        self.store.flow_contact_put(sender,link_sent=True)
        return 'Follower verified; link accepted.'
