#!/usr/bin/env bash
# Run on the Pi, as the non-root account that owns this checkout.
set -euo pipefail
if [[ "$(uname -s)" != Linux || ! -d /run/systemd/system ]]; then
  echo 'Run this installer on your Raspberry Pi with systemd.' >&2
  exit 1
fi
if [[ "$EUID" == 0 ]]; then
  echo 'Run as your normal Pi user; the installer uses sudo for the system service.' >&2
  exit 1
fi
project_dir="$(cd "$(dirname "$0")/.." && pwd -P)"
service_user="$(id -un)"
python_bin="$(command -v python3)"
# Keep generated systemd values unambiguous; choose a checkout without spaces.
for value in "$project_dir" "$python_bin" "$service_user"; do
  if [[ ! "$value" =~ ^[a-zA-Z0-9_./-]+$ ]]; then
    echo 'Use a checkout, runtime paths, and username containing only letters, digits, /, ., _, or -.' >&2
    exit 1
  fi
done
"$python_bin" -c 'import sys; assert sys.version_info >= (3,10), "Python 3.10+ is required"'
if [[ ! -f "$project_dir/.env" ]]; then
  echo 'Create your private .env first; see docs/raspberry-pi.md.' >&2
  exit 1
fi
chmod 600 "$project_dir/.env"
mkdir -p "$project_dir/native/.local"
chmod 700 "$project_dir/native/.local"
unit_file="$(mktemp)"
trap 'rm -f "$unit_file"' EXIT
cat > "$unit_file" <<EOF
[Unit]
Description=Reel Follow-up Instagram worker and local dashboard
Wants=network-online.target
After=network-online.target
StartLimitIntervalSec=60
StartLimitBurst=5

[Service]
Type=simple
User=$service_user
WorkingDirectory=$project_dir
ExecStart=$python_bin $project_dir/native/app.py
Environment=PATH=$(dirname):$(dirname "$python_bin"):/usr/local/bin:/usr/bin:/bin
Environment=PYTHONUNBUFFERED=1
Environment=PYTHONDONTWRITEBYTECODE=1
Restart=on-failure
RestartSec=10
UMask=0077
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=read-only
ReadWritePaths=$project_dir/.env $project_dir/native/.local
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectControlGroups=true
RestrictSUIDSGID=true
CapabilityBoundingSet=
RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6

[Install]
WantedBy=multi-user.target
EOF
sudo install -m 644 "$unit_file" /etc/systemd/system/reel-followup.service
sudo systemctl daemon-reload
sudo systemctl enable reel-followup.service
sudo systemctl restart reel-followup.service
sudo systemctl --no-pager --full status reel-followup.service
echo 'From your Mac: ssh -N -L 127.0.0.1:3130:127.0.0.1:3130 YOUR_USER@YOUR_PI'
echo 'Then open http://localhost:3130. A fresh installation starts with sending paused.'
