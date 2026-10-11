import {createHmac} from 'node:crypto';
const headers={'Cache-Control':'no-store','X-Content-Type-Options':'nosniff'};
export function createWaitlistHandler({save,rateLimit,secret,now=()=>Date.now()}){
  return async request=>{
    const reply=(status,value)=>Response.json(value,{status,headers});
    if(request.method!=='POST')return reply(405,{error:'Use the waitlist form.'});
    if(request.headers.get('origin')!==new URL(request.url).origin)return reply(403,{error:'Submit from this site’s waitlist form.'});
    if(!request.headers.get('content-type')?.startsWith('application/json'))return reply(415,{error:'Use the waitlist form.'});
    if(Number(request.headers.get('content-length'))>4096)return reply(413,{error:'The form is too large.'});
    let data;
    try{const raw=await request.text();if(Buffer.byteLength(raw)>4096)return reply(413,{error:'The form is too large.'});data=JSON.parse(raw);}catch{return reply(400,{error:'Could not read the form. Please try again.'});}
    if(!data||typeof data!=='object'||Array.isArray(data))return reply(400,{error:'Use the waitlist form.'});
    if(Object.keys(data).some(key=>!['email','name','instagram','consent','website'].includes(key)))return reply(400,{error:'Send only contact details; no credentials.'});
    if(typeof data.website==='string'&&data.website.trim())return reply(200,{ok:true});
    const email=typeof data.email==='string'?data.email.trim().toLowerCase():'';
    if(email.length>254||! /^[a-z0-9.!#$%&'*+\/=?^_`{|}~-]+@[a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)+$/.test(email))return reply(400,{error:'Enter a valid email address.',field:'email'});
    const name=typeof data.name==='string'?data.name.trim():'';
    const instagram=typeof data.instagram==='string'?data.instagram.trim().replace(/^@/,''):'';
    if(name.length>80||/[\x00-\x1f\x7f]/.test(name))return reply(400,{error:'Use a name with up to 80 characters.'});
    if(instagram&&!/^[a-zA-Z0-9._]{1,30}$/.test(instagram))return reply(400,{error:'Use an Instagram username with letters, numbers, dots or underscores.',field:'instagram'});
    if(data.consent!==true)return reply(400,{error:'Please agree to be contacted about assisted setup.'});
    if(!secret)return reply(503,{error:'The waitlist is temporarily unavailable. Please try again later.'});
    // Vercel overwrites this platform header. Never store the original IP.
    const ip=request.headers.get('x-vercel-forwarded-for')?.split(',')[0].trim()||'unknown';
    const bucket=Math.floor(now()/3600000);
    const key=createHmac('sha256',secret).update('waitlist:'+bucket+':'+ip).digest('hex');
    try{
      if(!await rateLimit(key,bucket))return reply(429,{error:'Too many attempts. Please try again in an hour.'});
      await save({email,name,instagram,consent:true});
      return reply(200,{ok:true,message:'You’re on the waitlist.'});
    }catch{return reply(503,{error:'The waitlist could not save your details. Please try again later.'});}
  };
}
export async function prepareWaitlist(sql){
  await sql.query(`CREATE TABLE IF NOT EXISTS reel_followup_waitlist (
    email text PRIMARY KEY,name text NOT NULL DEFAULT '',instagram text NOT NULL DEFAULT '',
    consent boolean NOT NULL CHECK(consent),created_at timestamptz NOT NULL DEFAULT now())`);
  await sql.query(`CREATE TABLE IF NOT EXISTS reel_followup_waitlist_rate_limit (
    request_key text PRIMARY KEY,hour_bucket bigint NOT NULL,attempts integer NOT NULL DEFAULT 1)`);
}
export function waitlistStore(sql){
  return {
    save:async data=>{await sql.query(`INSERT INTO reel_followup_waitlist(email,name,instagram,consent)
      VALUES($1,$2,$3,true) ON CONFLICT(email) DO NOTHING`,[data.email,data.name,data.instagram]);},
    rateLimit:async(key,bucket)=>{
      const rows=await sql.query(`INSERT INTO reel_followup_waitlist_rate_limit(request_key,hour_bucket,attempts) VALUES($1,$2,1)
        ON CONFLICT(request_key) DO UPDATE SET attempts=reel_followup_waitlist_rate_limit.attempts+1
        WHERE reel_followup_waitlist_rate_limit.attempts<10 RETURNING attempts`,[key,bucket]);
      return rows.length>0;
    }
  };
}
