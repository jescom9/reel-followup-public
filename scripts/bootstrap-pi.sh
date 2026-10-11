#!/usr/bin/env bash
set -euo pipefail
[[ "$(uname -s)" == Linux ]] || { echo 'Run this on the new Pi.' >&2; exit 1; }
cd "$(dirname "$0")/.."
python3 -c 'import sys; assert sys.version_info >= (3,10), "Python 3.10+ required"'
umask 077
if [[ ! -f .env ]]; then
  cp .env.pi.example .env
  python3 - <<'PY'
from pathlib import Path
import secrets
p=Path('.env');p.write_text(p.read_text().replace('IG_WEBHOOK_VERIFY_TOKEN=\n','IG_WEBHOOK_VERIFY_TOKEN='+secrets.token_hex(24)+'\n'))
PY
fi
chmod 600 .env
python3 - <<'PY'
from pathlib import Path
from native.profiles import private_write
from native.workflows import validate_flows
import json
path=Path('native/.local/config.json')
if not path.exists():
    draft={'id':'starter','name':'New flow','keywords':['INFO'],'enabled':False,
        'require_follow':True,'link_button':True,'link_url':'','opening_text':'Follow this account and press Following 👇',
        'follow_text':'Follow this account, then press Following 👇','link_text':'Your link','button_text':'Open link',
        'public_reply':True,'public_reply_text':'Sent you a message! Check your DMs.',
        'followup_enabled':False,'followup_delay_minutes':60,'followup_text':'Did the link help? Let us know!'}
    private_write(path,json.dumps({'enabled':False,'verified':False,'keyword':'INFO','workflow_mode':'manychat','flows':validate_flows([draft])}))
PY
python3 scripts/reelctl.py selftest
bash scripts/install-pi-user-worker.sh
python3 - <<'PY'
import time,urllib.request,urllib.error
for _ in range(40):
    try:
        with urllib.request.urlopen('http://localhost:3130/api/status',timeout=2) as response:
            if response.status==200:break
    except (urllib.error.URLError,TimeoutError):pass
    time.sleep(.5)
else:raise SystemExit('Worker did not become ready. Check native/.local/worker-service.log.')
PY
echo 'The local SQLite service is running; new accounts/campaigns start paused.'
echo 'Open a private SSH tunnel on your client:'
echo 'ssh -N -L 127.0.0.1:3130:127.0.0.1:3130 YOUR_USER@NEW_PI_IP'
echo 'Then open http://localhost:3130'
