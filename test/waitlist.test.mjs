import test from 'node:test';
import assert from 'node:assert/strict';
import {createWaitlistHandler} from '../lib/waitlist.mjs';
function request(data,origin='https://example.com'){
  return new Request('https://example.com/api/waitlist',{method:'POST',headers:{origin,'content-type':'application/json','x-vercel-forwarded-for':'192.0.2.1'},body:JSON.stringify(data)});
}
const signup={email:'Example+waitlist@example.com',name:'Example',instagram:'@example.user',consent:true,website:''};
test('stores only normalized contact details and hides duplicate membership',async()=>{
  const records=new Map(),keys=[];
  const handler=createWaitlistHandler({secret:'test-only',save:async value=>{if(!records.has(value.email))records.set(value.email,value);},rateLimit:async key=>{keys.push(key);return true;}});
  const one=await handler(request(signup)),two=await handler(request(signup));
  assert.equal(one.status,200);assert.deepEqual(await one.json(),await two.json());assert.equal(records.size,1);
  assert.deepEqual([...records.values()][0],{email:'example+waitlist@example.com',name:'Example',instagram:'example.user',consent:true});
  assert.match(keys[0],/^[a-f0-9]{64}$/);assert.equal(keys[0],keys[1]);
});
test('rejects cross-site submissions, missing consent and credential fields without saving',async()=>{
  let calls=0;const handler=createWaitlistHandler({secret:'test',save:async()=>calls++,rateLimit:async()=>true});
  assert.equal((await handler(request(signup,'https://attacker.invalid'))).status,403);
  assert.equal((await handler(request({...signup,consent:false}))).status,400);
  assert.equal((await handler(request({...signup,access_token:'never-store'}))).status,400);
  const response=await handler(request({...signup,email:'invalid'}));assert.equal(response.status,400);assert.equal((await response.json()).field,'email');
  assert.equal(calls,0);
});
test('fails honestly on storage errors and rate limits; honeypot saves nothing',async()=>{
  let calls=0;const blocked=createWaitlistHandler({secret:'test',save:async()=>calls++,rateLimit:async()=>false});
  assert.equal((await blocked(request(signup))).status,429);
  assert.equal((await blocked(request({...signup,website:'bot-filled'}))).status,200);assert.equal(calls,0);
  const broken=createWaitlistHandler({secret:'test',rateLimit:async()=>true,save:async()=>{throw Error('private database error');}});
  const response=await broken(request(signup));assert.equal(response.status,503);assert.ok(!(await response.text()).includes('private database'));
});
