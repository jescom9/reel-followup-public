const test=require('node:test'),assert=require('node:assert/strict');
const account=require('../api/hosted/account');const {issue}=require('../lib/hosted-session');
test('portal derives ownership from the cookie and rejects cross-site mutations',async()=>{
 const oldEnv={...process.env},oldFetch=global.fetch;Object.assign(process.env,{IG_APP_ID:'456',IG_APP_SECRET:'secret',IG_REDIRECT_URI:'https://example.test/api/instagram/callback',LOGIN_STATE_SECRET:'state-secret',REEL_PI_SERVICE_URL:'https://pi.example/',REEL_PI_SERVICE_SECRET:'s'.repeat(40)});
 const sent=[];global.fetch=async(url,options)=>{sent.push(JSON.parse(options.body));return Response.json({saved:true});};
 const response=()=>({headers:{},setHeader(k,v){this.headers[k]=v;},status(code){this.code=code;return this;},json(data){this.data=data;}});
 try{const req={method:'POST',headers:{origin:'https://example.test',cookie:'__Host-reel_session='+issue('123','state-secret')},body:{operation:'account.toggle',account_id:'999',data:{enabled:false,account_id:'999'}}},res=response();await account(req,res);assert.equal(res.code,200);assert.equal(sent[0].account_id,'123');
 const rejected=response();await account({...req,headers:{...req.headers,origin:'https://attacker.invalid'}},rejected);assert.equal(rejected.code,403);assert.equal(sent.length,1);
 }finally{global.fetch=oldFetch;for(const key of Object.keys(process.env))if(!(key in oldEnv))delete process.env[key];Object.assign(process.env,oldEnv);}
});
