#!/usr/bin/env bash
# Start and supervise the worker at boot without changing system services.
set -euo pipefail
if [[ "$(uname -s)" != Linux ]]; then
  echo 'Run on the Pi.' >&2
  exit 1
fi
project_dir="$(cd "$(dirname "$0")/.." && pwd -P)"
if [[ ! "$project_dir" =~ ^[a-zA-Z0-9_./-]+$ ]]; then
  echo 'Use a project path without spaces or shell metacharacters.' >&2
  exit 1
fi
python3 -c 'import sys; assert sys.version_info >= (3,10)'
[[ -f "$project_dir/.env" ]]
chmod 600 "$project_dir/.env"
mkdir -p "$project_dir/native/.local"
chmod 700 "$project_dir/native/.local"
task_cron="$(mktemp)"
trap 'rm -f "$task_cron"' EXIT
crontab -l > "$task_cron" 2>/dev/null || true
python3 - "$task_cron" "$project_dir" <<'PY'
import sys
from pathlib import Path
path,project=Path(sys.argv[1]),sys.argv[2]
lines=[line for line in path.read_text().splitlines() if '# reel-followup-worker' not in line]
lines.append(f'@reboot /usr/bin/python3 {project}/scripts/pi-user-service.py start worker >> {project}/native/.local/worker-boot.log 2>&1 # reel-followup-worker')
path.write_text('\n'.join(lines)+'\n')
PY
crontab "$task_cron"
python3 "$project_dir/scripts/pi-user-service.py" start worker
