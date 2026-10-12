"""Read-only, account-scoped history for the hosted dashboard."""
import json
try:
    from .followup import message_text
except ImportError:
    from followup import message_text

def page_number(value):
    if isinstance(value,bool) or not isinstance(value,int) or not 0<=value<=100000:
        raise ValueError('Invalid history page.')
    return value

def summary(store):
    account=store.config['account_id']
    def count(sql):return store.execute(sql,(account,))[0]['n']
    return {'conversations':count("SELECT count(DISTINCT conversation_id) n FROM archive_records WHERE account_id=?"),
        'messages':count("SELECT count(*) n FROM archive_records WHERE account_id=? AND record_type='message'"),
        'contacts':count('SELECT count(*) n FROM local_flow_contacts WHERE account_id=?'),
        'reached':count('SELECT count(*) n FROM local_flow_contacts WHERE account_id=? AND (opened=1 OR link_sent=1)'),
        'accepted_actions':count("SELECT count(*) n FROM local_flow_actions WHERE account_id=? AND state='sent'")}

def chats(store,data):
    page=page_number(data.get('page',0));account=store.config['account_id']
    search=data.get('search','')
    if not isinstance(search,str) or len(search)>100:raise ValueError('Use a shorter contact search.')
    rows=store.execute("""SELECT conversation_id,record_id,payload,message_created_at FROM (
        SELECT *,row_number() OVER (PARTITION BY conversation_id ORDER BY message_created_at DESC,record_id DESC) position
        FROM archive_records WHERE account_id=? AND record_type='message') WHERE position=1 ORDER BY message_created_at DESC""",(account,))
    own={account,*map(str,store.config.get('account_aliases',[]))};result=[]
    for row in rows:
        payload=json.loads(row['payload']);sender=payload.get('from') or {}
        recipient=next((p for p in (payload.get('to') or {}).get('data',[]) if str(p.get('id')) not in own),{}) if str(sender.get('id')) in own else sender
        name=recipient.get('username') or recipient.get('id') or 'Instagram contact'
        if search.casefold() not in str(name).casefold():continue
        result.append({'conversation_id':row['conversation_id'],'recipient_id':str(recipient.get('id') or ''),
            'username':str(name),'preview':message_text(payload)[:240],'latest_at':row['message_created_at']})
    return {'rows':result[page*30:page*30+30],'total':len(result),'page':page}

def conversation(store,data):
    page=page_number(data.get('page',0));identifier=data.get('conversation_id')
    if not isinstance(identifier,str) or not 1<=len(identifier)<=512:raise ValueError('Invalid conversation.')
    account=store.config['account_id'];args=(account,identifier)
    total=store.execute("SELECT count(*) n FROM archive_records WHERE account_id=? AND conversation_id=? AND record_type='message'",args)[0]['n']
    rows=store.execute("SELECT payload,message_created_at FROM archive_records WHERE account_id=? AND conversation_id=? AND record_type='message' ORDER BY message_created_at DESC,record_id DESC LIMIT 30 OFFSET ?",(*args,page*30))
    own={account,*map(str,store.config.get('account_aliases',[]))};messages=[]
    for row in reversed(rows):
        payload=json.loads(row['payload']);sender=payload.get('from') or {}
        messages.append({'text':message_text(payload) or '[Attachment]','created_at':row['message_created_at'],
            'outgoing':str(sender.get('id')) in own,'sender':sender.get('username') or sender.get('id') or 'Instagram contact'})
    return {'messages':messages,'total':total,'page':page,'conversation_id':identifier}
