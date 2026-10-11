#!/usr/bin/env bash
# Expose the signed-only ingress, never the dashboard or SSH port.
set -euo pipefail
command -v tailscale >/dev/null || { echo 'Install/enroll Tailscale first.' >&2; exit 1; }
echo 'This publishes only the signed webhook listener on port 3131.'
echo 'If Tailscale asks, enable HTTPS/Funnel for this test Pi in its enrollment page.'
sudo tailscale funnel --bg --https=443 http://127.0.0.1:3131
tailscale funnel status
echo 'Set REEL_WEBHOOK_URL=https://YOUR_TEST_PI_NAME.YOUR_TAILNET.ts.net/webhook'
echo 'Use that URL and your verification token in Meta webhook settings.'
