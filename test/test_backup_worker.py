import importlib.util,json,sqlite3,tempfile,unittest
from pathlib import Path
spec=importlib.util.spec_from_file_location('backup_worker',Path(__file__).resolve().parents[1]/'scripts/backup-worker.py');backup=importlib.util.module_from_spec(spec);spec.loader.exec_module(backup)

class BackupTests(unittest.TestCase):
    def test_snapshot_is_encrypted_restores_integrity_and_pauses_every_account(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);state=root/'native/.local/profiles/ig-example';state.mkdir(parents=True);(root/'.env').write_text('SECRET=private-test-only')
            (state/'config.json').write_text(json.dumps({'enabled':True,'username':'example'}))
            with sqlite3.connect(state/'events.sqlite') as db:db.execute('CREATE TABLE receipt(id TEXT)');db.execute("INSERT INTO receipt VALUES('sent')")
            file,report=backup.snapshot(root);self.assertTrue(report['restore_verified']);self.assertEqual(report['databases_verified'],1);self.assertNotIn(b'private-test-only',file.read_bytes());self.assertEqual(file.stat().st_mode&0o777,0o600)
            self.assertTrue(backup.verify(file.read_bytes(),(root/'native/.local/.backup-key').read_bytes())['restored_accounts_paused'])
            broken=bytearray(file.read_bytes());broken[-1]^=1
            with self.assertRaises(Exception):backup.verify(bytes(broken),(root/'native/.local/.backup-key').read_bytes())
            self.assertTrue(json.loads((state/'config.json').read_text())['enabled'])

if __name__=='__main__':unittest.main()
