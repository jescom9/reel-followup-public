import json, tempfile, unittest
from unittest.mock import patch
from native.app import App, Store, MetaError
from native.followup import PHRASE, matches, preflight, deliver

NOW = 1_800_000_000
def message(mid, sender, stamp, text='', template=None):
    from datetime import datetime, timezone
    result = {'id':mid,'from':{'id':sender},'to':{'data':[{'id':'customer' if sender=='business' else 'business'}]},
        'created_time':datetime.fromtimestamp(stamp,timezone.utc).isoformat(),'message':text}
    if template: result['attachments'] = {'data':[{'generic_template':{'title':template}}]}
    return result

TARGET = {'conversation_id':'thread','source_message_id':'link','recipient_id':'customer','username':'customer'}
CONFIG = {'account_id':'business','username':'jescojm'}

class API:
    def __init__(self,pages,error=None): self.pages,self.error,self.calls,self.sends = list(pages),error,[],[]
    def call(self,method,path,**query):
        self.calls.append((method,path,query));page=self.pages.pop(0)
        return {'messages':page} if path=='thread' else page
    def send(self,recipient,text):
        self.sends.append((recipient,text))
        if self.error: raise self.error
        return {'message_id':'receipt','recipient_id':'customer'}

class DB:
    def __init__(self): self.requests=[];self.claimed=False
    def request(self,value):
        self.requests.append(value)
        if 'claim' in value:
            if self.claimed: return {'claimed':False}
            self.claimed=True;return {'claimed':True}
        return {'recorded':True}

class FollowupTests(unittest.TestCase):
    def test_card_titles_match_and_inbound_quotes_do_not(self):
        self.assertTrue(matches(message('link','business',NOW,template=PHRASE),'business'))
        self.assertFalse(matches(message('link','customer',NOW,text=PHRASE),'business'))
    def test_changed_latest_message_prevents_send(self):
        api=API([{'data':[message('reply','customer',NOW,text='Thank you')]}]);db=DB()
        self.assertEqual(deliver(api,db,None,TARGET,CONFIG,lambda:NOW),'changed')
        self.assertEqual(api.sends,[]);self.assertEqual(db.requests,[])
    def test_recent_outbound_does_not_reopen_expired_window(self):
        api=API([{'data':[message('link','business',NOW-5,template=PHRASE),message('in','customer',NOW-86401)]}])
        self.assertEqual(preflight(api,TARGET,'business',NOW),'window_closed')
    def test_recipient_mismatch_prevents_send(self):
        latest=message('link','business',NOW-5,template=PHRASE);latest['to']={'data':[{'id':'other'}]}
        api=API([{'data':[latest]}])
        self.assertEqual(preflight(api,TARGET,'business',NOW),'changed')
    def test_preflight_pages_inside_message_field_expansion(self):
        api=API([{'data':[message('link','business',NOW-5,template=PHRASE)],'paging':{'next':'next','cursors':{'after':'cursor'}}},
            {'data':[message('in','customer',NOW-10)]}])
        self.assertEqual(preflight(api,TARGET,'business',NOW),'ready')
        self.assertEqual(api.calls[1][1],'thread');self.assertIn('.after(cursor)',api.calls[1][2]['fields'])
        self.assertNotIn('after',api.calls[1][2])
    def test_send_is_claimed_once_and_archived_after_receipt(self):
        page={'data':[message('link','business',NOW-5,template=PHRASE),message('in','customer',NOW-10)]}
        db=DB()
        with tempfile.TemporaryDirectory() as folder:
            store=Store(folder);api=API([page,page,page])
            self.assertEqual(deliver(api,db,store,TARGET,CONFIG,lambda:NOW),'sent')
            self.assertEqual(deliver(api,db,store,TARGET,CONFIG,lambda:NOW),'already_recorded')
            self.assertEqual(deliver(api,db,store,TARGET,CONFIG,lambda:NOW,retry_rejected=True),'already_recorded')
            self.assertEqual(len(api.sends),1)
            self.assertEqual(db.requests[1]['finish']['state'],'sent')
            self.assertEqual(db.requests[2]['records'][0]['record_id'],'receipt')
            store.db.close()
    def test_unknown_send_is_held_for_review_without_retry(self):
        page={'data':[message('link','business',NOW-5,template=PHRASE),message('in','customer',NOW-10)]}
        db=DB()
        with tempfile.TemporaryDirectory() as folder:
            store=Store(folder);api=API([page,page,page],MetaError('Network result unknown.'))
            self.assertEqual(deliver(api,db,store,TARGET,CONFIG,lambda:NOW),'review')
            self.assertEqual(deliver(api,db,store,TARGET,CONFIG,lambda:NOW),'already_recorded')
            self.assertEqual(deliver(api,db,store,TARGET,CONFIG,lambda:NOW,retry_rejected=True),'already_recorded')
            self.assertEqual(len(api.sends),1);self.assertEqual(db.requests[1]['finish']['state'],'review')
            store.db.close()

class ArchiveDB:
    def __init__(self):self.inputs=[]
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def request(self,value):
        self.inputs.append(value)
        return {'manifest':[]} if value.get('manifest') else {'saved':len(value.get('records',[]))}

class ArchivePaginationTest(unittest.TestCase):
    def test_archive_advances_cursor_inside_messages_expansion(self):
        process=ArchiveDB()
        api=API([{'data':[{'id':'thread','updated_time':'2026-10-06T00:00:00Z','participants':{'data':[]}}]},
            {'data':[message('first','business',NOW)],'paging':{'next':'next','cursors':{'after':'cursor'}}},
            {'data':[message('older','customer',NOW-10)]}])
        with tempfile.TemporaryDirectory() as folder,patch('native.app.NeonBridge',return_value=process),patch('native.app.Graph',return_value=api),patch('native.app.save_instagram_env'):
            app=App(folder);app.store.config.update(verified=True,account_id='business',access_token='test-token')
            app.sync_chat_history();app.store.db.close()
        self.assertEqual(api.calls[1][1],'thread');self.assertIn('.after(cursor)',api.calls[2][2]['fields'])
        self.assertNotIn('after',api.calls[2][2])
        records=[r for item in process.inputs for r in item.get('records',[]) if r['record_type']=='message']
        self.assertEqual([r['record_id'] for r in records],['first','older'])

if __name__=='__main__': unittest.main()
