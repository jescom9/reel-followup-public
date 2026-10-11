import tempfile,unittest,sqlite3
from pathlib import Path
from native.token_vault import TokenVault

class VaultTests(unittest.TestCase):
    def test_ciphertext_survives_restart_without_plaintext_in_database(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault=TokenVault(tmp);vault.put('very-private-test-access-token','123','456',2000000000)
            self.assertNotIn(b'very-private-test-access-token',vault.path.read_bytes())
            self.assertEqual(TokenVault(tmp).get()['access_token'],'very-private-test-access-token')
            self.assertEqual(vault.path.stat().st_mode&0o777,0o600);self.assertEqual(vault.key_file.stat().st_mode&0o777,0o600)
    def test_tampering_or_using_another_workspace_key_fails_closed(self):
        with tempfile.TemporaryDirectory() as one,tempfile.TemporaryDirectory() as two:
            a,b=TokenVault(one),TokenVault(two);a.put('private-token')
            with a.connect() as db:encrypted=db.execute('SELECT encrypted FROM credentials').fetchone()[0]
            with b.connect() as db:db.execute('INSERT INTO credentials VALUES(?,?,?)',('instagram',encrypted,0))
            with self.assertRaises(ValueError):b.get()
            with a.connect() as db:db.execute('UPDATE credentials SET encrypted=?',(encrypted[:-2]+b'XX',))
            with self.assertRaises(ValueError):a.get()
