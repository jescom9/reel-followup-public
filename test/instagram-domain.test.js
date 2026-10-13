const test=require('node:test'),assert=require('node:assert/strict');
const login=require('../api/instagram/login');
test('OAuth state is issued on the callback origin after a domain change',()=>{
 const old={...process.env};Object.assign(process.env,{IG_APP_ID:'456',IG_APP_SECRET:'secret',IG_REDIRECT_URI:'https://reelfollowups.app/api/instagram/callback',LOGIN_STATE_SECRET:'state-secret',REEL_PI_SERVICE_URL:'https://pi.example/',REEL_PI_SERVICE_SECRET:'s'.repeat(40)});
 const response=()=>({headers:{},setHeader(k,v){this.headers[k]=v;},end(){}});
 try{const migrated=response();login({method:'GET',headers:{host:'reel-followup.vercel.app'}},migrated);assert.equal(migrated.headers.Location,'https://reelfollowups.app/api/instagram/login');assert.equal(migrated.headers['Set-Cookie'],undefined);
 const canonical=response();login({method:'GET',headers:{host:'reelfollowups.app'}},canonical);assert.match(canonical.headers['Set-Cookie'],/ig_oauth_state=/);const url=new URL(canonical.headers.Location);assert.equal(url.hostname,'www.instagram.com');assert.equal(url.searchParams.get('redirect_uri'),'https://reelfollowups.app/api/instagram/callback');
 }finally{for(const key of Object.keys(process.env))if(!(key in old))delete process.env[key];Object.assign(process.env,old);}
});
