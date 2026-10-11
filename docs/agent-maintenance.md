# Maintain Reel Follow-up through SSH

The Python service runs on the Pi without an attached client. An agent with authorized SSH can manage it using `reelctl`; the command itself does not install an AI agent or grant a chat unattended access.

## Pi-side commands

```sh
cd ~/reel-followup
python3 scripts/reelctl.py status
python3 scripts/reelctl.py accounts
python3 scripts/reelctl.py campaign list
python3 scripts/reelctl.py campaign add \
  --name 'App download' --keyword APP --link https://example.com/app \
  --no-follow --followup 'Did you get a chance to try it?' --delay 60
python3 scripts/reelctl.py campaign pause CAMPAIGN_ID
python3 scripts/reelctl.py campaign resume CAMPAIGN_ID
python3 scripts/reelctl.py service status
python3 scripts/reelctl.py update
```

New campaigns and follow-ups always start paused. `--no-follow` permits a link without follower status; otherwise a current follower check is required. Edit messages and follow-up settings in the dashboard. Resume requires a verified account; the account's own pause state still applies.

Use `--account PROFILE_ID` before the command to select another workspace. `accounts` lists IDs. `status` returns storage, sending state, campaigns and schedule counts without tokens or the private API nonce.

A client-side agent can run commands through your verified SSH target:

```sh
ssh YOUR_USER@reel-followup-test \
  'cd ~/reel-followup && python3 scripts/reelctl.py status'
```

Enrollment, device approval and Tailscale SSH checks can require owner authentication. Logs are in `native/.local/worker-service.log`. The bot runs independently of the maintenance agent.

## Copy the agent skill from Vercel

Download [SKILL.md](https://reel-followup.vercel.app/agent-skill/reel-followup-pi/SKILL.md) into your agent's skill folder. For Codex on the client or Pi:

```sh
mkdir -p ~/.codex/skills/reel-followup-pi
curl -fsSL https://reel-followup.vercel.app/agent-skill/reel-followup-pi/SKILL.md \
  -o ~/.codex/skills/reel-followup-pi/SKILL.md
```

Start a new agent session if needed, then invoke `$reel-followup-pi`. Other agents that support SKILL.md can use their own skill directory. The skill is a public instruction file, contains no credentials, and does not execute on Vercel.

Example request:

> Use $reel-followup-pi to set up my new test Pi over the SSH target I provide. Keep SQLite as the default, enroll Tailscale, run the isolated self-test, and add a paused Setup test campaign. Report the commit, SQLite backend, worker PID and campaign ID, then reconnect to verify the service survived. Preserve the existing production Pi.
