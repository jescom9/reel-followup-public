"""Read-only, paginated schedules from an account's isolated worker database."""
import json,time
try:
    from .hosted_history import page_number
except ImportError:
    from hosted_history import page_number

def list_activity(store, items, data, now=None, local_history=False):
    if not isinstance(data,dict):raise ValueError('Invalid activity request.')
    page=page_number(data.get('page',0));kind=data.get('kind','all');history=data.get('history',False)
    if kind not in ('all','followup','follow','reminder') or not isinstance(history,bool):raise ValueError('Invalid activity filter.')
    now=time.time() if now is None else now
    by_id={flow['id']:flow for flow in items}
    where=[];args=[]
    if by_id:
        where.append('flow_id IN ('+','.join('?' for _ in by_id)+')');args.extend(by_id)
    else:where.append('0')
    if kind!='all':where.append('kind=?');args.append(kind)
    if not history:where.append("state IN ('waiting','waiting_inbound','review','blocked')")
    sql="""SELECT flow_id,recipient_id,kind,state,inbound_at requested_at,next_at due_at,0 started_at
        FROM workflow_jobs UNION ALL SELECT flow_id,recipient_id,'reminder',state,opened_at,next_at,opened_at FROM comment_reminders"""
    selection=' FROM ('+sql+') WHERE '+' AND '.join(where)
    total=store.execute('SELECT count(*) n'+selection,args)[0]['n']
    rows=store.execute('SELECT *'+selection+' ORDER BY CASE WHEN state IN (\'waiting\',\'waiting_inbound\') THEN 0 ELSE 1 END,due_at,flow_id,recipient_id LIMIT 30 OFFSET ?',[*args,page*30])
    result=[]
    for raw in rows:
        row=dict(raw);flow=by_id[row['flow_id']];row['flow_name']=flow['name'];row['username']=None
        if local_history:
            records=store.execute("""SELECT payload FROM archive_records WHERE account_id=? AND record_type='message'
                AND (json_extract(payload,'$.from.id')=? OR EXISTS (SELECT 1 FROM json_each(payload,'$.to.data') WHERE json_extract(value,'$.id')=?))
                ORDER BY message_created_at DESC LIMIT 1""",(store.config['account_id'],row['recipient_id'],row['recipient_id']))
            if records:
                payload=json.loads(records[0]['payload']);people=[payload.get('from') or {},*(payload.get('to') or {}).get('data',[])]
                row['username']=next((p.get('username') for p in people if str(p.get('id'))==row['recipient_id']),None)
        status=row['state']
        if status in ('waiting','waiting_inbound'):
            if not store.config['enabled']:status='paused_account'
            elif not flow['enabled']:status='paused_flow'
            elif row['kind']=='followup' and not flow['followup_enabled']:status='paused_followup'
            elif row['kind']=='reminder' and not flow.get('comment_reminder_enabled'):status='paused_reminder'
        row['status']=status
        if row['kind']=='reminder':row['due_at']=max(row['due_at'],row['started_at']+flow.get('comment_reminder_after_hours',24)*3600)
        result.append(row)
    batches=[]
    for batch in store.execute('SELECT id,keyword,state,next_at,interval_seconds FROM public_reply_batches WHERE account_id=? ORDER BY rowid DESC LIMIT 50',(store.config['account_id'],)):
        batch=dict(batch);counts={r['state']:r['n'] for r in store.execute('SELECT state,count(*) n FROM public_reply_jobs WHERE batch_id=? GROUP BY state',(batch['id'],))}
        total_jobs=sum(counts.values());done=counts.get('sent',0)+counts.get('skipped',0)
        active=batch['state']=='running' and store.config['enabled']
        batch.update(counts=counts,total=total_jobs,processed=done,status='paused_account' if batch['state']=='running' and not store.config['enabled'] else batch['state'],
            estimate_seconds=max(0,batch['next_at']-now)+max(0,counts.get('pending',0)-1)*batch['interval_seconds'] if active and counts.get('pending') else None)
        batches.append(batch)
    return {'rows':result,'total':total,'page':page,'server_time':now,'batches':batches}
