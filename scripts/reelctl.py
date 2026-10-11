#!/usr/bin/env python3
"""Agent-friendly campaign control over the private local dashboard API."""
import argparse,json,secrets,subprocess,sys,urllib.request,urllib.error
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))

def status(base,profile):
    request=urllib.request.Request(base+'/api/status',headers={'X-Reel-Account':profile})
    with urllib.request.urlopen(request,timeout=15) as response:return json.load(response)
def post(base,profile,path,data):
    nonce=status(base,profile)['nonce']
    req=urllib.request.Request(base+path,data=json.dumps(data).encode(),method='POST',
        headers={'Content-Type':'application/json','Origin':base,'X-Local-Token':nonce,'X-Reel-Account':profile})
    try:
        with urllib.request.urlopen(req,timeout=30) as response:return json.load(response)
    except urllib.error.HTTPError as error:
        value=json.load(error);raise ValueError(value.get('error','Request rejected.')) from None
def run():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url',default='http://localhost:3130');parser.add_argument('--account',default='default')
    sub=parser.add_subparsers(dest='command',required=True)
    sub.add_parser('status');sub.add_parser('accounts');sub.add_parser('selftest')
    service=sub.add_parser('service');service.add_argument('action',choices=['status','start','stop'])
    sub.add_parser('update')
    campaign=sub.add_parser('campaign');ops=campaign.add_subparsers(dest='operation',required=True)
    ops.add_parser('list')
    for action in ['pause','resume']:
        cmd=ops.add_parser(action);cmd.add_argument('id')
    add=ops.add_parser('add');add.add_argument('--name',required=True);add.add_argument('--keyword',required=True,action='append');add.add_argument('--link',required=True)
    add.add_argument('--no-follow',action='store_true');add.add_argument('--followup',default='Did the link help? Let us know!')
    add.add_argument('--delay',type=int,default=60)
    args=parser.parse_args()
    if args.command=='selftest':
        from scripts.selftest_pi import selftest
        return selftest()
    if args.command=='service':
        subprocess.run([sys.executable,str(ROOT/'scripts/pi-user-service.py'),args.action,'worker'],check=True);return
    if args.command=='update':
        if subprocess.check_output(['git','status','--porcelain'],cwd=ROOT).strip():raise ValueError('Commit or save local source edits before updating.')
        subprocess.run(['git','pull','--ff-only'],cwd=ROOT,check=True)
        subprocess.run([sys.executable,'-m','unittest','discover','-s','test','-p','test_*.py'],cwd=ROOT,check=True)
        subprocess.run([sys.executable,str(ROOT/'scripts/pi-user-service.py'),'stop','worker'],check=True)
        import time
        for _ in range(60):
            record=json.loads(subprocess.check_output([sys.executable,str(ROOT/'scripts/pi-user-service.py'),'status','worker']))
            if not record['supervisor_running'] and not record['process_running']:break
            time.sleep(.5)
        else:raise ValueError('Worker is still stopping; no second worker started.')
        subprocess.run([sys.executable,str(ROOT/'scripts/pi-user-service.py'),'start','worker'],check=True);return
    data=status(args.url,args.account);config=data['config']
    if args.command=='accounts':result=data['accounts']
    elif args.command=='status':
        result={'account':config.get('username'),'enabled':config['enabled'],'storage':data.get('storage'),'webhook':data['webhook'].get('state'),
            'archive':data['archive'].get('state'),'campaigns':[{'id':f['id'],'name':f['name'],'keywords':f['keywords'],'enabled':f['enabled']} for f in config['flows']],
            'jobs':data.get('workflow_stats',[])}
    elif args.operation=='list':result=config['flows']
    elif args.operation in ['pause','resume']:
        result=post(args.url,args.account,'/api/flows/toggle',{'id':args.id,'setting':'enabled','value':args.operation=='resume'})
    else:
        current=config['flows']
        if not config['verified']:
            current=[{**f,'enabled':False} for f in current]
        current.append({'id':secrets.token_hex(8),'name':args.name,'keywords':args.keyword,'enabled':False,
            'require_follow':not args.no_follow,'link_button':True,'link_url':args.link,
            'opening_text':'Follow this account and press Following 👇','follow_text':'Follow this account, then press Following 👇',
            'link_text':'Your link','button_text':'Open link','public_reply':True,'public_reply_text':'Sent you a message! Check your DMs.',
            'followup_enabled':False,'followup_delay_minutes':args.delay,'followup_text':args.followup})
        result=post(args.url,args.account,'/api/flows',{'flows':current})
        result['campaign_id']=current[-1]['id'];result['enabled']=False
    print(json.dumps(result,indent=2))
if __name__=='__main__':
    try:run()
    except (ValueError,urllib.error.URLError,subprocess.CalledProcessError) as error:
        print(str(error),file=sys.stderr);sys.exit(1)
