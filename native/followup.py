"""Follow-up selection, live preflight checks, and durable delivery claims."""
import json, re, time
from datetime import datetime, timezone
from pathlib import Path

PHRASE = 'Works best in Chrome on Mac/Windows'
TEXT = 'Hi, ich hoffe, dir hat’s geholfen. Erstell gerne ein Reel und teile es mit deinen Freunden.'
RULE = 'bikefit-reel-results-v1'
FIELDS = 'id,created_time,from,to,message,attachments'
ROOT = Path(__file__).resolve().parent

try:
    from .storage import StorageBridge as NeonBridge, ArchiveError
except ImportError:
    from storage import StorageBridge as NeonBridge, ArchiveError

def stamp(message):
    try: return datetime.fromisoformat(message.get('created_time','').replace('Z','+00:00')).timestamp()
    except (ValueError,TypeError): return 0

def message_text(message):
    pieces = [message.get('message') or '']
    for attachment in (message.get('attachments') or {}).get('data',[]):
        template = attachment.get('generic_template') or {}
        pieces.extend([template.get('title') or '',template.get('subtitle') or ''])
    return ' '.join(pieces)

def matches(message, account_id):
    return str((message.get('from') or {}).get('id')) == account_id and PHRASE.casefold() in message_text(message).casefold()

def message_page(api, conversation_id, cursor=None):
    # Instagram returns ManyChat generic-template attachments through this field expansion.
    # The cursor belongs inside messages.after(...), not on the conversation's outer query.
    if cursor and not re.fullmatch(r'[A-Za-z0-9_+/=\-]+',cursor): raise ArchiveError('Instagram returned an invalid message cursor.')
    field = 'messages.limit(100)' + (f'.after({cursor})' if cursor else '') + '{' + FIELDS + '}'
    return api.call('GET',conversation_id,fields=field).get('messages') or {}

def preflight(api, target, account_id, now):
    """Re-read latest message and inbound time; never send from a stale archive match."""
    cursor, seen, first = None,set(),True
    while True:
        page = message_page(api,target['conversation_id'],cursor)
        messages = sorted(page.get('data',[]),key=stamp,reverse=True)
        if first:
            if not messages: return 'unavailable'
            latest = messages[0]
            if latest.get('id') != target['source_message_id'] or not matches(latest,account_id): return 'changed'
            recipients = (latest.get('to') or {}).get('data',[])
            if not any(str(r.get('id')) == target['recipient_id'] for r in recipients): return 'changed'
            first = False
        for message in messages:
            if str((message.get('from') or {}).get('id')) == target['recipient_id']:
                return 'ready' if 0 <= now-stamp(message) < 86400 else 'window_closed'
        if messages and stamp(messages[-1]) <= now-86400: return 'window_closed'
        paging = page.get('paging') or {}
        cursor = (paging.get('cursors') or {}).get('after')
        if not paging.get('next') or not cursor or cursor in seen: return 'window_closed'
        seen.add(cursor)

def deliver(api, db, store, target, config, clock=time.time, retry_rejected=False):
    account_id = str(config['account_id'])
    status = preflight(api,target,account_id,clock())
    if status != 'ready': return status
    identity = {**target,'ig_account_id':account_id,'rule_key':RULE,'retry_rejected':retry_rejected}
    if not db.request({'claim':identity}).get('claimed'): return 'already_recorded'
    key = f'followup:{RULE}:{account_id}:{target["recipient_id"]}'
    if retry_rejected:
        # A fresh durable claim permits retry only of a confirmed HTTP rejection, never a sent/unknown attempt.
        store.execute("DELETE FROM actions WHERE id=? AND state='review'",(key,))
    try:
        receipt = store.once(key,
            lambda: api.send({'id':target['recipient_id']},TEXT))
    except Exception as error:
        # HTTP rejection is definite. Timeouts/crashes are uncertain and must never be retried blindly.
        state = 'rejected' if 'Meta rejected the request' in str(error) else 'review'
        detail = str(error) if type(error).__name__ == 'MetaError' else 'Delivery outcome needs review.'
        if getattr(error,'subcode',None) == 2534037:
            detail = 'Meta says this app does not own the conversation. Assign it in Conversation Routing before retrying.'
        db.request({'finish':{**identity,'state':state,'detail':detail,
            'receipt':{'error_code':getattr(error,'code',None),'error_subcode':getattr(error,'subcode',None)}}})
        return state
    db.request({'finish':{**identity,'state':'sent','receipt':receipt,'detail':'Instagram accepted the follow-up.'}})
    created = datetime.fromtimestamp(clock(),timezone.utc).isoformat()
    message = {'id':receipt['message_id'],'message':TEXT,'created_time':created,
        'from':{'id':account_id,'username':config['username']},
        'to':{'data':[{'id':target['recipient_id'],'username':target.get('username') or ''}]}}
    db.request({'records':[{'ig_account_id':account_id,'conversation_id':target['conversation_id'],
        'record_type':'message','record_id':receipt['message_id'],'message_created_at':created,
        'payload':message,'participants':[message['from'],message['to']['data'][0]]}]})
    return 'sent'
