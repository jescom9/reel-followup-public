# Sign in without displaying an Instagram token

Version 0.4 hands the Instagram connection directly from Vercel to the Pi. The browser receives a short-lived, HttpOnly sign-in session. It does not receive the Instagram access token, a copy button or a token in a redirect URL.

## Pi setup

Install `python3-cryptography` from Raspberry Pi OS/Debian packages. The bot remains a Python process; no Node worker runs on the Pi. Every workspace stores its token in `credentials.sqlite`, authenticated/encrypted with Fernet. The matching private key is an owner-only file outside that database. Back up both securely; a database-only copy cannot unlock the token. Restoring a mismatched key fails closed.

```sh
sudo apt install -y python3-cryptography
bash scripts/setup-pi-hosted.sh
```

Set the Pi’s `IG_APP_ID` to the same app ID used by your Vercel connector. For relay mode, Meta’s app secret can remain only on Vercel. Restart the worker and use `bash scripts/publish-webhook.sh` to publish only the signed ingress on port 3131. The local dashboard stays private on port 3130.

In Vercel, configure `REEL_PI_SERVICE_URL=https://YOUR_PI_HOST` and the matching private `REEL_PI_SERVICE_SECRET`. The helper creates that secret in the owner-only Pi `.env`. Transfer it through a private server configuration channel; never paste it into chat, a URL or GitHub. This is a service authentication secret, not an SSH key or user token.

The existing Meta app settings still apply: `IG_APP_ID`, `IG_APP_SECRET`, `LOGIN_STATE_SECRET`, and the exact `IG_REDIRECT_URI`. Meta’s callback remains `/api/instagram/webhook`; Vercel verifies Meta’s signature before handing account events to the Pi. A fresh relay installation can leave the legacy account registry empty and needs no Neon URL.

## Account enrollment and controls

Open your connector and sign in with an eligible Business or Creator account. The Pi independently verifies its identity and webhook subscription before saving the encrypted token. New workspaces start paused. The signed browser session opens `/dashboard/`, where the account owner can add/edit keyword flows, pause them or their follow-ups, and activate the account when ready.

The Vercel account API always derives the account ID from the authenticated cookie. It does not accept a client-selected account ID. The Pi bridge authenticates method, path, timestamp, nonce and body; expired, forged or replayed requests are rejected. The bridge never returns credentials in account status.

Existing accounts configured in the Vercel legacy registry keep their current queue routing. To prevent a second active worker, set `REEL_RESERVED_ACCOUNT_IDS` on a new Pi to their canonical/alias IDs. Those workspaces cannot be activated there until the operator intentionally migrates them and removes their legacy routing.

For a migration, pause the old workspace, back up both installations, and import the account's archive, contacts, delivery claims and workflow jobs into its new workspace. Preserve accepted and uncertain delivery claims so restoring history cannot repeat a send. Keep the new encrypted credential; do not replace it with an old token. The hosted dashboard displays local contacts and paginated chat history only for the signed-in account.

After verifying the import, set `REEL_PI_ACCOUNT_IDS` in Vercel to the migrated account's canonical and alias IDs, separated by commas. This explicitly routes those IDs to the Pi while preserving other legacy routes. Redeploy Vercel, import any remaining events from the old queue, and remove only those IDs from the new Pi's `REEL_RESERVED_ACCOUNT_IDS`. Activate one installation. Accounts whose archive remains in Neon use the private Pi dashboard for history.

## Existing credentials and backups

On startup, credentials supplied in the installation’s `.env` are imported into the encrypted vault; managed token values are cleared from that live environment file. Tokens received through OAuth are never written to workspace `.env` files. Runtime configuration omits tokens from JSON and public APIs. Existing backups may still contain older plaintext configuration and remain private.

SQLite is the default. Token encryption does not encrypt the complete filesystem or message archive. The Pi owner and its worker must be able to read the private key to use the token. Automatic Meta token renewal is not implemented; sign in again to renew an expired connection.
