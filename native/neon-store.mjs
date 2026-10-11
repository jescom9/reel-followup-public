import { neon } from '@neondatabase/serverless';
import readline from 'node:readline';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import {prepareFlowStore} from '../lib/instagram-flow-store.mjs';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const env = {};
for (const line of readFileSync(path.join(root, '.env'), 'utf8').split(/\r?\n/)) {
  const match = line.match(/^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)\s*$/);
  if (match && !match[1].startsWith('#')) env[match[1]] = match[2].replace(/^(['"])(.*)\1$/, '$2');
}
const connection = env.REEL_FOLLOWUP_DATABASE_URL;
if (!connection) {
  process.stdout.write(JSON.stringify({ ready: false, error: 'The local Neon connection is not configured.' }) + '\n');
  process.exit(0);
}

const sql = neon(connection);
const table = 'reel_followup_instagram_chat_archive';
const deliveries = 'reel_followup_instagram_followups';
const chatView = `WITH latest AS (
  SELECT DISTINCT ON (conversation_id) * FROM ${table}
  WHERE ig_account_id=$1 AND record_type='message'
  ORDER BY conversation_id,message_created_at DESC NULLS LAST,record_id DESC
), inbound AS (
  SELECT conversation_id,max(message_created_at) AS inbound_time FROM ${table}
  WHERE ig_account_id=$1 AND record_type='message' AND payload->'from'->>'id'<>$1 GROUP BY conversation_id
), chat AS (
  SELECT l.*,i.inbound_time,
    concat_ws(' ',nullif(l.payload->>'message',''),
      (SELECT string_agg(concat_ws(' ',a->'generic_template'->>'title',a->'generic_template'->>'subtitle'),' ')
       FROM jsonb_array_elements(coalesce(l.payload->'attachments'->'data','[]'::jsonb)) a)) AS preview,
    CASE WHEN l.payload->'from'->>'id'<>$1 THEN l.payload->'from'->>'id' ELSE recipient->>'id' END AS recipient_id,
    CASE WHEN l.payload->'from'->>'id'<>$1 THEN l.payload->'from'->>'username' ELSE recipient->>'username' END AS username,
    f.state AS delivery_state,f.detail AS delivery_detail
  FROM latest l LEFT JOIN inbound i USING(conversation_id)
  LEFT JOIN LATERAL (SELECT value AS recipient FROM jsonb_array_elements(coalesce(l.payload->'to'->'data','[]'::jsonb))
    WHERE value->>'id'<>$1 LIMIT 1) r ON true
  LEFT JOIN ${deliveries} f ON f.ig_account_id=$1 AND f.conversation_id=l.conversation_id AND f.rule_key=$2
), classified AS (
  SELECT *, (payload->'from'->>'id'=$1 AND strpos(lower(preview),lower($3))>0) AS is_match,
    CASE WHEN delivery_state IS NOT NULL THEN delivery_state
      WHEN NOT (payload->'from'->>'id'=$1 AND strpos(lower(preview),lower($3))>0) THEN 'not_matching'
      WHEN recipient_id IS NULL THEN 'unknown_recipient'
      WHEN inbound_time IS NULL OR inbound_time<now()-interval '24 hours' THEN 'window_closed'
      ELSE 'ready' END AS status FROM chat
)`;
try {
  await sql.query(`CREATE TABLE IF NOT EXISTS ${table} (
    ig_account_id text NOT NULL,
    conversation_id text NOT NULL,
    record_type text NOT NULL CHECK (record_type IN ('conversation', 'message')),
    record_id text NOT NULL,
    conversation_updated_at timestamptz,
    message_created_at timestamptz,
    participants jsonb NOT NULL DEFAULT '[]'::jsonb,
    payload jsonb NOT NULL,
    archived_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (ig_account_id, conversation_id, record_type, record_id)
  )`);
  await sql.query(`CREATE INDEX IF NOT EXISTS reel_followup_chat_archive_updated_idx ON ${table} (ig_account_id, conversation_updated_at DESC)`);
  await sql.query(`CREATE INDEX IF NOT EXISTS reel_followup_chat_archive_message_idx ON ${table} (ig_account_id, message_created_at DESC) WHERE record_type = 'message'`);
  await sql.query(`CREATE TABLE IF NOT EXISTS ${deliveries} (
    ig_account_id text NOT NULL,conversation_id text NOT NULL,rule_key text NOT NULL,
    recipient_id text NOT NULL,source_message_id text NOT NULL,state text NOT NULL,
    receipt jsonb NOT NULL DEFAULT '{}'::jsonb,detail text NOT NULL DEFAULT '',updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (ig_account_id,conversation_id,rule_key),UNIQUE (ig_account_id,recipient_id,rule_key)
  )`);
  await prepareFlowStore(sql);
  process.stdout.write(JSON.stringify({ ready: true }) + '\n');
} catch {
  process.stdout.write(JSON.stringify({ ready: false, error: 'Could not prepare the Reel Follow-up archive table in Neon.' }) + '\n');
  process.exit(0);
}

const rl = readline.createInterface({ input: process.stdin, crlfDelay: Infinity });
for await (const line of rl) {
  try {
    const input = JSON.parse(line);
    if (input.done) {
      process.stdout.write(JSON.stringify({ done: true }) + '\n');
      break;
    }
    if (input.webhook_pull) {
      const events=await sql.query(`SELECT event_id,payload,extract(epoch FROM received_at) AS received
        FROM reel_followup_instagram_webhook_events WHERE ig_account_id=$1 AND state='pending'
        ORDER BY received_at LIMIT 50`,[input.ig_account_id]);
      process.stdout.write(JSON.stringify({events})+'\n'); continue;
    }
    if (input.webhook_finish) {
      const v=input.webhook_finish;
      if (!['imported','done','review','ignored'].includes(v.state)) throw Error('Invalid event state');
      await sql.query(`UPDATE reel_followup_instagram_webhook_events SET state=$3,detail=$4,updated_at=now()
        WHERE ig_account_id=$1 AND event_id=$2`,[v.ig_account_id,v.event_id,v.state,v.detail || '']);
      process.stdout.write(JSON.stringify({recorded:true})+'\n');continue;
    }
    if (input.webhook_stats) {
      const [stats]=await sql.query(`SELECT count(*)::int AS received,count(*) FILTER(WHERE state='pending')::int AS pending,
        count(*) FILTER(WHERE state='imported')::int AS imported,count(*) FILTER(WHERE state='done')::int AS done,
        count(*) FILTER(WHERE state='review')::int AS review,max(received_at) AS last_received
        FROM reel_followup_instagram_webhook_events WHERE ig_account_id=$1`,[input.ig_account_id]);
      process.stdout.write(JSON.stringify({stats})+'\n');continue;
    }
    if (input.flow_action_claim) {
      const v=input.flow_action_claim;
      const inserted=await sql.query(`INSERT INTO reel_followup_instagram_flow_actions (ig_account_id,action_id,state)
        VALUES($1,$2,'attempting') ON CONFLICT DO NOTHING RETURNING action_id`,[v.ig_account_id,v.action_id]);
      const [action]=await sql.query(`SELECT state,receipt FROM reel_followup_instagram_flow_actions
        WHERE ig_account_id=$1 AND action_id=$2`,[v.ig_account_id,v.action_id]);
      process.stdout.write(JSON.stringify({claimed:inserted.length===1,...action})+'\n');continue;
    }
    if (input.flow_action_finish) {
      const v=input.flow_action_finish;
      if (!['sent','rejected','review'].includes(v.state)) throw Error('Invalid action state');
      await sql.query(`UPDATE reel_followup_instagram_flow_actions SET state=$3,receipt=$4::jsonb,updated_at=now()
        WHERE ig_account_id=$1 AND action_id=$2 AND state='attempting'`,[v.ig_account_id,v.action_id,v.state,JSON.stringify(v.receipt || {})]);
      process.stdout.write(JSON.stringify({recorded:true})+'\n');continue;
    }
    if (input.flow_contact_get) {
      const v=input.flow_contact_get;
      const [contact]=await sql.query(`SELECT opened,link_sent,inbound_at,media_id FROM reel_followup_instagram_contacts
        WHERE ig_account_id=$1 AND recipient_id=$2`,[v.ig_account_id,v.recipient_id]);
      const [history]=await sql.query(`WITH outgoing AS (
        SELECT payload FROM ${table}
        WHERE ig_account_id=$1 AND record_type='message' AND payload->'from'->>'id'=$1
          AND EXISTS(SELECT 1 FROM jsonb_array_elements(coalesce(payload->'to'->'data','[]'::jsonb)) r WHERE r->>'id'=$2)
      ) SELECT EXISTS(SELECT 1 FROM outgoing
          WHERE payload->>'message' ILIKE '%https://bikefitting.fit%' OR (payload->'attachments')::text ILIKE '%Works best in Chrome on Mac/Windows%') AS received_link,
        EXISTS(SELECT 1 FROM outgoing,
          jsonb_array_elements(coalesce(payload->'attachments'->'data','[]'::jsonb)) a,
          jsonb_array_elements(coalesce(a->'generic_template'->'cta','[]'::jsonb)) b
          WHERE b->>'type'='postback' AND lower(trim(b->>'title')) IN
            ('send me the link','send mir den link','following','ich folge','ich folge dir')) AS received_opening`,
        [v.ig_account_id,v.recipient_id]);
      const [opening]=await sql.query(`SELECT receipt FROM reel_followup_instagram_flow_actions
        WHERE ig_account_id=$1 AND action_id LIKE 'mc-opening:%' AND state='sent' AND receipt->>'recipient_id'=$2 LIMIT 1`,[v.ig_account_id,v.recipient_id]);
      process.stdout.write(JSON.stringify({contact:{opened:Boolean(contact?.opened || opening || history.received_opening),
        link_sent:Boolean(contact?.link_sent || history.received_link),inbound_at:contact?.inbound_at || 0,media_id:contact?.media_id || ''}})+'\n');continue;
    }
    if (input.flow_contact_put) {
      const v=input.flow_contact_put;
      await sql.query(`INSERT INTO reel_followup_instagram_contacts (ig_account_id,recipient_id,opened,link_sent,inbound_at,media_id)
        VALUES($1,$2,$3,$4,$5,$6) ON CONFLICT(ig_account_id,recipient_id) DO UPDATE SET
        opened=reel_followup_instagram_contacts.opened OR EXCLUDED.opened,
        link_sent=reel_followup_instagram_contacts.link_sent OR EXCLUDED.link_sent,
        inbound_at=greatest(reel_followup_instagram_contacts.inbound_at,EXCLUDED.inbound_at),
        media_id=CASE WHEN EXCLUDED.media_id='' THEN reel_followup_instagram_contacts.media_id ELSE EXCLUDED.media_id END,updated_at=now()`,
        [v.ig_account_id,v.recipient_id,Boolean(v.opened),Boolean(v.link_sent),Number(v.inbound_at || 0),v.media_id || '']);
      process.stdout.write(JSON.stringify({recorded:true})+'\n');continue;
    }
    if (input.overview || input.targets) {
      const args = [String(input.ig_account_id || ''),String(input.rule_key || ''),String(input.phrase || '')];
      if (input.targets) {
        const retryFilter = input.retry_rejected ? "OR (status='rejected' AND inbound_time>now()-interval '24 hours')" : '';
        const targets = await sql.query(`${chatView} SELECT conversation_id,record_id AS source_message_id,recipient_id,username
          FROM classified WHERE is_match AND (status='ready' ${retryFilter}) ORDER BY message_created_at DESC`,args);
        process.stdout.write(JSON.stringify({ targets }) + '\n');
      } else {
        const [stats] = await sql.query(`${chatView} SELECT
          (SELECT count(*)::int FROM ${table} WHERE ig_account_id=$1 AND record_type='conversation') AS conversations,
          (SELECT count(*)::int FROM ${table} WHERE ig_account_id=$1 AND record_type='message') AS messages,
          (SELECT count(*)::int FROM ${table} WHERE ig_account_id=$1 AND record_type='conversation' AND payload->>'archive_sync_state'='incomplete') AS unavailable,
          count(*) FILTER (WHERE is_match)::int AS matches,count(*) FILTER (WHERE is_match AND status='ready')::int AS eligible,
          count(*) FILTER (WHERE is_match AND status='window_closed')::int AS window_closed,
          count(*) FILTER (WHERE delivery_state='sent')::int AS sent,
          count(*) FILTER (WHERE delivery_state='rejected')::int AS rejected,
          count(*) FILTER (WHERE delivery_state IN ('review','attempting','rejected'))::int AS needs_review FROM classified`,args);
        const matchesOnly = input.view !== 'all';
        const page = Math.max(0,Number(input.page) || 0);
        const filter = matchesOnly ? '(is_match OR delivery_state IS NOT NULL)' : 'true';
        const [total] = await sql.query(`${chatView} SELECT count(*)::int AS n FROM classified WHERE ${filter}`,args);
        const rows = await sql.query(`${chatView} SELECT conversation_id,recipient_id,username,preview,
          message_created_at AS latest_at,inbound_time,status,delivery_detail FROM classified WHERE ${filter}
          ORDER BY message_created_at DESC NULLS LAST LIMIT 30 OFFSET $4`,[...args,page*30]);
        process.stdout.write(JSON.stringify({ stats,rows,total:total.n,page }) + '\n');
      }
      continue;
    }
    if (input.claim) {
      const v = input.claim;
      const rows = await sql.query(`INSERT INTO ${deliveries}
        (ig_account_id,conversation_id,rule_key,recipient_id,source_message_id,state)
        VALUES ($1,$2,$3,$4,$5,'attempting') ON CONFLICT (ig_account_id,conversation_id,rule_key) DO UPDATE
        SET state='attempting',source_message_id=EXCLUDED.source_message_id,updated_at=now()
        WHERE ${deliveries}.state='rejected' AND $6::boolean RETURNING conversation_id`,
        [v.ig_account_id,v.conversation_id,v.rule_key,v.recipient_id,v.source_message_id,Boolean(v.retry_rejected)]);
      process.stdout.write(JSON.stringify({ claimed:rows.length===1 }) + '\n');
      continue;
    }
    if (input.finish) {
      const v = input.finish;
      if (!['sent','review','rejected'].includes(v.state)) throw Error('Invalid delivery state');
      await sql.query(`UPDATE ${deliveries} SET state=$4,receipt=$5::jsonb,detail=$6,updated_at=now()
        WHERE ig_account_id=$1 AND conversation_id=$2 AND rule_key=$3 AND state='attempting'`,
        [v.ig_account_id,v.conversation_id,v.rule_key,v.state,JSON.stringify(v.receipt || {}),v.detail || '']);
      process.stdout.write(JSON.stringify({ recorded:true }) + '\n');
      continue;
    }
    if (input.manifest) {
      const manifest = await sql.query(`SELECT conversation_id,conversation_updated_at,payload->>'archive_sync_state' AS archive_state,
        payload->>'archive_next_cursor' AS archive_next_cursor,
        payload->>'archive_next_conversation_cursor' AS archive_next_conversation_cursor,
        payload->>'archive_schema_version' AS archive_schema_version
        FROM ${table} WHERE ig_account_id=$1 AND record_type='conversation'`, [String(input.ig_account_id || '')]);
      process.stdout.write(JSON.stringify({ manifest }) + '\n');
      continue;
    }
    if (input.index_cursor) {
      const cursor = input.index_cursor.cursor || null;
      await sql.query(`UPDATE ${table} SET payload = CASE WHEN $3::text IS NULL
        THEN payload - 'archive_next_conversation_cursor'
        ELSE jsonb_set(payload,'{archive_next_conversation_cursor}',to_jsonb($3::text),true) END,
        archived_at=now()
        WHERE ig_account_id=$1 AND conversation_id=$2 AND record_type='conversation'`,
        [String(input.index_cursor.ig_account_id || ''), String(input.index_cursor.conversation_id || ''), cursor]);
      process.stdout.write(JSON.stringify({ checkpoint: true }) + '\n');
      continue;
    }
    const rows = Array.isArray(input.records) ? input.records : [];
    let saved = 0;
    for (let offset = 0; offset < rows.length; offset += 100) {
      const chunk = rows.slice(offset, offset + 100);
      const params = [];
      const values = chunk.map((row) => {
        const start = params.length;
        params.push(row.ig_account_id, row.conversation_id, row.record_type, row.record_id,
          row.conversation_updated_at || null, row.message_created_at || null,
          JSON.stringify(row.participants || []), JSON.stringify(row.payload));
        return `($${start + 1},$${start + 2},$${start + 3},$${start + 4},$${start + 5},$${start + 6},$${start + 7}::jsonb,$${start + 8}::jsonb,now())`;
      });
      await sql.query(`INSERT INTO ${table}
        (ig_account_id,conversation_id,record_type,record_id,conversation_updated_at,message_created_at,participants,payload,archived_at)
        VALUES ${values.join(',')}
        ON CONFLICT (ig_account_id,conversation_id,record_type,record_id) DO UPDATE SET
          conversation_updated_at=EXCLUDED.conversation_updated_at,
          message_created_at=EXCLUDED.message_created_at,
          participants=EXCLUDED.participants,
          payload=EXCLUDED.payload,
          archived_at=now()`, params);
      saved += chunk.length;
    }
    process.stdout.write(JSON.stringify({ saved }) + '\n');
  } catch {
    process.stdout.write(JSON.stringify({ error: 'The Neon archive write failed; earlier saved pages are retained.' }) + '\n');
  }
}
