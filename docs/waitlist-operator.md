# Optional waitlist hosting

The service waitlist at `/waitlist/` stores contact details for assisted onboarding. Signup is not OAuth consent and does not enroll a Pi, create an account, grant app access or send messages.

The Pi uses SQLite and does not need this database. Only the website operator who wants to host a waitlist configures `WAITLIST_DATABASE_URL` on Vercel, together with `LOGIN_STATE_SECRET` for hashing request-limit keys.

Prepare the two dedicated tables using `prepareWaitlist` from `lib/waitlist.mjs` with an administrative database connection. Give the Vercel role schema usage plus `SELECT, INSERT` on `reel_followup_waitlist` and `SELECT, INSERT, UPDATE` on `reel_followup_waitlist_rate_limit`. It needs no access to Instagram event tables and no table-creation permission. Keep the connection secret server-side. Do not configure a Pi with the waitlist connection.

The form stores email, optional name/Instagram username, contact consent and signup time. Duplicate email submissions return the same generic success response. There is no public list or lookup endpoint. Requests require same-origin JSON, a small body, allowed contact fields and explicit consent. Credential fields are rejected; a honeypot and ten-attempt hourly limit reduce automated submissions. Rate keys are hashed; original IP addresses are not stored. These controls do not replace a platform firewall for a targeted abuse incident.

Administrators can inspect invitations through their private database tools. Remove obsolete contact details through those tools when requested; do not expose them in GitHub issues or application logs. Periodically prune rate-limit records with old hour buckets. The endpoint does not send email; contact people only within their stated consent.
