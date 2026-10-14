#!/usr/bin/env python3
"""Forced SSH command: accept only an encrypted backup into a dedicated folder."""
import hashlib,json,os,secrets,shutil,sys,time
from pathlib import Path

folder=Path.home()/'reel-followup-backups';folder.mkdir(mode=0o700,exist_ok=True)
tmp=folder/('.incoming-'+secrets.token_hex(8));size=0;digest=hashlib.sha256()
try:
    with tmp.open('wb') as out:
        while True:
            chunk=sys.stdin.buffer.read(1048576)
            if not chunk:break
            if size==0 and not chunk.startswith((b'RFBA1',b'RFAL1')):raise ValueError('Invalid encrypted snapshot.')
            size+=len(chunk)
            if size>512*1048576:raise ValueError('Snapshot exceeds receiver capacity.')
            out.write(chunk);digest.update(chunk)
    if size<33:raise ValueError('Incomplete snapshot.')
    tmp.chmod(0o600);alert=tmp.open('rb').read(5)==b'RFAL1';name='reel-'+time.strftime('%Y%m%dT%H%M%SZ',time.gmtime())+'-'+secrets.token_hex(3)+'.rfbackup';name='alerts.rfalert' if alert else name;tmp.replace(folder/name)
    disk=shutil.disk_usage(folder);running=False
    state=Path.home()/'reel-followup/native/.local/worker-service.json'
    if state.exists():
        try:
            pid=json.loads(state.read_text()).get('process_pid');cmdline=Path('/proc/'+str(int(pid))+'/cmdline').read_bytes();running=b'native/app.py' in cmdline
        except (OSError,TypeError,ValueError):pass
    memory={}
    try:
        for line in Path('/proc/meminfo').read_text().splitlines():
            key,value=line.split(':',1);memory[key]=int(value.split()[0])*1024
    except (OSError,ValueError):pass
    watchdogfile=Path.home()/'.config/reel-followup/watchdog-status.json'
    watchdog=json.loads(watchdogfile.read_text()) if watchdogfile.exists() else {}
    watchdog={k:v for k,v in watchdog.items() if k in ('checked_at','healthy','failures','reply_window_open','last_notice','send_state')}
    print(json.dumps({'stored_file':name,'sha256':digest.hexdigest(),'size_bytes':size,'received_at':time.time(),'disk_free':disk.free,'disk_total':disk.total,'worker_running':running,'cpu_cores':os.cpu_count(),'load_per_core':os.getloadavg()[0]/(os.cpu_count() or 1),'memory_available':memory.get('MemAvailable'),'memory_total':memory.get('MemTotal'),'watchdog':watchdog}))
    for path in sorted(folder.glob('reel-*.rfbackup'),key=lambda p:p.stat().st_mtime)[:-12]:path.unlink()
finally:
    if tmp.exists():tmp.unlink()
