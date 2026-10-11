const test=require('node:test'),assert=require('node:assert/strict');
const {issue,verify,cookie}=require('../lib/hosted-session');
const {piRequest}=require('../lib/pi-service');
test('private sessions expire, cannot be forged and do not contain Instagram tokens',()=>{
 const value=issue('123','secret',1000);assert.equal(verify(value,'secret',1001).sub,'123');assert.equal(verify(value,'secret',8201),null);assert.equal(verify(value+'x','secret',1001),null);assert.equal(verify(value,'wrong',1001),null);assert.match(cookie(value),/HttpOnly; Secure; SameSite=Lax/);
});
test('Pi transport sends credentials in authenticated HTTPS body with no redirects',async()=>{
 let call;await piRequest('/host/connect',{access_token:'private-test-token',account_id:'123'},{config:{url:new URL('https://pi.example/'),secret:'s'.repeat(40)},fetchImpl:async(url,options)=>{call={url,options};return Response.json({stored:true});}});
 assert.equal(call.url.href,'https://pi.example/host/connect');assert.ok(!call.url.href.includes('private-test-token'));assert.equal(call.options.redirect,'error');assert.match(call.options.headers['X-Reel-Signature'],/^[a-f0-9]{64}$/);assert.equal(JSON.parse(call.options.body).access_token,'private-test-token');
});
