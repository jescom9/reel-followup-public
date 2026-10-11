import test from 'node:test';
import assert from 'node:assert/strict';
import {createHmac} from 'node:crypto';
import {createForwardHandler} from '../lib/instagram-forward.mjs';
const secret='test-signing-secret',raw='{"object":"instagram","entry":[]}';
function request(signature){return new Request('https://example.test/api/instagram/webhook',{method:'POST',body:raw,headers:{'X-Hub-Signature-256':signature||'sha256='+createHmac('sha256',secret).update(raw).digest('hex')}});}
test('direct forwarding preserves signed bytes without any Neon connection',async()=>{
  let received;
  const handle=createForwardHandler({url:'https://test-pi.example/webhook',verifyToken:'verify',secrets:[secret],fetchImpl:async(url,init)=>{received=init;return Response.json({accepted:true});}});
  assert.equal((await handle(request())).status,200);assert.equal(received.body.toString(),raw);
  assert.equal(received.headers['X-Hub-Signature-256'],request().headers.get('x-hub-signature-256'));
});
test('invalid signatures never reach the Pi and failed delivery remains retryable',async()=>{
  let calls=0;const handle=createForwardHandler({url:'https://test-pi.example/webhook',verifyToken:'verify',secrets:[secret],fetchImpl:async()=>{calls++;return new Response('',{status:503});}});
  assert.equal((await handle(request('bad'))).status,403);assert.equal(calls,0);
  assert.equal((await handle(request())).status,503);assert.equal(calls,1);
});
test('dashboard and non-HTTPS forwarding targets are rejected',()=>{
  for(const url of ['http://test-pi.example/webhook','https://test-pi.example/','https://user:pass@test-pi.example/webhook'])assert.throws(()=>createForwardHandler({url}));
});
