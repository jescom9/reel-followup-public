#!/usr/bin/env python3
"""Encrypted SQLite snapshots, integrity rehearsal and a restricted standby upload."""
import argparse,hashlib,io,json,os,secrets,sqlite3,subprocess,tarfile,tempfile,time
from pathlib import Path
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

ROOT=Path(__file__).resolve().parent.parent
MAGIC=b'RFBA1'


def verify(blob,key):
    if not blob.startswith(MAGIC):raise ValueError('Invalid backup format.')
    plain=AESGCM(key).decrypt(blob[5:17],blob[17:],MAGIC)
    with tempfile.TemporaryDirectory() as tmp:
        folder=Path(tmp)
        with tarfile.open(fileobj=io.BytesIO(plain),mode='r:gz') as archive:
            for member in archive:
                if not member.isfile():continue
                target=folder/member.name
                if not target.resolve().is_relative_to(folder.resolve()):raise ValueError('Invalid backup path.')
                target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(archive.extractfile(member).read())
        checked=0
        for path in folder.rglob('*.sqlite'):
            with sqlite3.connect('file:'+str(path)+'?mode=ro',uri=True) as db:
                if db.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('Backup database integrity failed.')
            checked+=1
        for path in folder.rglob('config.json'):
            if json.loads(path.read_text()).get('enabled'):raise ValueError('Recovery snapshots must start paused.')
        manifest=json.loads((folder/'manifest.json').read_text())
        return {'databases_verified':checked,'created_at':manifest['created_at'],'restore_verified':True,'restored_accounts_paused':True}


def snapshot(project):
    project=Path(project);state=project/'native/.local';state.mkdir(parents=True,exist_ok=True)
    keyfile=state/'.backup-key'
    if not keyfile.exists():keyfile.write_bytes(secrets.token_bytes(32));keyfile.chmod(0o600)
    key=keyfile.read_bytes();created=time.time();payload=io.BytesIO();files=[]
    with tempfile.TemporaryDirectory() as tmp:
        temp=Path(tmp)
        with tarfile.open(fileobj=payload,mode='w:gz') as archive:
            candidates=[p for p in state.rglob('*') if p.is_file() and (p.suffix=='.sqlite' or p.name in ('config.json','.env','.token-vault-key')) and 'backups' not in p.relative_to(state).parts]
            if (project/'.env').exists():candidates.append(project/'.env')
            for index,path in enumerate(candidates):
                name=str(path.relative_to(project));copy=temp/str(index)
                if path.suffix=='.sqlite':
                    with sqlite3.connect('file:'+str(path)+'?mode=ro',uri=True) as source,sqlite3.connect(copy) as destination:source.backup(destination)
                elif path.name=='config.json':
                    c=json.loads(path.read_text());c['enabled']=False;copy.write_text(json.dumps(c))
                else:copy.write_bytes(path.read_bytes())
                archive.add(copy,arcname=name,recursive=False);files.append(name)
            manifest={'created_at':created,'files':files,'restored_accounts_paused':True}
            value=json.dumps(manifest).encode();info=tarfile.TarInfo('manifest.json');info.size=len(value);info.mode=0o600;archive.addfile(info,io.BytesIO(value))
    nonce=secrets.token_bytes(12);blob=MAGIC+nonce+AESGCM(key).encrypt(nonce,payload.getvalue(),MAGIC)
    report=verify(blob,key);report.update(size_bytes=len(blob),sha256=hashlib.sha256(blob).hexdigest())
    out=state/'backups';out.mkdir(mode=0o700,exist_ok=True);path=out/('reel-'+time.strftime('%Y%m%dT%H%M%SZ',time.gmtime(created))+'-'+secrets.token_hex(3)+'.rfbackup');path.write_bytes(blob);path.chmod(0o600)
    return path,report


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--project',type=Path,default=ROOT);parser.add_argument('--push',action='store_true');parser.add_argument('--verify',type=Path);args=parser.parse_args()
    state=args.project/'native/.local'
    if args.verify:print(json.dumps(verify(args.verify.read_bytes(),(state/'.backup-key').read_bytes())));return
    path,report=snapshot(args.project);report.update(local_snapshot_at=report['created_at'],last_backup_at=0,push_ok=False,interval_hours=4)
    if args.push:
        from sys import path as search_path
        search_path.insert(0,str(args.project))
        from native.profiles import read_values
        env=read_values(args.project/'.env');host=env.get('REEL_BACKUP_SSH_HOST','');user=env.get('REEL_BACKUP_SSH_USER','pi')
        if not host:raise ValueError('Configure the standby backup SSH host.')
        command=['ssh','-T','-o','BatchMode=yes','-o','StrictHostKeyChecking=yes','-o','ConnectTimeout=8','-o','UserKnownHostsFile='+str(state/'backup_known_hosts'),'-i',str(state/'.backup-push-key'),user+'@'+host,'receive-reel-backup']
        sent=subprocess.run(command,input=path.read_bytes(),capture_output=True,timeout=120)
        if sent.returncode:report['error']='Encrypted standby upload failed. Local snapshot retained.'
        else:
            receipt=json.loads(sent.stdout)
            if receipt.get('sha256')!=report['sha256']:raise ValueError('Standby backup checksum differs.')
            report.update(receipt,push_ok=True,last_backup_at=report['created_at'],host=host,worker_running=receipt.get('worker_running',False))
            # Standby receives only the inbox bot credential for independent outage replies,
            # not the other accounts' vault keys or the full backup decryption key.
            from cryptography.fernet import Fernet
            from native.token_vault import TokenVault
            alertkey=state/'.standby-alert-key'
            if not alertkey.exists():alertkey.write_bytes(Fernet.generate_key());alertkey.chmod(0o600)
            for configfile in (state/'profiles').glob('ig-*/config.json'):
                config=json.loads(configfile.read_text())
                if not config.get('verified') or config.get('username','').casefold()!=env.get('REEL_CAMPAIGN_SETUP_USERNAME','').casefold():continue
                with sqlite3.connect('file:'+str(configfile.parent/'events.sqlite')+'?mode=ro',uri=True) as db:
                    db.row_factory=sqlite3.Row
                    try:subscribers=[dict(r) for r in db.execute('SELECT sender_id,inbound_at FROM service_alert_subscription')]
                    except sqlite3.OperationalError:subscribers=[]
                if not subscribers:continue
                credential=TokenVault(configfile.parent).get()
                if not credential:continue
                payload={'account_id':config['account_id'],'api_version':config.get('api_version','v22.0'),'access_token':credential['access_token'],'subscribers':subscribers,'created_at':time.time(),'health_url':env.get('REEL_STANDBY_HEALTH_URL','')}
                encrypted=b'RFAL1'+Fernet(alertkey.read_bytes()).encrypt(json.dumps(payload).encode())
                result=subprocess.run(command,input=encrypted,capture_output=True,timeout=120)
                report['alert_watchdog_synced']=result.returncode==0

    status=state/'backup-status.json';old=json.loads(status.read_text()) if status.exists() else {}
    if not report['push_ok'] and old.get('last_backup_at'):report['last_backup_at']=old['last_backup_at']
    temporary=status.with_suffix('.tmp');temporary.write_text(json.dumps(report));temporary.chmod(0o600);temporary.replace(status)
    # Retention covers only this helper's generated local encrypted snapshots.
    for old_path in sorted((state/'backups').glob('reel-*.rfbackup'),key=lambda p:p.stat().st_mtime)[:-12]:old_path.unlink()
    print(json.dumps({k:report[k] for k in ('restore_verified','databases_verified','restored_accounts_paused','push_ok','size_bytes','last_backup_at')}))
    if args.push and not report['push_ok']:raise SystemExit(1)

if __name__=='__main__':main()
