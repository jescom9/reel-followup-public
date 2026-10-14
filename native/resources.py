"""Sampled service health, host capacity and dated cloud-plan usage."""
import json,os,shutil,socket,threading,time
from pathlib import Path
from urllib.request import urlopen
try:
    from .profiles import read_values
    from .neon_http import NeonHTTP
except ImportError:
    from profiles import read_values
    from neon_http import NeonHTTP

class Resources:
    def __init__(self,registry,clock=time.time):
        self.registry,self.clock=registry,clock;self.cached=None;self.neon_at=0;self.neon_ok=None;self.lock=threading.RLock()
    def report(self):
        with self.lock:
            if self.cached and self.clock()-self.cached['checked_at']<60:return self.cached
            return self.sample()
    def sample(self):
        root=self.registry.project;state=root/'native/.local';now=self.clock();alerts=[];mem={}
        try:
            for line in Path('/proc/meminfo').read_text().splitlines():
                key,value=line.split(':',1);mem[key]=int(value.split()[0])*1024
        except (OSError,ValueError):pass
        disk=shutil.disk_usage(root);cores=os.cpu_count() or 1;load=os.getloadavg()[0]/cores
        service=state/'worker-service.json';w=json.loads(service.read_text()) if service.exists() else {}
        def process(pid,expected):
            try:return expected in Path('/proc/'+str(int(pid))+'/cmdline').read_bytes().decode()
            except (OSError,ValueError,TypeError):return False
        worker={'running':process(w.get('process_pid'),'native/app.py'),'supervisor_running':process(w.get('supervisor_pid'),'pi-user-service.py')}
        services=[]
        started=time.monotonic()
        try:
            with socket.create_connection(('127.0.0.1',3131),timeout=3):pass
            ok=True
        except OSError:ok=False
        services.append({'name':'Pi webhook bridge','ok':ok,'latency_ms':round((time.monotonic()-started)*1000),'note':'Worker ingress unavailable.'})
        started=time.monotonic()
        try:
            with urlopen('https://reelfollowups.app/',timeout=5) as response:ok=response.status==200
        except Exception:ok=False
        services.append({'name':'Website','ok':ok,'latency_ms':round((time.monotonic()-started)*1000),'note':'Website check failed from this Pi.'})
        values=read_values(root/'.env');neon_file=state/'neon-usage.json';n=json.loads(neon_file.read_text()) if neon_file.exists() else {}
        n.update(role='Cloud archive and delivery receipts; local jobs and encrypted credentials',stale=not n.get('checked_at') or now-n['checked_at']>86400)
        if values.get('REEL_FOLLOWUP_DATABASE_URL') and now-self.neon_at>=3600:
            started=time.monotonic()
            try:
                with NeonHTTP(root/'.env') as db:
                    size=db.http({'query':'SELECT pg_database_size(current_database()) AS size','params':[]})
                    n['live_database_bytes']=int(size['rows'][0][0]);self.neon_ok=True
            except Exception:self.neon_ok=False
            self.neon_at=now;self.neon_latency=round((time.monotonic()-started)*1000);self.neon_size=n.get('live_database_bytes')
        n['live_database_bytes']=getattr(self,'neon_size',None)
        services.append({'name':'Neon SQL · hourly probe','ok':self.neon_ok is True,'latency_ms':getattr(self,'neon_latency',0),'note':'Neon SQL unavailable or not configured.','checked_at':self.neon_at})
        bfile=state/'backup-status.json';b=json.loads(bfile.read_text()) if bfile.exists() else {}
        backup={'host':values.get('REEL_BACKUP_SSH_HOST',''),'last_backup_at':b.get('last_backup_at',0),'restore_verified':bool(b.get('restore_verified') and b.get('push_ok')),'worker_running':b.get('worker_running',False),'disk_free':b.get('disk_free'),'interval_hours':b.get('interval_hours',4),'checked_at':b.get('last_backup_at',0),'reachable':False,'cpu_cores':b.get('cpu_cores'),'load_per_core':b.get('load_per_core'),'memory_available':b.get('memory_available'),'memory_total':b.get('memory_total'),'disk_total':b.get('disk_total'),'watchdog':b.get('watchdog',{}),'alert_watchdog_synced':b.get('alert_watchdog_synced',False)}
        if backup['host']:
            try:
                with socket.create_connection((backup['host'],22),timeout=3):pass
                backup['reachable']=True
            except OSError:pass
        if load>1.5:alerts.append('CPU load exceeds 1.5 per core.')
        if mem.get('MemAvailable',1)/max(1,mem.get('MemTotal',1))<.15:alerts.append('Less than 15% of RAM remains available.')
        if disk.free/disk.total<.15:alerts.append('Less than 15% of main Pi disk space remains free.')
        if not worker['running']:alerts.append('Main worker is not running.')
        for s in services:
            if not s['ok']:alerts.append(s['name']+': availability check failed.')
        if not backup['last_backup_at'] or now-backup['last_backup_at']>8*3600:alerts.append('No successful standby backup in the last eight hours.')
        if backup['worker_running']:alerts.append('Standby automation worker is running; inspect duplicate-delivery risk.')
        if backup['host'] and not backup['reachable']:alerts.append('Backup Pi SSH is unreachable.')
        if n.get('stale'):alerts.append('Neon monthly usage snapshot is older than 24 hours; check the console for current quota usage.')
        for used,limit,label in [('storage_bytes','storage_limit_bytes','storage'),('compute_hours','compute_limit_hours','compute'),('transfer_bytes','transfer_limit_bytes','transfer')]:
            if n.get(used) is not None and n.get(limit) and n[used]/n[limit]>=.8:alerts.append('Neon '+label+' exceeds 80% of the recorded free-plan quota.')
        if n.get('compute_hours') and n.get('period_start') and n.get('period_end') and n.get('checked_at'):
            elapsed=max(1,n['checked_at']-n['period_start']);projected=n['compute_hours']*(n['period_end']-n['period_start'])/elapsed
            n['projected_compute_hours']=round(projected,1)
            if projected>n.get('compute_limit_hours',100):alerts.append('Shared Neon compute is projected to exceed this month’s free allowance at the sampled rate.')
        pending=0;review=0
        for row in self.registry.listing():
            if not row['verified']:continue
            found=self.registry.find_account(row['account_id'])
            if not found:continue
            try:
                store=found[1].store
                pending+=store.execute("SELECT count(*) n FROM events WHERE state IN ('pending','processing') AND created<?",(now-120,))[0]['n']
                review+=store.execute("SELECT count(*) n FROM events WHERE state='review' AND created>?",(now-600,))[0]['n']
            except Exception:continue
        if pending>20:alerts.append(str(pending)+' events have waited more than two minutes.')
        if review>5:alerts.append(str(review)+' new events require review in the last ten minutes.')
        result={'checked_at':now,'pi':{'hostname':socket.gethostname(),'cpu_cores':cores,'load_per_core':load,'memory_available':mem.get('MemAvailable'),'memory_total':mem.get('MemTotal'),'disk_free':disk.free,'disk_total':disk.total,'database_bytes':sum(p.stat().st_size for p in state.rglob('*.sqlite'))},'worker':worker,'services':services,'neon':n,'backup':backup,'recovery':{'summary':'The supervisor restarts the worker after a crash. A separate Pi checks primary availability every two minutes and stores encrypted four-hour snapshots. Recovery begins paused; the standby does not send campaign messages automatically.','steps':['Confirm the main worker is offline before moving automation to another host.','Restore the newest encrypted snapshot with its separately stored recovery key into an empty directory.','Check SQLite integrity, token-vault keys and the Neon connection. All restored accounts remain paused.','Review uncertain deliveries and events since the backup before resuming accounts. Restore credentials and configure the replacement webhook route.']},'capacity':{'alerts':alerts,'note':'Host and availability samples are current. Monthly Neon compute and transfer use the dated operator snapshot, not live billing. The database is shared with Bikefitting; usage is project-wide. Backup worker status reflects the latest upload receipt. A four-hour schedule is a target, not a guaranteed recovery point.'}}
        self.cached=result;return result
    def run(self):
        while self.registry.running:
            try:
                with self.lock:report=self.sample()
                self.registry.service_alerts.check(report)
            except Exception:pass
            # Interruptible sleep, independent of campaign worker threads.
            for _ in range(120):
                if not self.registry.running:return
                time.sleep(1)
