import json,unittest
from types import SimpleNamespace
from native.hosted_media import list_media,verify_new_selections

class ReelPreviewTests(unittest.TestCase):
    def setUp(self):
        self.app=SimpleNamespace(store=SimpleNamespace(config={'account_id':'123','account_aliases':['456'],'verified':True,'access_token':'private-account-token'}))
        self.calls=[]
    def factory(self,config):
        def call(method,path,**query):
            self.calls.append((method,path,query,config['account_id']))
            if path=='123/media':return {'data':[
                {'id':'111','media_product_type':'REELS','caption':'Your Reel','permalink':'https://www.instagram.com/reel/abc/?utm=source','thumbnail_url':'https://scontent.cdninstagram.com/photo.jpg','comments_count':4,'timestamp':'2026-10-13T09:00:00Z'},
                {'id':'222','media_product_type':'FEED','permalink':'https://www.instagram.com/p/feed/'},
                {'id':'333','media_product_type':'REELS','permalink':'javascript:alert(1)','thumbnail_url':'https://attacker.test/image.jpg'}],
                'paging':{'next':'https://graph.instagram.com/?access_token=private-account-token','cursors':{'after':'opaque_cursor=='}}}
            return {'id':path,'owner':{'id':'999' if path=='999' else '123'},'media_product_type':'REELS'}
        return SimpleNamespace(call=call)
    def test_previews_use_the_owned_account_only_and_never_return_graph_tokens(self):
        result=list_media(self.app,self.factory,{'account_id':'999'},now=10)
        self.assertEqual(self.calls[0][1],'123/media');self.assertEqual([r['id'] for r in result['rows']],['111'])
        self.assertEqual(result['rows'][0]['permalink'],'https://www.instagram.com/reel/abc/')
        self.assertEqual(result['rows'][0]['comments_count'],4)
        self.assertNotIn('private-account-token',json.dumps(result));self.assertEqual(result['next_cursor'],'opaque_cursor==')
        list_media(self.app,self.factory,{},now=20);self.assertEqual(len(self.calls),1)
        list_media(self.app,self.factory,{'refresh':True},now=21);self.assertEqual(len(self.calls),2)
    def test_pagination_is_a_cursor_not_a_client_selected_graph_url(self):
        for bad in ['https://attacker.test/','a\nheader',False,'x'*4097]:
            with self.assertRaises(ValueError):list_media(self.app,self.factory,{'after':bad})
        list_media(self.app,self.factory,{'after':'cursor=='},now=1)
        self.assertEqual(self.calls[0][2]['after'],'cursor==')
        self.app.store.config['verified']=False
        with self.assertRaisesRegex(ValueError,'Reconnect'):list_media(self.app,self.factory,{})
    def test_foreign_reels_are_rejected_and_known_owned_previews_are_reused(self):
        list_media(self.app,self.factory,{},now=1)
        verify_new_selections(self.app,self.factory,[{'id':'f','media_scope':'selected','media_ids':['111']}],[])
        self.assertEqual(len(self.calls),1)
        with self.assertRaisesRegex(ValueError,'owned'):verify_new_selections(self.app,self.factory,[{'id':'f','media_scope':'selected','media_ids':['999']}],[])
        prior=[{'id':'f','media_scope':'selected','media_ids':['444']}]
        self.calls.clear();verify_new_selections(self.app,self.factory,prior,prior);self.assertEqual(self.calls,[])
