"""Read-only activity totals from one account's workspace database."""

def summary(store, items, include_legacy=False):
    contacts = [dict(row) for row in store.execute('SELECT flow_id,recipient_id,opened,link_sent FROM workflow_contacts')]
    # Historical single-flow contacts belong to the legacy flow. Merge rather
    # than add: the workflow engine may have already copied the same recipient.
    if include_legacy and any(flow['id'] == 'legacy' for flow in items):
        merged = {(row['flow_id'], row['recipient_id']): row for row in contacts}
        for row in store.execute('SELECT recipient_id,opened,link_sent FROM local_flow_contacts WHERE account_id=?', (store.config['account_id'],)):
            key = ('legacy', row['recipient_id'])
            existing = merged.get(key, {})
            merged[key] = {'flow_id': 'legacy', 'recipient_id': row['recipient_id'],
                'opened': bool(existing.get('opened') or row['opened']),
                'link_sent': bool(existing.get('link_sent') or row['link_sent'])}
        contacts = list(merged.values())
    jobs = [dict(row) for row in store.execute('SELECT flow_id,kind,state,count(*) n FROM workflow_jobs GROUP BY flow_id,kind,state')]
    jobs += [dict(row) for row in store.execute("SELECT flow_id,'reminder' kind,state,count(*) n FROM comment_reminders GROUP BY flow_id,state")]
    result = []
    for flow in items:
        owned = [row for row in contacts if row['flow_id'] == flow['id']]
        pending = [row for row in jobs if row['flow_id'] == flow['id']]
        def count(state, kind=None):
            return sum(row['n'] for row in pending if row['state'] == state and (kind is None or row['kind'] == kind))
        result.append({'id': flow['id'], 'runs': sum(bool(row['opened']) for row in owned),
            'links_sent': sum(bool(row['link_sent']) for row in owned),
            'followups_sent': count('sent', 'followup'), 'waiting': count('waiting'),
            'waiting_inbound': count('waiting_inbound'), 'expired': count('expired'),
            'review': count('review')+count('blocked'), 'ctr': None})
    return {'flows': result, **{key: sum(row[key] for row in result) for key in
        ('runs', 'links_sent', 'followups_sent', 'waiting', 'waiting_inbound', 'expired', 'review')}, 'ctr': None}
