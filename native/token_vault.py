"""Authenticated encryption for Instagram tokens in owner-only local SQLite."""
import json,os,sqlite3,time
from pathlib import Path
from contextlib import contextmanager
from cryptography.fernet import Fernet,InvalidToken

class TokenVault:
    def __init__(self,folder):
        self.folder=Path(folder);self.folder.mkdir(parents=True,exist_ok=True,mode=0o700)
        self.key_file=self.folder/'.token-vault-key'
        if not self.key_file.exists():
            descriptor=os.open(self.key_file,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
            with os.fdopen(descriptor,'wb') as output:output.write(Fernet.generate_key())
        os.chmod(self.key_file,0o600)
        self.cipher=Fernet(self.key_file.read_bytes())
        self.path=self.folder/'credentials.sqlite'
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS credentials (slot TEXT PRIMARY KEY,encrypted BLOB NOT NULL,updated REAL NOT NULL)')
        os.chmod(self.path,0o600)
    @contextmanager
    def connect(self):
        db=sqlite3.connect(self.path,timeout=30)
        try:
            with db:yield db
        finally:db.close()
    def put(self,token,account_id='',app_id='',expires_at=0):
        if not isinstance(token,str) or not token or len(token)>8192 or any(c in token for c in '\r\n\x00'):raise ValueError('Invalid account credential.')
        value={'slot':'instagram','access_token':token,'account_id':str(account_id),'app_id':str(app_id),'expires_at':float(expires_at or 0)}
        encrypted=self.cipher.encrypt(json.dumps(value).encode())
        with self.connect() as db:db.execute('INSERT INTO credentials VALUES(?,?,?) ON CONFLICT(slot) DO UPDATE SET encrypted=excluded.encrypted,updated=excluded.updated',('instagram',encrypted,time.time()))
    def get(self):
        with self.connect() as db:row=db.execute("SELECT encrypted FROM credentials WHERE slot='instagram'").fetchone()
        if not row:return None
        try:
            value=json.loads(self.cipher.decrypt(row[0]))
            if value.get('slot')!='instagram':raise ValueError()
            return value
        except (InvalidToken,ValueError,TypeError):raise ValueError('Credential vault could not be unlocked. Restore its matching private key.') from None
