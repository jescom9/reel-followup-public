#!/usr/bin/env bash
# Run on the new Pi after first connecting through local OpenSSH.
set -euo pipefail
[[ "$(uname -s)" == Linux ]] || { echo 'Run this on the new Pi.' >&2; exit 1; }
sudo systemctl enable --now ssh
if ! command -v tailscale >/dev/null 2>&1; then
  installer="$(mktemp)"
  trap 'rm -f "$installer"' EXIT
  curl -fsSL --proto '=https' https://tailscale.com/install.sh -o "$installer"
  sudo sh "$installer"
fi
sudo systemctl enable --now tailscaled
echo 'Approve enrollment with the same Tailscale account as your client.'
sudo tailscale up --hostname=reel-followup-test --ssh
tailscale ip -4
echo "Connect from a Tailscale client: tailscale ssh $(id -un)@reel-followup-test"
echo 'Local OpenSSH remains available on the LAN IP.'
