// Separate tables for Reel Follow-up; existing Bikefitting tables are not changed.
export async function prepareFlowStore(sql) {
  await sql.query(`CREATE TABLE IF NOT EXISTS reel_followup_instagram_webhook_events (
    ig_account_id text NOT NULL,event_id text NOT NULL,payload jsonb NOT NULL,
    state text NOT NULL DEFAULT 'pending',detail text NOT NULL DEFAULT '',
    received_at timestamptz NOT NULL DEFAULT now(),updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (ig_account_id,event_id))`);
  await sql.query(`CREATE INDEX IF NOT EXISTS reel_followup_webhook_pending_idx
    ON reel_followup_instagram_webhook_events (ig_account_id,state,received_at)`);
  await sql.query(`CREATE TABLE IF NOT EXISTS reel_followup_instagram_contacts (
    ig_account_id text NOT NULL,recipient_id text NOT NULL,opened boolean NOT NULL DEFAULT false,
    link_sent boolean NOT NULL DEFAULT false,inbound_at double precision NOT NULL DEFAULT 0,
    media_id text NOT NULL DEFAULT '',updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (ig_account_id,recipient_id))`);
  await sql.query(`CREATE TABLE IF NOT EXISTS reel_followup_instagram_flow_actions (
    ig_account_id text NOT NULL,action_id text NOT NULL,state text NOT NULL,
    receipt jsonb NOT NULL DEFAULT '{}'::jsonb,updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (ig_account_id,action_id))`);
}

export async function saveWebhookEvents(sql, accountId, events) {
  if (!events.length) return 0;
  const params = [];
  const values = events.map(event => {
    const n=params.length;
    params.push(accountId,event.id,JSON.stringify(event.payload));
    return `($${n+1},$${n+2},$${n+3}::jsonb)`;
  });
  const saved=await sql.query(`INSERT INTO reel_followup_instagram_webhook_events
    (ig_account_id,event_id,payload) VALUES ${values.join(',')}
    ON CONFLICT DO NOTHING RETURNING event_id`,params);
  return saved.length;
}
