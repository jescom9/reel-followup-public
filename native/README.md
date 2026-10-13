# Reel Follow-up on Mac and Raspberry Pi

The bot runs in Python 3.10+ with cryptography for token encryption. Local SQLite stores events, contacts, chats, jobs and delivery receipts by default. Neon is an optional HTTPS storage/queue backend; no Node worker or Docker bot is required. Node is used for developing and testing the Vercel functions.

Start locally with `python3 native/app.py`. The dashboard listens on `127.0.0.1:3130` and the signed webhook listener on `127.0.0.1:3131`. Follow the [Pi guide](../docs/raspberry-pi.md) for local SSH, Tailscale SSH and bootstrap. The supervisor restarts the Python bot and launches it at boot.

## Connect Instagram

Self-hosting requires your own Meta app. Deploy your own Instagram connector and configure `REEL_CONNECTOR_URL` to its `/connect/` page; see [the Meta setup guide](../docs/self-host-meta.md). Use that connector to authorize a Business or Creator account. The sign-in callback stores its token directly in the Pi’s encrypted database; it does not display a token for copying. Follow [the secure connection guide](../docs/secure-instagram-connection.md). Meta app approval, messaging permissions and conversation routing still apply. Tokens live in the encrypted per-account SQLite vault. Keep app/service secrets and any optional database connection in the owner-only, Git-ignored `.env` file. Never copy them into GitHub or a public URL.

By default, HTTPS delivers signed events directly to the Pi and its SQLite queue. Vercel may forward the original signed bytes or optionally queue events in Neon. Set `REEL_STORAGE` and `REEL_WEBHOOK_DELIVERY` explicitly for Neon. Keep only one bot worker for a given account; delivery claims prevent repeated sends after duplicate webhook delivery or a restart.

## Edit keyword flows

Under **Keyword flows**, add separate keywords such as `alarm` and `app`. Edit each flow's destination URL, opening message, follow request, link text/button label, public reply, and follow-up message/delay. Save changes, then resume the desired flow. New flows start paused; enter an HTTPS destination before resuming. Keywords are unique across flows. If a comment matches several flows, the first matching active flow handles it.

**Pause flow** stops its initial replies, follower checks and follow-ups. **Pause follow-ups** leaves initial replies active. Pending jobs remain saved and can resume later if their reply window is still open. Removed flows stop sending.

Follower checks read Meta's current follower flag. Delayed changes are rechecked automatically without repeating the same prompt. Links and prompts have separate durable send claims; unknown delivery outcomes remain in review. Existing legacy buttons and the current flow's configured link are preserved.

Follow-ups are scheduled separately for each flow/contact. The bot checks the live inbox before sending and sends at most once per flow/contact. Instagram requires an inbound message or postback within the past 24 hours. Clicking a URL button alone does not open that window. Closed windows are skipped; paused jobs are held. Each flow displays scheduled/sent jobs, waiting replies, closed windows and review counts.

## History and checks

The history panel saves conversation/message pages in separate Reel Follow-up tables, resumes interrupted pages, and refreshes changed conversations. The optional historical batch tool matches older link messages; it is separate from the new per-flow schedules.

Run `python3 -m unittest discover -s test -p 'test_*.py'` for Python regression tests. With development dependencies installed, `pnpm test` checks the Vercel OAuth and signed receiver. The hosted dashboard uses account-scoped Instagram sessions. Automatic token renewal and home-security control are separate features.

## Multiple accounts and public comment reminders

Use **Instagram account workspaces → Add an Instagram account** to verify a token from the Vercel connector. Every connected account has its own private token file, SQLite history, keyword flows, schedule and account pause control. All account workers run together in the one Python service. Switching the dashboard changes the workspace you edit; it does not stop the others. This is the private host owner's account manager, not public user signup.

Each flow can enable **Reply in comments if no interaction with the opening DM**, with an editable delay (24 hours by default) and text. Reminders apply to new opening sends after enabling the setting. The worker checks recorded interactions and the live inbox, then posts at most one public reply on the original comment. A reply/button interaction cancels it; paused flows or accounts do not post. A comment reminder does not extend the direct-message reply window.

Reminders are posted only by the account that owns the flow and media. Cross-account collaboration has been removed. Older flow settings that selected a different reminder account are shown with reminders disabled, and runtime checks block cross-account jobs before any API call. Account workspaces remain isolated and can still be managed separately.

## Reel targeting

Keyword flows default to `media_scope: "all"`, including future Reels. A flow can use `media_scope: "selected"` with a nonempty `media_ids` array of up to 50 owned Instagram Reel IDs. The worker matches both keyword and Reel before attempting an opening. The managed website includes an Instagram API thumbnail picker; local editor saves preserve existing targeting. Creating or changing selections verifies ownership. Identical keywords may be used by different flows when their selected Reel sets do not overlap.

## Launching after comments have already arrived

The managed editor can preview and launch earlier keyword comments from the selected Reels. The shared worker stores the reviewed snapshot in the account’s SQLite database, sends at most one launch notice per person, and paces work at one comment per minute. Initial DMs remain limited to seven days after the comment; older comments get the reviewed public invitation to comment again. An accepted opening is required before “check your DMs” is posted, and following is still checked before the link is delivered. Unknown send outcomes pause the run for review rather than retrying.
