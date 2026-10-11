import unittest
from native.neon_http import NeonHTTP,decode,pg_value,ArchiveError

class NeonHTTPTests(unittest.TestCase):
    def test_boolean_and_json_rows_are_decoded_without_truthiness_errors(self):
        self.assertIs(decode('f',16),False);self.assertIs(decode('t',16),True)
        self.assertEqual(decode('{"state":"sent"}',3802),{'state':'sent'})
        self.assertEqual(decode('1791571000.5',1700),1791571000.5)
        self.assertIsNone(decode(None,16))
    def test_untrusted_text_stays_in_parameters_not_sql(self):
        db=NeonHTTP();requests=[]
        db.http=lambda payload:requests.append(payload) or {'fields':[{'name':'received_link','dataTypeID':16},{'name':'received_opening','dataTypeID':16}],'rows':[['f','f']]}
        value="a'; DROP TABLE x; --"
        db.request({'flow_contact_get':{'ig_account_id':'owner','recipient_id':value}})
        self.assertTrue(all(value not in query['query'] and query['params'][1]==value for query in requests))
    def test_pg_parameters_encode_null_boolean_and_quoted_arrays(self):
        self.assertIsNone(pg_value(None));self.assertEqual(pg_value(False),'false')
        self.assertEqual(pg_value(['a','b"c']),'{"a","b\\"c"}')
    def test_archive_record_batch_has_complete_parameterized_values(self):
        db=NeonHTTP();requests=[]
        db.http=lambda payload:requests.append(payload) or {'fields':[],'rows':[]}
        result=db.request({'records':[{'ig_account_id':'owner','conversation_id':'thread','record_type':'conversation','record_id':'thread','payload':{'state':'complete'}}]})
        self.assertEqual(result['saved'],1)
        self.assertNotIn('${',requests[0]['query'])
        self.assertIn('$7::jsonb,$8::jsonb,now()',requests[0]['query'])
        self.assertEqual(len(requests[0]['params']),8)
    def test_unknown_operations_are_rejected(self):
        with self.assertRaises(ArchiveError):NeonHTTP().request({'sql':'DELETE FROM users'})
    def test_query_result_types_remain_usable_for_durable_claims(self):
        db=NeonHTTP()
        db.http=lambda payload:{'fields':[{'name':'claimed','dataTypeID':16},{'name':'receipt','dataTypeID':3802}],
            'rows':[['f','{"message_id":"receipt"}']]}
        rows=db.query('flow_action_get',['owner','key'])
        self.assertIs(rows[0]['claimed'],False)
        self.assertEqual(rows[0]['receipt']['message_id'],'receipt')

if __name__=='__main__':unittest.main()
