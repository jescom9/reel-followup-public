const crypto=require('node:crypto');
function serviceConfig(){
  const url=new URL(process.env.REEL_PI_SERVICE_URL||'https://unconfigured.invalid');
  const secret=process.env.REEL_PI_SERVICE_SECRET||'';
  if(!process.env.REEL_PI_SERVICE_URL||secret.length<32||url.protocol!=='https:'||url.username||url.password||url.search||url.hash||url.pathname!=='/')throw Error('The private Pi connection is not configured.');
  return {url,secret};
}
async function piRequest(path,data,{fetchImpl=fetch,config=serviceConfig()}={}){
  if(!['/host/health','/host/connect','/host/events','/host/portal'].includes(path))throw Error('Invalid Pi operation.');
  const body=JSON.stringify(data),stamp=String(Math.floor(Date.now()/1000)),nonce=crypto.randomBytes(16).toString('hex');
  const hash=crypto.createHash('sha256').update(body).digest('hex');
  const signature=crypto.createHmac('sha256',config.secret).update(['reel-pi-v1',stamp,nonce,'POST',path,hash].join('\n')).digest('hex');
  const response=await fetchImpl(new URL(path,config.url),{method:'POST',headers:{'Content-Type':'application/json','X-Reel-Time':stamp,'X-Reel-Nonce':nonce,'X-Reel-Signature':signature},body,redirect:'error',signal:AbortSignal.timeout(20000)});
  if(!response.ok){const error=Error('The Pi could not complete the connection.');error.retryable=response.status>=500;if(path==='/host/portal'){const value=await response.json().catch(()=>({}));if(typeof value.error==='string'&&value.error.length<300)error.userMessage=value.error;}throw error;}
  const result=await response.json();
  return result;
}
module.exports={serviceConfig,piRequest};
