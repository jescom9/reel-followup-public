#!/usr/bin/env bash
# Configure the signed credential/event bridge on an existing Pi installation.
set -euo pipefail
[[ "$(uname -s)" == Linux ]] || { echo 'Run on the Pi.' >&2; exit 1; }
cd "$(dirname "$0")/.."
python3 -c 'import cryptography.fernet'
python3 - <<'PY'
from pathlib import Path
import secrets
p=Path('.env');lines=p.read_text().splitlines() if p.exists() else []
keys={line.split('=',1)[0]:line.split('=',1)[1] for line in lines if '=' in line and not line.startswith('#')}
if not keys.get('REEL_PI_SERVICE_SECRET'):lines.append('REEL_PI_SERVICE_SECRET='+secrets.token_urlsafe(48))
lines=[line for line in lines if not line.startswith('REEL_WEBHOOK_DELIVERY=')];lines.append('REEL_WEBHOOK_DELIVERY=relay')
p.write_text('\n'.join(lines)+'\n');p.chmod(0o600)
print('Private Pi bridge configured. Keep its shared secret server-side; do not print it.')
PY
echo 'Restart the worker, then publish only port 3131 with scripts/publish-webhook.sh.'
echo 'In your own Vercel deployment set REEL_PI_SERVICE_URL to the HTTPS origin and REEL_PI_SERVICE_SECRET to the matching private value.'
