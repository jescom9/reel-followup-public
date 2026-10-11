# Use your own Meta app for self-hosting

The public Reel Follow-up installation uses **your own Meta developer app**. It does not require access to the Reel Follow-up operator’s app. A token from the operator’s sign-in page alone is not a complete independent webhook installation.

## Your Meta connection

1. Open [Meta for Developers](https://developers.facebook.com/apps/) and create a Meta app for Instagram automation. Add Instagram API with Instagram Login. Follow Meta’s current setup screens for your account.
2. Use an Instagram Business or Creator account you control. Authorize the app for profile access, comments and messages: `instagram_business_basic`, `instagram_business_manage_comments`, and `instagram_business_manage_messages`. Meta’s app access levels, tester roles and review rules apply.
3. Deploy your copy of the public repository to Vercel. Set `IG_APP_ID`, `IG_APP_SECRET`, a random `LOGIN_STATE_SECRET`, and `IG_REDIRECT_URI=https://YOUR_DOMAIN/api/instagram/callback`. Keep all secrets server-side.
4. Register that exact redirect URL in the Meta app. Visit **your own** `https://YOUR_DOMAIN/connect/` page to authorize the account. Configure [the authenticated Pi bridge](secure-instagram-connection.md) before signing in. The callback saves its account token directly in the Pi’s encrypted vault. Never paste a token or app secret into a GitHub issue or the waitlist.
5. On the Pi, set your matching `IG_APP_ID`, `IG_APP_SECRET` for direct mode, and `REEL_CONNECTOR_URL=https://YOUR_DOMAIN/connect/` in `.env`. Its file mode must remain 600. The secure OAuth handoff verifies the account and starts its workspace paused.
6. Follow [the Pi tutorial](raspberry-pi.md) to publish the signed listener through HTTPS. Set Meta’s callback URL and verification token to match the Pi. For optional forwarding through your own Vercel app, use the same Meta signing secret on that deployment and the Pi.
7. Add your keyword campaigns and check their links and messages. Activate only the accounts and flows you intend to run. One host can manage several accounts authorized for the same configured Meta app.

SQLite is the default. Neon is an optional archive/queue backend. The public source does not ship app credentials, user tokens, SSH keys or private account data.

## Prefer assisted setup?

Join [the Reel Follow-up assisted setup waitlist](https://reel-followup.vercel.app/waitlist/). The planned service helps install the Pi worker and manages the Meta connection/webhook relay using the operator’s app. It is not available yet and waitlist signup does not authorize Instagram or start any automation. Service onboarding and platform approval must be completed before live use.

The waitlist asks only for contact details. Do not share a Facebook password, Instagram token, app secret or SSH private key. Agents can assist with configuration; the account owner completes required sign-in, consent and approvals.
