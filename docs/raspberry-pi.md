# Run Reel Follow-up on your Raspberry Pi

The public self-hosting version requires **your own Meta developer app**. Prefer a service-managed connection? [Join the assisted setup waitlist](https://reel-followup.vercel.app/waitlist/).

Version 0.3 uses **SQLite on the Pi by default**. Events, chats, campaign jobs and delivery receipts stay local. Neon is optional. The bot needs Python 3.10+ and uses its standard library; no Node runtime or Docker bot is required.

## 1 · Connect locally

Use 64-bit Raspberry Pi OS and a user with sudo access. In the Pi terminal:

```sh
sudo systemctl enable --now ssh
whoami
hostname -I
ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub
```

Install your client's public SSH key in `~/.ssh/authorized_keys`; set `.ssh` to mode 700 and `authorized_keys` to 600. Keep the private key on the client. Compare the first-connection fingerprint with the Pi's output.

```sh
ssh YOUR_USER@NEW_PI_IP
```

[Official Raspberry Pi SSH guide](https://www.raspberrypi.com/documentation/computers/remote-access.html).

## 2 · Install on the new Pi

The public source can be cloned over HTTPS without a GitHub account or deploy key. Use your own Meta app for live Instagram automation; see [the Meta setup guide](self-host-meta.md).

```sh
sudo apt update
sudo apt install -y python3 git curl cron
sudo systemctl enable --now cron
git clone https://github.com/jescom9/reel-followup-public.git reel-followup
cd reel-followup
git switch main
bash scripts/bootstrap-pi.sh
python3 scripts/reelctl.py status
python3 scripts/reelctl.py service status
```

The bootstrap copies `.env.pi.example` only if no `.env` exists, generates a verification token, runs an isolated test, and installs a Python supervisor with a user `@reboot` cron entry. Existing configuration is preserved. Fresh accounts stay paused until verified and enabled. Run one worker per installation.

The fresh defaults require no cloud database:

```dotenv
REEL_STORAGE=sqlite
REEL_WEBHOOK_DELIVERY=direct
REEL_FOLLOWUP_DATABASE_URL=
```

Private data lives in `native/.local/`. The root account uses `native/.local/events.sqlite`; additional accounts use their own folders. Back up these files together while the worker is stopped. Preserve delivery receipts to prevent duplicate sends.

## 3 · Enable remote SSH with Tailscale

On the Pi:

```sh
bash scripts/setup-remote-ssh.sh
```

The helper installs official Tailscale, enables its system service, and enrolls the new Pi as `reel-followup-test` with Tailscale SSH. Open its enrollment URL and approve it using the same tailnet as your client.

From a client connected to Tailscale:

```sh
tailscale ssh YOUR_USER@reel-followup-test
```

Tailscale SSH needs both network access and SSH permission in the tailnet policy. Existing custom policies may require a rule for your maintenance user and this device. Keep local OpenSSH available on the LAN IP. No FRITZ!Box forwarding or public IPv6 address is required.

[Official Tailscale SSH instructions](https://tailscale.com/docs/features/tailscale-ssh).

## 4 · Open the private dashboard

Keep this tunnel open on the client; use the LAN IP first, then the Pi's Tailscale hostname/IP away from home:

```sh
ssh -N -L 127.0.0.1:3130:127.0.0.1:3130 YOUR_USER@NEW_PI_IP
```

Open [http://localhost:3130](http://localhost:3130). If Tailscale SSH is enabled and permitted, ordinary `ssh YOUR_USER@reel-followup-test` also uses its server on the Tailscale address. Keep port 3130 available on the client. The dashboard binds to loopback and stays private.

Closing the browser, SSH session or Mac does not stop the Pi's supervisor.

## 5 · Test without Instagram credentials or Neon

```sh
python3 scripts/reelctl.py selftest
python3 scripts/reelctl.py campaign add \
  --name 'Setup test' --keyword SETUPTEST --link https://example.com/
python3 scripts/reelctl.py campaign list
python3 scripts/reelctl.py campaign pause CAMPAIGN_ID
python3 scripts/reelctl.py service status
```

The self-test uses disposable SQLite storage and a fake Instagram API. It exercises the real signed HTTP listener, follower/link branch, duplicate protection and receipt persistence. It sends **zero external messages**. New campaigns and their follow-ups start paused. Replace `CAMPAIGN_ID` with the returned ID.

Disconnect SSH, reconnect, then check service status. Both `supervisor_running` and `process_running` should be true. Separately verify reboot recovery and off-network Tailscale access before relying on unattended operation.

## 6 · Connect Instagram and live webhooks

Use your own Meta automation app and an authorized Business or Creator account. Required permissions are `instagram_business_basic`, `instagram_business_manage_comments` and `instagram_business_manage_messages`. Meta app access levels, review and messaging windows still apply.

Deploy your own connector with the same Meta app as the Pi. Visit your own `https://YOUR_DOMAIN/connect/` page to get the account token. Set `REEL_CONNECTOR_URL=https://YOUR_DOMAIN/connect/` on the Pi. [Follow the Meta setup steps](self-host-meta.md).

Vercel can handle sign-in without a database. Configure `IG_APP_ID`, `IG_APP_SECRET`, `LOGIN_STATE_SECRET`, and `IG_REDIRECT_URI=https://YOUR_DOMAIN/api/instagram/callback`. Register that exact redirect in Meta. After consent, copy the token into the private Pi dashboard and verify its account. Each additional account uses its own workspace.

Set the Pi's automation app ID/secret and token in its owner-only `.env`. Keep `REEL_STORAGE=sqlite` and `REEL_WEBHOOK_DELIVERY=direct`. Restart after environment edits: stop, wait until service status shows `process_running=false`, then start.

```sh
python3 scripts/reelctl.py service stop
python3 scripts/reelctl.py service status
python3 scripts/reelctl.py service start
```

Live flows need a public HTTPS endpoint reaching only the signed listener on `127.0.0.1:3131`. Tailscale Funnel can provide it:

```sh
bash scripts/publish-webhook.sh
```

Approve HTTPS/Funnel if requested. The helper publishes the **signed-only listener**, never the dashboard or SSH. Set `REEL_WEBHOOK_URL=https://YOUR_PI_HOST/webhook`, restart, and register this URL in Meta with the Pi's `IG_WEBHOOK_VERIFY_TOKEN`. The Pi verifies POST signatures with the Meta app secret and queues accepted events in SQLite.

[Official Funnel examples](https://tailscale.com/docs/reference/examples/funnel).

Alternatively, your own Vercel receiver can forward to this Pi URL. Set Vercel's `REEL_WEBHOOK_FORWARD_URL=https://YOUR_PI_HOST/webhook`, matching `IG_WEBHOOK_VERIFY_TOKEN`, and `IG_APP_SECRET` or `IG_WEBHOOK_APP_SECRET`. Register `https://YOUR_DOMAIN/api/instagram/webhook` in Meta and set that as the Pi's `REEL_WEBHOOK_URL`. This route does not need Neon: Vercel checks the signature and forwards the original signed bytes. If the Pi is unavailable, it returns an error so Meta can retry. Direct delivery depends on the Pi being online; it does not provide a separate cloud backlog.

Create keyword campaigns with your own links and messages. Resume only the account and flows you intend to activate. Follow-ups and optional public comment reminders have separate pause switches. Keep only one active installation per Instagram account.

## Optional · Neon archive and cloud queue

Use Neon explicitly for a managed archive and queue while the Pi is offline:

```dotenv
REEL_STORAGE=neon
REEL_WEBHOOK_DELIVERY=neon
REEL_FOLLOWUP_DATABASE_URL=YOUR_PRIVATE_WORKER_CONNECTION
REEL_WEBHOOK_URL=https://YOUR_DOMAIN/api/instagram/webhook
```

In Vercel, leave `REEL_WEBHOOK_FORWARD_URL` unset and configure its restricted database connection, verification token, signing secret and consenting account registry (`IG_WEBHOOK_ACCOUNT_ID` / aliases or `IG_WEBHOOK_ACCOUNTS`). The Python worker creates its tables and connects over HTTPS without Node.

Older installations with a database URL and no storage selector keep their Neon behavior. Changing the selector does not migrate history or delivery receipts. Back up and migrate state before switching a live account. A fresh test installation needs no migration.

## Copy the maintenance skill into your agent

Download [the agent skill](https://reel-followup.vercel.app/agent-skill/reel-followup-pi/SKILL.md) into your agent's skill folder. For Codex on the client or Pi:

```sh
mkdir -p ~/.codex/skills/reel-followup-pi
curl -fsSL https://reel-followup.vercel.app/agent-skill/reel-followup-pi/SKILL.md \
  -o ~/.codex/skills/reel-followup-pi/SKILL.md
```

Start a new agent session if needed, then ask: Use `$reel-followup-pi` to connect to my test Pi, report status and add a paused campaign. Other SKILL.md-compatible agents can use their own skill directory. The public file contains no credentials. Vercel hosts the download; the agent uses SSH to do the work.

## Maintenance · Agent commands and updates

An agent with authorized SSH can use the same Pi-side commands:

```sh
cd ~/reel-followup
python3 scripts/reelctl.py status
python3 scripts/reelctl.py accounts
python3 scripts/reelctl.py campaign list
python3 scripts/reelctl.py --account PROFILE_ID campaign pause CAMPAIGN_ID
python3 scripts/reelctl.py update
```

`update` requires a clean Git checkout, pulls with `--ff-only`, runs Python tests and restarts one worker. It preserves ignored configuration and databases. Public-source updates use anonymous HTTPS; no GitHub deploy key is required. See [the agent command guide](agent-maintenance.md).

Run unrelated home-security automation as a separate service. Reel Follow-up does not control cameras, locks or alarms.

[Assisted setup waitlist](https://reel-followup.vercel.app/waitlist/) · [Follow @reelfollowup](https://www.instagram.com/reelfollowup) · [GitHub source](https://github.com/jescom9/reel-followup-public)
