"""Neon SQL-over-HTTPS adapter; the Pi needs only Python's standard library."""
import hashlib,json,os,re,threading
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request,urlopen

class ArchiveError(Exception):pass

QUERIES=json.loads(Path(__file__).with_name('neon_queries.json').read_text())
_prepared=set();_prepare_lock=threading.Lock()

def pg_value(value):
    if value is None:return None
    if isinstance(value,bool):return 'true' if value else 'false'
    if isinstance(value,(list,tuple)):
        return '{'+','.join('NULL' if v is None else '"'+str(v).replace('\\','\\\\').replace('"','\\"')+'"' for v in value)+'}'
    if isinstance(value,dict):return json.dumps(value,separators=(',',':'))
    return str(value)

def decode(value,oid):
    if value is None:return None
    if oid==16:return value in ('t','true',True)
    if oid in (20,21,23,26):return int(value)
    if oid in (700,701,1700):return float(value)
    if oid in (114,3802):return json.loads(value) if isinstance(value,str) else value
    if oid in (1114,1184):return datetime.fromisoformat(value.replace('Z','+00:00')).isoformat()
    return value

class NeonHTTP:
    def __init__(self,env_file=None,timeout=30,prepare=True):self.env_file,self.timeout,self.prepare=env_file,timeout,prepare
    def __enter__(self):
        env_path=Path(self.env_file or os.environ.get('REEL_ENV_FILE') or Path(__file__).resolve().parent.parent/'.env')
        values={}
        if env_path.exists():
            for line in env_path.read_text().splitlines():
                if '=' in line and not line.lstrip().startswith('#'):
                    key,value=line.split('=',1);values[key.strip()]=value.strip().strip('"').strip("'")
        self.connection=values.get('REEL_FOLLOWUP_DATABASE_URL','')
        parsed=urlsplit(self.connection)
        if parsed.scheme not in ('postgres','postgresql') or not parsed.hostname or not parsed.hostname.endswith('.neon.tech'):
            raise ArchiveError('Configure a private Neon database connection in the worker environment.')
        self.endpoint='https://api.'+parsed.hostname.split('.',1)[1]+'/sql'
        if not self.prepare:return self
        identity=hashlib.sha256(self.connection.encode()).hexdigest()
        with _prepare_lock:
            if identity not in _prepared:
                schema=[{'query':QUERIES[key],'params':[]} for key in ['archive_schema','archive_update_index','archive_message_index','delivery_schema',*sorted(k for k in QUERIES if k.startswith('flow_schema_'))]]
                self.http({'queries':schema});_prepared.add(identity)
        return self
    def __exit__(self,*args):pass
    def http(self,payload):
        request=Request(self.endpoint,data=json.dumps(payload).encode(),method='POST',headers={
            'Content-Type':'application/json','Neon-Connection-String':self.connection,
            'Neon-Raw-Text-Output':'true','Neon-Array-Mode':'true'})
        try:
            with urlopen(request,timeout=self.timeout) as response:return json.load(response)
        except Exception:raise ArchiveError('The Neon operation could not be confirmed; saved data and delivery claims are retained.') from None
    def query(self,name,args=(),**replacements):
        query=QUERIES[name].replace('${chatView}',QUERIES['chatView']).replace('${hostedChatView}',QUERIES['hosted_chat_view'])
        for key,value in replacements.items():query=query.replace('${'+key+'}',value)
        if '${' in query:raise ArchiveError('Incomplete archive query.')
        result=self.http({'query':query,'params':[pg_value(arg) for arg in args]})
        fields=result.get('fields',[])
        return [{field['name']:decode(value,field['dataTypeID']) for field,value in zip(fields,row)} for row in result.get('rows',[])]
    def request(self,data):
        q=self.query;account=str(data.get('ig_account_id') or '')
        if data.get('done'):return {'done':True}
        if data.get('webhook_pull'):return {'events':q('webhook_pull',[[account,*map(str,data.get('account_aliases',[]))]])}
        if data.get('webhook_stats'):return {'stats':q('webhook_stats',[[account,*map(str,data.get('account_aliases',[]))]])[0]}
        if 'webhook_finish' in data:
            v=data['webhook_finish']
            if v['state'] not in ('imported','done','review','ignored'):raise ArchiveError('Invalid event state.')
            q('webhook_finish',[v['ig_account_id'],v['event_id'],v['state'],v.get('detail','')]);return {'recorded':True}
        if 'flow_action_claim' in data:
            v=data['flow_action_claim'];args=[v['ig_account_id'],v['action_id']]
            inserted=q('flow_action_claim',args);action=q('flow_action_get',args)[0]
            return {'claimed':len(inserted)==1,**action}
        if 'flow_action_finish' in data:
            v=data['flow_action_finish']
            if v['state'] not in ('sent','review','rejected'):raise ArchiveError('Invalid action state.')
            q('flow_action_finish',[v['ig_account_id'],v['action_id'],v['state'],json.dumps(v.get('receipt',{}))]);return {'recorded':True}
        if 'flow_contact_get' in data:
            v=data['flow_contact_get'];args=[v['ig_account_id'],v['recipient_id']]
            contacts=q('flow_contact_get',args);contact=contacts[0] if contacts else {}
            history=q('flow_contact_history',args)[0];opening=q('flow_contact_opening',args)
            return {'contact':{'opened':bool(contact.get('opened') or opening or history.get('received_opening')),
                'link_sent':bool(contact.get('link_sent') or history.get('received_link')),
                'inbound_at':contact.get('inbound_at',0),'media_id':contact.get('media_id','')}}
        if 'flow_contact_put' in data:
            v=data['flow_contact_put'];q('flow_contact_put',[v['ig_account_id'],v['recipient_id'],bool(v.get('opened')),bool(v.get('link_sent')),float(v.get('inbound_at') or 0),v.get('media_id','')]);return {'recorded':True}
        if data.get('overview') or data.get('targets'):
            args=[account,str(data.get('rule_key') or ''),str(data.get('phrase') or '')]
            if data.get('targets'):
                retry="OR (status='rejected' AND inbound_time>now()-interval '24 hours')" if data.get('retry_rejected') else ''
                return {'targets':q('targets',args,retryFilter=retry)}
            page=max(0,int(data.get('page') or 0));filter='(is_match OR delivery_state IS NOT NULL)' if data.get('view')!='all' else 'true'
            stats=q('overview_stats',args)[0];total=q('overview_total',args,filter=filter)[0]['n']
            return {'stats':stats,'total':total,'page':page,'rows':q('overview_rows',[*args,page*30],filter=filter)}
        if 'claim' in data:
            v=data['claim'];rows=q('claim',[v['ig_account_id'],v['conversation_id'],v['rule_key'],v['recipient_id'],v['source_message_id'],bool(v.get('retry_rejected'))]);return {'claimed':len(rows)==1}
        if 'finish' in data:
            v=data['finish']
            if v['state'] not in ('sent','review','rejected'):raise ArchiveError('Invalid delivery state.')
            q('finish',[v['ig_account_id'],v['conversation_id'],v['rule_key'],v['state'],json.dumps(v.get('receipt',{})),v.get('detail','')]);return {'recorded':True}
        if data.get('manifest'):return {'manifest':q('manifest',[account])}
        if 'index_cursor' in data:
            v=data['index_cursor'];q('index_cursor',[v.get('ig_account_id',''),v.get('conversation_id',''),v.get('cursor')]);return {'checkpoint':True}
        if not isinstance(data.get('records'),list):raise ArchiveError('Unsupported archive operation.')
        records=data['records'];saved=0
        for offset in range(0,len(records),100):
            chunk=records[offset:offset+100];args=[];values=[]
            for row in chunk:
                start=len(args);args.extend([row['ig_account_id'],row['conversation_id'],row['record_type'],row['record_id'],row.get('conversation_updated_at'),row.get('message_created_at'),json.dumps(row.get('participants',[])),json.dumps(row['payload'])])
                values.append('('+','.join('$'+str(start+i)+( '::jsonb' if i in (7,8) else '') for i in range(1,9))+',now())')
            q('records',args,values=','.join(values));saved+=len(chunk)
        return {'saved':saved}
