# Hosted operations

`REEL_ADMIN_ACCOUNT_IDS` pins verified canonical Instagram IDs, server-side. Sign in as the configured operator and open **Admin**. Accounts & usage gives aggregate usage, review counts and read-only support inspection for flows, requests, failures and paginated conversations. Each inspection is audited for 90 days. Account tokens and payment identifiers are excluded. Ordinary sessions cannot gain admin privileges through a username, request flag or target ID.

**Resources & recovery** samples Pi CPU, available RAM, disk, database sizes, worker/supervisor, signed ingress availability, website availability, hourly Neon SQL availability and backup SSH availability. CPU load above 1.5/core, RAM or disk below 15%, old event backlog, recent processing failures, backup age and recorded Neon quota pressure appear as alerts. Samples have timestamps. Neon compute and transfer are **dated operator snapshots**, because the database connection cannot read Neon billing usage. Refresh `native/.local/neon-usage.json` from the operator's Neon project report when checking monthly allowance; never claim this is live billing. Storage SQL reports physical database size separately from branch logical storage.

## Neon on the hosted worker

Set `REEL_STORAGE=neon`, `REEL_FOLLOWUP_DATABASE_URL` privately and **`REEL_WEBHOOK_DELIVERY=relay`** in root and account environments. Neon stores the archive, contacts and global delivery claims; encrypted credentials, webhook intake, campaign configuration, jobs and plan records remain local. The signed Vercel bridge sends new webhooks directly to the Pi. Idle archive/dashboard refresh and SQL health probes run hourly so they do not keep the free compute awake every few seconds. The account header caches cloud archive totals for an hour; plan and workflow totals remain local and current. Read-only archive calls use a bounded five-second timeout without schema preparation. An archive outage leaves plan/settings access available. Opening conversations and real messages may wake the database.

Before changing storage, take an encrypted backup, stop the worker and run:

```sh
python3 scripts/migrate-worker-neon.py --env-file /private/path/neon.env
```

The migration merges archives and contacts, preserves terminal receipts and retains uncertain claims for review. It never sends Instagram messages. Verify all receipts before switching environments and restarting. Never switch back to an older local receipt snapshot while allowing sends: reconcile current Neon claims first. Connected customer plans and local jobs are retained.

## Encrypted standby backup

`scripts/backup-worker.py --push` takes online SQLite snapshots, adds account environments and matching vault keys, copies all configs with `enabled=false`, encrypts with AES-GCM and performs an isolated restore/integrity rehearsal. The standby receives only an encrypted stream through a dedicated public key with a forced receiver command, no shell or forwarding. Upload checksums are checked. Twelve snapshots are retained locally and on the standby; four-hour user-systemd scheduling is configured on the hosted Pi. The backup key must also be kept separately, owner-only, outside the failed Pi. Backups contain private credentials even though ciphertext is encrypted; protect recovery keys accordingly.

To restore into an empty directory:

```sh
python3 scripts/restore-worker.py /private/path/snapshot.rfbackup --key /private/path/recovery.key --output /private/path/recovery
```

The normal worker supervisor restarts a crashed process. A whole-host failure needs a manual move to a standby, Linux desktop or rented server. Keep the old worker offline, restore paused, verify credentials and Neon, inspect uncertain actions/events after the backup, then change the webhook route and resume accounts. A four-hour schedule is a target recovery point; a failed backup increases data age. Neon history retention is separate from the local encrypted snapshot. Do not start both automation workers simultaneously.

## Instagram service alerts

Set `REEL_ALERT_USERNAME` to the intended connected operator username. That owner sends **alerts** to the configured campaign inbox. The bot verifies the sender through Instagram and the connected owner account before saving the scoped recipient ID. It sends a subscription acknowledgement, deduplicated service/capacity changes and recovery messages within 24 hours of the last inbound message. Send alerts again to reopen the reply window. A URL click does not renew it. Operational alert sends keep local durable claims so a Neon outage can still be reported; prior cloud-mode outcomes are preserved. Customer campaign sends continue to require Neon claims. Unknown send results remain claimed for review. The monitoring process on the main Pi cannot send while that Pi is fully offline; the independently scheduled standby watchdog checks the primary ingress every two minutes and sends an outage alert after three failures, plus a recovery notice. It receives only the operator inbox credential in a separate encrypted envelope and never runs customer campaigns. Both-host failures still require external monitoring.
