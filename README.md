<img src="assets/reel-followup.png" alt="Reel Follow-up" width="120">

# Reel Follow-up

An MIT-licensed Instagram keyword-to-DM bot with editable links, follower checks, follow-ups, pause controls and multiple account workspaces. Run it on a Raspberry Pi or Mac. The bot uses Python's standard library and **local SQLite by default**. Neon is optional.

## Choose your setup

**Self-host now:** create your own Meta developer app and authorize your own Instagram Business or Creator account. Use your app ID, app secret, account token and signed HTTPS webhook callback. A copied token from someone else's app alone is not a complete independent installation. Follow [the Meta app guide](docs/self-host-meta.md) and [the Raspberry Pi tutorial](docs/raspberry-pi.md).

**Prefer assisted setup?** Join [the Reel Follow-up waitlist](https://reel-followup.vercel.app/waitlist/) for agent-assisted installation and a service-managed Meta connection. That service is planned; joining the waitlist does not authorize Instagram or start messaging.

## Test a fresh Pi

```sh
git clone https://github.com/jescom9/reel-followup-public.git reel-followup
cd reel-followup
bash scripts/bootstrap-pi.sh
python3 scripts/reelctl.py selftest
python3 scripts/reelctl.py status
```

Install Python 3.10+, Git, curl and cron first, as described in the guide. No GitHub login, deploy key or Neon database is needed. The isolated self-test simulates Instagram and sends zero external messages. Fresh account workspaces and campaigns start paused. Run one worker per installation; keep only one active installation per Instagram account.

## Agent maintenance

Copy the [maintenance skill](agent-skill/reel-followup-pi/SKILL.md) into your agent. With authorized SSH or Tailscale access, it can add or pause campaigns, report status and update the service. See [the command guide](docs/agent-maintenance.md).

```sh
python3 scripts/reelctl.py campaign add \
  --name 'App download' --keyword APP --link https://example.com/app --no-follow
python3 scripts/reelctl.py campaign pause CAMPAIGN_ID
python3 scripts/reelctl.py update
```

Campaigns added through the CLI start paused. Configure messages and follow-ups in the private dashboard. The agent does not need to publish SSH keys.

## Your own Vercel connector

Deploy this repository to your own Vercel project and set `IG_APP_ID`, `IG_APP_SECRET`, `LOGIN_STATE_SECRET` and your exact `IG_REDIRECT_URI`. Register that redirect in your own Meta app. Open your deployment's `/connect/` page to authorize Instagram. Set `REEL_CONNECTOR_URL` on the Pi to that page. Publish only the signed webhook listener; keep the dashboard private through SSH.

Meta permissions, app access levels and reply windows apply. The operator completes required consent and approvals. Self-hosting does not grant access to the Reel Follow-up operator's Meta app. Configuration and data in `.env` and `native/.local/` stay private; the source contains no installed credentials or private host data. Some internal IDs and archive matching rules preserve compatibility with earlier installations.

## Checks

```sh
python3 -m unittest discover -s test -p 'test_*.py'
node --test
```

Node and `pnpm install` are needed for Vercel development/tests, not the Pi bot. Optional waitlist hosting uses a separate restricted `WAITLIST_DATABASE_URL`; it is never required by the Pi. See [waitlist operator setup](docs/waitlist-operator.md).

[Follow @reelfollowup](https://www.instagram.com/reelfollowup) · [Public tutorial](https://reel-followup.vercel.app/tutorial/) · [Assisted setup waitlist](https://reel-followup.vercel.app/waitlist/)
