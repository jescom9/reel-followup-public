const test=require('node:test'),assert=require('node:assert/strict');
const callback=require('../api/instagram/callback');const {mac}=require('../lib/instagram-oauth');
test('OAuth saves on the Pi and never returns the Instagram token to the browser',async()=>{
 const oldEnv={...process.env},oldFetch=global.fetch;Object.assign(process.env,{IG_APP_ID:'456',IG_APP_SECRET:'secret',IG_REDIRECT_URI:'https://example.test/api/instagram/callback',LOGIN_STATE_SECRET:'state-secret',REEL_PI_SERVICE_URL:'https://pi.example/',REEL_PI_SERVICE_SECRET:'s'.repeat(40)});
 let saved;
 global.fetch=async(input,options={})=>{const url=new URL(input);if(url.hostname==='api.instagram.com')return Response.json({access_token:'short-test'});if(url.pathname==='/access_token')return Response.json({access_token:'private-never-display-token',expires_in:5184000});if(url.pathname==='/v22.0/me')return Response.json({user_id:'123',username:'creator'});if(url.pathname==='/host/connect'){saved=JSON.parse(options.body);return Response.json({stored:true,account_id:'123',profile_id:'workspace'});}throw Error('Unexpected request');};
 const headers={},res={setHeader(k,v){headers[k]=v;},end(body){this.body=body;}};const state='test-state';
 try{await callback({method:'GET',url:'/api/instagram/callback?state='+state+'&code=one-time',headers:{cookie:'ig_oauth_state='+state+'.'+mac(state,'state-secret')}},res);assert.equal(res.statusCode,200);assert.equal(saved.access_token,'private-never-display-token');assert.ok(!(res.body||'').includes('private-never-display-token'));assert.ok(!(res.body||'').includes('<textarea'));assert.match(headers['Set-Cookie'].join(';'),/__Host-reel_session=/);}
 finally{global.fetch=oldFetch;for(const key of Object.keys(process.env))if(!(key in oldEnv))delete process.env[key];Object.assign(process.env,oldEnv);}
});
