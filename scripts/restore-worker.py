#!/usr/bin/env python3
"""Decrypt an encrypted worker snapshot into an EMPTY isolated recovery directory."""
import argparse,importlib.util,io,tarfile
from pathlib import Path
spec=importlib.util.spec_from_file_location('backup_worker',Path(__file__).with_name('backup-worker.py'));backup=importlib.util.module_from_spec(spec);spec.loader.exec_module(backup)

def restore(snapshot,key,output):
    report=backup.verify(snapshot.read_bytes(),key.read_bytes())
    if output.exists() and any(output.iterdir()):raise ValueError('Use an empty recovery directory.')
    output.mkdir(parents=True,exist_ok=True,mode=0o700)
    blob=snapshot.read_bytes();plain=backup.AESGCM(key.read_bytes()).decrypt(blob[5:17],blob[17:],backup.MAGIC)
    with tarfile.open(fileobj=io.BytesIO(plain),mode='r:gz') as archive:
        for member in archive:
            if not member.isfile():continue
            target=output/member.name
            if not target.resolve().is_relative_to(output.resolve()):raise ValueError('Invalid snapshot path.')
            target.parent.mkdir(parents=True,exist_ok=True,mode=0o700);target.write_bytes(archive.extractfile(member).read());target.chmod(0o600)
    return report

if __name__=='__main__':
    import json
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('snapshot',type=Path);p.add_argument('--key',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();print(json.dumps(restore(a.snapshot,a.key,a.output)))
