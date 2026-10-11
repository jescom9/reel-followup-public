import {createHash,createHmac,timingSafeEqual} from 'node:crypto';

function equal(a,b) {
  const x=Buffer.from(a || ''),y=Buffer.from(b || '');
  return x.length===y.length && timingSafeEqual(x,y);
}

export function webhookEvents(body,accountId,aliases=[],now=Date.now()/1000) {
  if (body.object!=='instagram') return [];
  const own=new Set([String(accountId),...aliases.map(String)]),events=[];
  for (const entry of body.entry || []) {
    if (!own.has(String(entry.id))) continue;
    for (const change of entry.changes || []) {
      if (change.field==='comments' && change.value?.id) {
        events.push({id:'comment:'+String(change.value.id),payload:{kind:'comment',value:change.value,received:now,source:'webhook'}});
      }
    }
    for (const value of entry.messaging || []) {
      if (!own.has(String(value.recipient?.id)) || own.has(String(value.sender?.id)) || value.message?.is_echo) continue;
      const mid=value.message?.mid || value.postback?.mid;
      if (!mid && !(value.postback?.payload && value.timestamp)) continue;
      const fallback=createHash('sha256').update(JSON.stringify([value.sender?.id,accountId,value.timestamp,value.postback?.payload,value.postback?.title,mid])).digest('hex');
      const id=value.postback?.payload ? 'postback:'+fallback : 'message:'+String(mid || fallback);
      events.push({id,payload:{kind:'message',value:{...value,recipient:{...value.recipient,id:accountId}},received:now,source:'webhook'}});
    }
  }
  return events;
}

export function webhookAccounts(env) {
  const accounts=env.IG_WEBHOOK_ACCOUNTS
    ? JSON.parse(env.IG_WEBHOOK_ACCOUNTS)
    : [{accountId:env.IG_WEBHOOK_ACCOUNT_ID || '',aliases:(env.IG_WEBHOOK_ACCOUNT_ALIASES || '').split(',').map(x=>x.trim()).filter(Boolean)}];
  if (!Array.isArray(accounts) || !accounts.length) throw Error('Invalid webhook account registry');
  const seen=new Set();
  return accounts.map(account=>{
    if (!account || typeof account.accountId!=='string' || !account.accountId ||
        (account.aliases!==undefined && !Array.isArray(account.aliases))) throw Error('Invalid webhook account');
    // Legacy single-account installations also listed the canonical ID as an alias.
    const aliases=[...new Set(account.aliases || [])].filter(id=>id!==account.accountId);
    for (const id of [account.accountId,...aliases]) {
      if (typeof id!=='string' || !id || seen.has(id)) throw Error('Duplicate or invalid webhook account ID');
      seen.add(id);
    }
    return {accountId:account.accountId,aliases};
  });
}

export function createWebhookHandler({verifyToken,secrets,accountId,aliases=[],accounts,acceptAuthorizedAccounts=false,save}) {
  const registry=accounts || [{accountId,aliases}];
  const headers={'Cache-Control':'no-store','X-Content-Type-Options':'nosniff'};
  return async function handle(request) {
    if (!verifyToken || (!acceptAuthorizedAccounts && (!registry.length || registry.some(a=>!a.accountId))) || !secrets?.filter(Boolean).length) return Response.json({error:'Webhook is not configured.'},{status:503,headers});
    const url=new URL(request.url);
    if (request.method==='GET') {
      if (!url.searchParams.has('hub.mode')) return Response.json({receiver:'instagram',ready:true},{headers});
      const challenge=url.searchParams.get('hub.challenge') || '';
      if (url.searchParams.get('hub.mode')!=='subscribe' || !equal(url.searchParams.get('hub.verify_token'),verifyToken) || challenge.length>1024) {
        return new Response('Verification denied.',{status:403,headers});
      }
      return new Response(challenge,{headers:{...headers,'Content-Type':'text/plain; charset=utf-8'}});
    }
    if (request.method!=='POST') return new Response('Method not allowed.',{status:405,headers:{...headers,Allow:'GET, POST'}});
    if (Number(request.headers.get('content-length'))>4*1024*1024) return new Response('Payload too large.',{status:413,headers});
    const raw=Buffer.from(await request.arrayBuffer());
    if (raw.length>4*1024*1024) return new Response('Payload too large.',{status:413,headers});
    const signature=request.headers.get('x-hub-signature-256') || '';
    const valid=secrets.filter(Boolean).some(secret=>equal(signature,'sha256='+createHmac('sha256',secret).update(raw).digest('hex')));
    if (!valid) return new Response('Signature denied.',{status:403,headers});
    let body;
    try {body=JSON.parse(raw.toString('utf8'));}
    catch {return new Response('Invalid JSON.',{status:400,headers});}
    try {
      let saved=0;
      for (const account of registry) {
        const events=webhookEvents(body,account.accountId,account.aliases || []);
        if (events.length) saved+=await save(events,account.accountId);
      }
      if (acceptAuthorizedAccounts && body?.object==='instagram') {
        const registered=new Set(registry.flatMap(a=>[a.accountId,...(a.aliases || [])]));
        for (const entry of body.entry || []) {
          const id=String(entry.id || '');
          if (!/^\d+$/.test(id) || registered.has(id)) continue;
          const aliases=(entry.messaging || []).map(v=>String(v.recipient?.id || '')).filter(v=>/^\d+$/.test(v));
          const events=webhookEvents({object:'instagram',entry:[entry]},id,aliases);
          if(events.length)saved+=await save(events,id);
        }
      }
      return Response.json({accepted:true,events:saved},{headers});
    } catch {
      // Meta retries unsuccessful deliveries; acknowledge only after the durable save.
      return Response.json({error:'Event storage unavailable; retry delivery.'},{status:503,headers});
    }
  };
}
