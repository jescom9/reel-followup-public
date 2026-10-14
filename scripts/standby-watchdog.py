#!/usr/bin/env python3
"""Cold standby checks the primary ingress; it never runs customer campaigns."""
import json,time
from pathlib import Path
from urllib.request import Request,build_opener,HTTPRedirectHandler
from urllib.error import HTTPError
from cryptography.fernet import Fernet

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None

def run(folder,keyfile,statefile,fetch=None,clock=time.time):
    fetch=fetch or build_opener(NoRedirect).open
    payloadfile=folder/'alerts.rfalert'
    if not payloadfile.exists() or not keyfile.exists():return {'ready':False}
    raw=payloadfile.read_bytes()
    if not raw.startswith(b'RFAL1'):raise ValueError('Invalid alert envelope.')
    payload=json.loads(Fernet(keyfile.read_bytes()).decrypt(raw[5:]));url=payload.get('health_url','')
    if not url.startswith('https://') or not url.endswith('/host/health'):raise ValueError('Invalid primary health destination.')
    state=json.loads(statefile.read_text()) if statefile.exists() else {'failures':0,'incident':0,'notified':False}
    try:
        with fetch(Request(url,data=b'{}',method='POST',headers={'Content-Type':'application/json'}),timeout=10) as r:healthy=False
    except HTTPError as e:
        # The primary's specific authentication rejection proves its ingress is alive
        # without giving this watchdog the privileged host-service signing key.
        try:healthy=e.code==403 and json.load(e).get('error')=='Host authentication denied.'
        except Exception:healthy=False
    except Exception:healthy=False
    if healthy:
        state['failures']=0;mode='recovered' if state['notified'] else None
    else:
        state['failures']+=1
        if state['failures']==1:state['incident']=int(clock())
        mode='down' if state['failures']>=3 and not state['notified'] else None
    recipients=[r for r in payload['subscribers'] if 0<=clock()-r['inbound_at']<86400]
    if mode and recipients:
        state['notified']=mode=='down';state['last_notice']=mode;state['send_state']='attempting'
        # Persist before sending; uncertain results are never automatically retried.
        statefile.parent.mkdir(parents=True,exist_ok=True,mode=0o700);statefile.write_text(json.dumps(state));statefile.chmod(0o600)
        text='Service alert from the standby Pi: '+('the main webhook service failed three consecutive checks. Campaign replies may be delayed. Check Admin → Resources and the main Pi.' if mode=='down' else 'the main webhook service is reachable again. Check saved requests and uncertain deliveries in Admin.')
        try:
            for recipient in recipients:
                body=json.dumps({'recipient':{'id':recipient['sender_id']},'message':{'text':text}}).encode()
                request=Request('https://graph.instagram.com/'+payload['api_version']+'/'+payload['account_id']+'/messages',data=body,method='POST',headers={'Authorization':'Bearer '+payload['access_token'],'Content-Type':'application/json'})
                with fetch(request,timeout=20) as response:receipt=json.load(response)
                if not receipt.get('message_id'):raise ValueError('No receipt.')
            state['send_state']='sent'
        except Exception:state['send_state']='review'
    state['checked_at']=clock();state['healthy']=healthy;state['reply_window_open']=bool(recipients)
    statefile.parent.mkdir(parents=True,exist_ok=True,mode=0o700);tmp=statefile.with_suffix('.tmp');tmp.write_text(json.dumps(state));tmp.chmod(0o600);tmp.replace(statefile)
    return {'ready':True,'healthy':healthy,'failures':state['failures'],'reply_window_open':bool(recipients),'last_notice':state.get('last_notice'),'send_state':state.get('send_state')}

if __name__=='__main__':
    root=Path.home();print(json.dumps(run(root/'reel-followup-backups',root/'.config/reel-followup/standby-alert.key',root/'.config/reel-followup/watchdog-status.json')))
