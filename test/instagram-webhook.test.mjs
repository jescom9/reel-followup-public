import test from 'node:test';
import assert from 'node:assert/strict';
import {createHmac} from 'node:crypto';
import {createWebhookHandler,webhookEvents,webhookAccounts} from '../lib/instagram-webhook.mjs';

const secret='test-webhook-secret',accountId='business';
function signed(body) {
  const raw=JSON.stringify(body);
  return new Request('https://example.test/api/instagram/webhook',{method:'POST',body:raw,
    headers:{'Content-Type':'application/json','x-hub-signature-256':'sha256='+createHmac('sha256',secret).update(raw).digest('hex')}});
}
const comment={object:'instagram',entry:[{id:accountId,changes:[{field:'comments',value:{id:'comment-1',text:'Fit',from:{id:'customer'},media:{id:'reel'}}}]}]};
test('returns the verification challenge only for the correct private token',async()=>{
  const handle=createWebhookHandler({accountId,verifyToken:'verify',secrets:[secret],save:async()=>0});
  assert.equal((await handle(new Request('https://example.test/?hub.mode=subscribe&hub.verify_token=wrong&hub.challenge=123'))).status,403);
  const response=await handle(new Request('https://example.test/?hub.mode=subscribe&hub.verify_token=verify&hub.challenge=123'));
  assert.equal(response.status,200);assert.equal(await response.text(),'123');
});
test('rejects a modified signature before any storage',async()=>{
  let saves=0;const handle=createWebhookHandler({accountId,verifyToken:'verify',secrets:[secret],save:async()=>{saves++;}});
  const request=signed(comment);request.headers.set('x-hub-signature-256','sha256='+ '0'.repeat(64));
  assert.equal((await handle(request)).status,403);assert.equal(saves,0);
});
test('saves valid events and makes retryable storage errors visible to Meta',async()=>{
  let events;const handle=createWebhookHandler({accountId,verifyToken:'verify',secrets:[secret],save:async e=>{events=e;return e.length;}});
  assert.equal((await handle(signed(comment))).status,200);assert.equal(events[0].id,'comment:comment-1');
  const failed=createWebhookHandler({accountId,verifyToken:'verify',secrets:[secret],save:async()=>{throw Error('DB unavailable');}});
  assert.equal((await failed(signed(comment))).status,503);
});
test('ignores other accounts and echo messages; canonicalizes a verified account alias',()=>{
  assert.equal(webhookEvents({...comment,entry:[{...comment.entry[0],id:'other'}]},accountId).length,0);
  const body={object:'instagram',entry:[{id:'scope-business',messaging:[
    {sender:{id:'customer'},recipient:{id:'scope-business'},timestamp:123,postback:{payload:'BF_LINK',title:'Send me the link'}},
    {sender:{id:'customer'},recipient:{id:'scope-business'},message:{mid:'echo',is_echo:true}},
    {sender:{id:'business'},recipient:{id:'scope-business'},message:{mid:'self'}}]}]};
  const events=webhookEvents(body,accountId,['scope-business']);
  assert.equal(events.length,1);assert.equal(events[0].payload.value.recipient.id,accountId);
  assert.equal(events[0].id,webhookEvents(body,accountId,['scope-business'])[0].id);
});
test('separate postback clicks on the same template remain distinct while duplicate delivery stays stable',()=>{
  const event={sender:{id:'customer'},recipient:{id:accountId},timestamp:123,postback:{mid:'template-message-id',payload:'BF_LINK',title:'Send me the link'}};
  const body={object:'instagram',entry:[{id:accountId,messaging:[event,{...event,timestamp:124}]}]};
  const events=webhookEvents(body,accountId);
  assert.notEqual(events[0].id,events[1].id);
  assert.equal(events[0].id,webhookEvents(body,accountId)[0].id);
});

test('routes one signed batch to the correct account partitions and ignores unregistered accounts',async()=>{
  const registry=webhookAccounts({IG_WEBHOOK_ACCOUNTS:JSON.stringify([
    {accountId:'creator-a',aliases:['scoped-a']},{accountId:'creator-b'}])});
  const saved=[];
  const handle=createWebhookHandler({accounts:registry,verifyToken:'verify',secrets:[secret],save:async(events,id)=>{
    saved.push({id,events});return events.length;
  }});
  const entry=id=>({...comment.entry[0],id});
  const response=await handle(signed({object:'instagram',entry:[entry('scoped-a'),entry('creator-b'),entry('unregistered')]}));
  assert.equal(response.status,200);
  assert.equal((await response.json()).events,2);
  assert.deepEqual(saved.map(x=>x.id),['creator-a','creator-b']);
  assert.equal(saved[0].events[0].id,saved[1].events[0].id);
});

test('rejects registries that could route one identity into two accounts',()=>{
  for (const registry of [[],{},[{accountId:'a',aliases:['b']},{accountId:'b'}],[{accountId:'a',aliases:'b'}]]) {
    assert.throws(()=>webhookAccounts({IG_WEBHOOK_ACCOUNTS:JSON.stringify(registry)}));
  }
  assert.deepEqual(webhookAccounts({IG_WEBHOOK_ACCOUNT_ID:'a',IG_WEBHOOK_ACCOUNT_ALIASES:' b, c '}),[
    {accountId:'a',aliases:['b','c']}]);
});

test('accepts legacy redundant aliases within one account',()=>{
  assert.deepEqual(webhookAccounts({IG_WEBHOOK_ACCOUNT_ID:'a',IG_WEBHOOK_ACCOUNT_ALIASES:'a,b,b'}),[
    {accountId:'a',aliases:['b']}]);
  assert.throws(()=>webhookAccounts({IG_WEBHOOK_ACCOUNTS:JSON.stringify([
    {accountId:'a',aliases:['a','b','b']},{accountId:'b'}])}));
});

test('additional app-signed accounts enter isolated partitions only after signature verification',async()=>{
  const saved=[];const handle=createWebhookHandler({accounts:[],acceptAuthorizedAccounts:true,verifyToken:'verify',secrets:[secret],save:async(events,id)=>{saved.push(id);return events.length;}});
  const body={object:'instagram',entry:[{...comment.entry[0],id:'222'},{...comment.entry[0],id:'333'}]};
  assert.equal((await handle(signed(body))).status,200);assert.deepEqual(saved,['222','333']);
  const bad=signed(body);bad.headers.set('x-hub-signature-256','sha256=bad');
  assert.equal((await handle(bad)).status,403);assert.deepEqual(saved,['222','333']);
});
