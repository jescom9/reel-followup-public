#!/usr/bin/env python3
"""Merge an offline worker's archive and receipts into Neon without replaying sends."""
import argparse,json,sqlite3,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from native.neon_http import NeonHTTP,pg_value

def batches(db,sql,rows,size=100):
    for offset in range(0,len(rows),size):
        db.http({'queries':[{'query':sql,'params':[pg_value(v) for v in row]} for row in rows[offset:offset+size]]})

def migrate(project,env_file):
    state=project/'native/.local';report={'archives':0,'contacts':0,'actions':0,'deliveries':0}
    service=state/'worker-service.json'
    if service.exists():
        info=json.loads(service.read_text());pid=info.get('process_pid')
        if pid and Path('/proc/'+str(pid)+'/cmdline').exists() and 'native/app.py' in Path('/proc/'+str(pid)+'/cmdline').read_bytes().decode():raise ValueError('Stop the worker before migrating receipts.')
    with NeonHTTP(env_file) as cloud:
        for path in state.rglob('events.sqlite'):
            if 'backups' in path.parts:continue
            with sqlite3.connect('file:'+str(path)+'?mode=ro',uri=True) as source:
                source.row_factory=sqlite3.Row;tables={r[0] for r in source.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                if 'archive_records' in tables:
                    rows=[tuple(r) for r in source.execute('SELECT account_id,conversation_id,record_type,record_id,conversation_updated_at,message_created_at,participants,payload FROM archive_records')]
                    batches(cloud,"""INSERT INTO reel_followup_instagram_chat_archive(ig_account_id,conversation_id,record_type,record_id,conversation_updated_at,message_created_at,participants,payload) VALUES($1,$2,$3,$4,$5,$6,$7::jsonb,$8::jsonb) ON CONFLICT(ig_account_id,conversation_id,record_type,record_id) DO NOTHING""",rows);report['archives']+=len(rows)
                if 'local_flow_contacts' in tables:
                    rows=[(r['account_id'],r['recipient_id'],bool(r['opened']),bool(r['link_sent']),r['inbound_at'],r['media_id']) for r in source.execute('SELECT * FROM local_flow_contacts')]
                    batches(cloud,"""INSERT INTO reel_followup_instagram_contacts(ig_account_id,recipient_id,opened,link_sent,inbound_at,media_id) VALUES($1,$2,$3,$4,$5,$6) ON CONFLICT(ig_account_id,recipient_id) DO UPDATE SET opened=reel_followup_instagram_contacts.opened OR excluded.opened,link_sent=reel_followup_instagram_contacts.link_sent OR excluded.link_sent,inbound_at=greatest(reel_followup_instagram_contacts.inbound_at,excluded.inbound_at),media_id=CASE WHEN excluded.media_id='' THEN reel_followup_instagram_contacts.media_id ELSE excluded.media_id END""",rows);report['contacts']+=len(rows)
                if 'local_flow_actions' in tables:
                    rows=[tuple(r) for r in source.execute('SELECT account_id,action_id,state,receipt FROM local_flow_actions')]
                    # Sent is terminal; uncertain existing claims remain uncertain. Never make a claim retryable.
                    batches(cloud,"""INSERT INTO reel_followup_instagram_flow_actions(ig_account_id,action_id,state,receipt) VALUES($1,$2,$3,$4::jsonb) ON CONFLICT(ig_account_id,action_id) DO UPDATE SET state=CASE WHEN reel_followup_instagram_flow_actions.state='sent' OR excluded.state='sent' THEN 'sent' ELSE 'review' END,receipt=CASE WHEN reel_followup_instagram_flow_actions.state='sent' THEN reel_followup_instagram_flow_actions.receipt ELSE excluded.receipt END""",rows);report['actions']+=len(rows)
                if 'local_deliveries' in tables:
                    rows=[tuple(r) for r in source.execute('SELECT account_id,conversation_id,rule_key,recipient_id,source_message_id,state,receipt,detail FROM local_deliveries')]
                    batches(cloud,"""INSERT INTO reel_followup_instagram_followups(ig_account_id,conversation_id,rule_key,recipient_id,source_message_id,state,receipt,detail) VALUES($1,$2,$3,$4,$5,$6,$7::jsonb,$8) ON CONFLICT(ig_account_id,recipient_id,rule_key) DO UPDATE SET state=CASE WHEN reel_followup_instagram_followups.state='sent' OR excluded.state='sent' THEN 'sent' ELSE 'review' END,receipt=CASE WHEN reel_followup_instagram_followups.state='sent' THEN reel_followup_instagram_followups.receipt ELSE excluded.receipt END""",rows);report['deliveries']+=len(rows)
                # Verify every imported delivery identity exists before changing the worker environment.
                if 'local_flow_actions' in tables:
                    checks=[dict(r) for r in source.execute('SELECT account_id,action_id,state FROM local_flow_actions')]
                    for offset in range(0,len(checks),100):
                        part=checks[offset:offset+100]
                        result=cloud.http({'query':"SELECT count(*) FROM jsonb_to_recordset($1::jsonb) AS expected(account_id text,action_id text,state text) JOIN reel_followup_instagram_flow_actions actual ON actual.ig_account_id=expected.account_id AND actual.action_id=expected.action_id WHERE expected.state<>'sent' OR actual.state='sent'",'params':[json.dumps(part)]})
                        if int(result['rows'][0][0])!=len(part):raise ValueError('A migrated receipt could not be verified.')
    return report

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--project',type=Path,default=ROOT);parser.add_argument('--env-file',type=Path,required=True);args=parser.parse_args();print(json.dumps(migrate(args.project,args.env_file)))
