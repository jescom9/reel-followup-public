# Secure connection for your own Meta app

The public edition includes a reusable Instagram OAuth connector. The managed customer dashboard, paid website and assisted-setup waitlist are in the separate private service repository.

1. Configure your own Instagram API Meta app and an eligible Business or Creator account. App permissions and access requirements apply.
2. On your Pi, install `python3-cryptography` and run `bash scripts/setup-pi-hosted.sh`. This creates the shared bridge secret in the owner-only `.env` file. Do not print, commit or publish it.
3. Publish only the authenticated listener on port 3131 over HTTPS. Keep the dashboard on port 3130 private through SSH.
4. Deploy the public connector kit to your own Vercel project. Configure `IG_APP_ID`, `IG_APP_SECRET`, `LOGIN_STATE_SECRET`, `IG_REDIRECT_URI=https://YOUR_DOMAIN/api/instagram/callback`, `REEL_PI_SERVICE_URL=https://YOUR_PI_HOST` and the matching `REEL_PI_SERVICE_SECRET`. Register the exact redirect in your Meta app.
5. Set `REEL_CONNECTOR_URL=https://YOUR_DOMAIN/connect/` on the Pi and open that page. Instagram verifies the login; the callback saves the token directly in your host's encrypted vault. Tokens are never displayed for copying.
6. Open your local dashboard through an SSH tunnel. Review its paused account and flows before activation. Each account has isolated credentials and saved records. Reminders use only the flow's own account.

The bridge authenticates path, method, timestamp, nonce and request body. Forged, expired and replayed requests are rejected. Tokens and their owner-only encryption key must be backed up securely together; a database alone cannot restore credentials. The token vault does not encrypt the complete message archive or filesystem.

Self-hosting uses your own Meta app and legal/provider information. It does not provide access to Zodial Labs' managed app or customer dashboard. See [Meta setup](self-host-meta.md) and [the Pi guide](raspberry-pi.md).
