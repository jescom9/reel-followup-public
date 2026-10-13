---
name: reel-followup-pi
description: Install, test, update and maintain Reel Follow-up on a Raspberry Pi through authorized SSH, including SQLite storage, Tailscale access and keyword campaign controls.
---

# Reel Follow-up Pi maintenance

Use the SSH target and account workspace specified by the user. Discover the Pi's username, IP and host fingerprint when missing; verify its host key before connecting. Distinguish a new test Pi from any existing production installation. Keep the client's private SSH key on the client.

The source is https://github.com/jescom9/reel-followup-public. Public source uses anonymous HTTPS; no deploy key is needed. Self-hosting requires the user’s own Meta app. Agent-assisted installation is waitlisted at https://reelfollowups.app/waitlist/. Eligible accounts can use the secure hosted connection. Do not register GitHub deploy keys, print key contents or commit key files. The public installation guide is https://reelfollowups.app/tutorial/. The bot runs in Python 3.10+ with cryptography for token encryption. Vercel serves Instagram OAuth and optional signed forwarding; it does not run the Pi worker or this skill.

## Install a fresh Pi

On 64-bit Raspberry Pi OS, enable SSH through the Pi console, install the client's public key and compare the host fingerprint. Install prerequisites and clone the public source:

```sh
sudo apt update
sudo apt install -y python3 python3-cryptography git curl cron
sudo systemctl enable --now ssh cron
git clone https://github.com/jescom9/reel-followup-public.git reel-followup
cd reel-followup
git switch main
bash scripts/bootstrap-pi.sh
```

The bootstrap preserves an existing `.env`, creates fresh configuration only when absent, runs an isolated self-test and starts a detached supervisor with user cron startup. It must run on the Pi, not the client. Fresh defaults are `REEL_STORAGE=sqlite`, `REEL_WEBHOOK_DELIVERY=direct` and a blank `REEL_FOLLOWUP_DATABASE_URL`. No Neon account is needed.

Private configuration and SQLite data are under `.env` and `native/.local/`; additional Instagram accounts have isolated profile folders. Never publish these files or reset delivery receipts. A fresh installation must stay paused until account verification and intentional activation. Do not copy production Instagram tokens into a test installation or start a second worker for the same account.

## Local and remote SSH

Local access uses `ssh YOUR_USER@NEW_PI_IP`. Run `bash scripts/setup-remote-ssh.sh` on the Pi to install official Tailscale and enroll it as `reel-followup-test` with Tailscale SSH. Give the owner the enrollment URL when interactive approval is needed. Use the same tailnet as the client, then verify `tailscale ssh YOUR_USER@reel-followup-test`. Both network and SSH policy permission are required. Preserve existing policy rules; do not open router ports. Local OpenSSH stays available.

The private dashboard binds to loopback port 3130. Open it through:

```sh
ssh -N -L 127.0.0.1:3130:127.0.0.1:3130 YOUR_USER@PI_IP_OR_TAILSCALE_NAME
```

Then use http://localhost:3130. The bot keeps running after the client disconnects.

## Campaigns and status

Run commands on the Pi in its source folder:

```sh
python3 scripts/reelctl.py status
python3 scripts/reelctl.py accounts
python3 scripts/reelctl.py campaign list
python3 scripts/reelctl.py campaign add \
  --name 'App download' --keyword APP --link https://example.com/app \
  --no-follow --followup 'Did you get a chance to try it?' --delay 60
python3 scripts/reelctl.py campaign pause CAMPAIGN_ID
python3 scripts/reelctl.py campaign resume CAMPAIGN_ID
python3 scripts/reelctl.py service status
```

Use `--account PROFILE_ID` before the subcommand for another workspace; get IDs from `accounts`. New campaigns and follow-ups start paused. Omit `--no-follow` when a current follower check is required. Resume requires a verified account, and the account pause switch still applies. Edit text, links, follow-ups and public reminders through the private dashboard. `status` omits tokens and the private API nonce. Report the selected account, campaign IDs/pause states, storage backend and worker state; do not print `.env` or full `/api/status` responses.

## Validate and update

`python3 scripts/reelctl.py selftest` runs a disposable SQLite/signed-webhook/follower-flow simulation, sends zero external messages and checks duplicate delivery plus persisted receipts. It does not prove live Instagram access. Check service status, disconnect SSH, reconnect and check that the supervisor and worker are still running. Distinguish this from a reboot test or an off-network test.

For an authorized source update, use `python3 scripts/reelctl.py update` from a clean Git checkout. It pulls with `--ff-only`, runs Python tests and restarts one worker while preserving private state. If Git authentication or tests fail, report the failure and do not claim deployment succeeded. For maintenance stops, wait until `process_running` and `supervisor_running` are false before starting again. Logs are in `native/.local/worker-service.log`.

## Live Instagram and optional Neon

For live self-hosting, configure the owner’s own Meta app ID/secret in private server configuration. Tokens are handed directly to the encrypted Pi vault, not copied from the browser. Deploy a connector with that same app; set REEL_CONNECTOR_URL to its HTTPS /connect/ page. The owner authorizes a Meta-compatible Business or Creator account through that connector and uses the secure Pi bridge to save its token directly in the encrypted vault. The browser must not display or copy the token. Configure the authenticated Pi bridge using scripts/setup-pi-hosted.sh and the public secure connection guide before login. Keep the key files private; do not publish them. If the user wants the operator’s service to handle the app and onboarding, direct them to the assisted setup waitlist for assisted onboarding. The relay requires a configured Pi URL/shared secret and Meta authorization; do not claim universal account access. Required permissions include `instagram_business_basic`, `instagram_business_manage_comments` and `instagram_business_manage_messages`; app access levels and reply windows still apply.

With SQLite/direct delivery, live events need a public HTTPS callback reaching only the signed ingress on port 3131. When requested, use `bash scripts/publish-webhook.sh` and the owner's HTTPS/Funnel approval. Never publish port 3130 or SSH through Funnel. Set `REEL_WEBHOOK_URL` and Meta's verification token consistently, using the same app signing secret on the Pi. Your own Vercel receiver may forward original signed bytes using `REEL_WEBHOOK_FORWARD_URL=https://YOUR_PI_HOST/webhook`, matching signing secret and verification token. Forwarding requires no Neon; the Pi must be reachable for delivery.

Neon is opt-in with `REEL_STORAGE=neon`, `REEL_WEBHOOK_DELIVERY=neon` and a private worker database URL. Vercel's Neon queue uses its restricted database connection and consenting account registry, with forwarding unset. Older deployments that have a database URL but no selector keep Neon compatibility. Changing backends does not migrate history or send receipts; preserve and migrate that state before changing a live account. Keep unrelated home-security services separate.
