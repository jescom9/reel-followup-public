"""Disposable Pi-local end-to-end test; no credentials, cloud DB or DMs."""
import hashlib,hmac,json,tempfile,threading,time,urllib.request
from pathlib import Path
from datetime import datetime,timezone,timedelta

def selftest():
    from native.app import App,Handler,ThreadingHTTPServer
    from native.storage import StorageBridge
    class FakeMeta:
        sends=[]
        def __init__(self,config):pass
        def call(self,method,path,data=None,**query):
            if path=='media':return {'owner':{'id':'101'},'media_product_type':'REELS'}
            if path=='comment':return {'timestamp':(datetime.now(timezone.utc)-timedelta(seconds=2)).isoformat()}
            if path=='202':return {'is_user_follow_business':True}
            return {'id':'public-test-receipt'}
        def send_button(self,*args,**kwargs):return {'message_id':'opening-test','recipient_id':'202'}
        def send(self,recipient,text):self.sends.append(text);return {'message_id':'link-test','recipient_id':'202'}
        def send_link(self,*args):self.sends.append('link');return {'message_id':'link-test','recipient_id':'202'}
    with tempfile.TemporaryDirectory(prefix='reel-local-selftest-') as folder:
        env=Path(folder)/'.env';env.write_text('REEL_STORAGE=sqlite\nIG_APP_SECRET=selftest-only\n')
        app=App(Path(folder)/'data',env)
        app.store.config.update(account_id='101',username='test',verified=True,enabled=True,workflow_mode='manychat',
            keyword='INFO',campaign_started_at=time.time()-30)
        app.engine.workflows.factory=FakeMeta
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler);server.app=app;server.ingress=True
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        def deliver(body):
            raw=json.dumps(body).encode();signature='sha256='+hmac.new(b'selftest-only',raw,hashlib.sha256).hexdigest()
            req=urllib.request.Request('http://127.0.0.1:'+str(server.server_port)+'/webhook',data=raw,method='POST',headers={'Content-Type':'application/json','X-Hub-Signature-256':signature})
            with urllib.request.urlopen(req,timeout=5) as response:assert response.status==200
            assert app.engine.run_one()
        try:
            deliver({'object':'instagram','entry':[{'id':'101','changes':[{'field':'comments','value':{'id':'comment','text':'INFO','from':{'id':'303'},'media':{'id':'media'}}}]}]})
            click={'object':'instagram','entry':[{'id':'101','messaging':[{'sender':{'id':'202'},'recipient':{'id':'101'},'timestamp':int(time.time()*1000),'postback':{'mid':'button','payload':'BF_FOLLOW','title':'Following'}}]}]}
            deliver(click)
            assert len(FakeMeta.sends)==1,[(r['state'],r['detail']) for r in app.store.execute('SELECT state,detail FROM events')]
            raw=json.dumps(click).encode();req=urllib.request.Request('http://127.0.0.1:'+str(server.server_port)+'/webhook',data=raw,method='POST',headers={'X-Hub-Signature-256':'sha256='+hmac.new(b'selftest-only',raw,hashlib.sha256).hexdigest()})
            urllib.request.urlopen(req,timeout=5).close();assert not app.engine.run_one();assert len(FakeMeta.sends)==1
            with StorageBridge(env,Path(folder)/'data') as db:
                claim=db.request({'flow_action_claim':{'ig_account_id':'101','action_id':'mc-opening:v1:media:303'}})
                assert not claim['claimed'] and claim['state']=='sent'
            print(json.dumps({'result':'passed','database':'SQLite','signed_webhook':'accepted','follower_link':'simulated once',
                'duplicate_delivery':'ignored','restart_receipt':'preserved','external_messages_sent':0,'Neon_required':False},indent=2))
        finally:server.shutdown();server.server_close();app.store.db.close()
