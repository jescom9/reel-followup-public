import {createHmac,timingSafeEqual} from 'node:crypto';
function equal(a,b){const x=Buffer.from(a||''),y=Buffer.from(b||'');return x.length===y.length&&timingSafeEqual(x,y);}
export function createForwardHandler({url,verifyToken,secrets,fetchImpl=fetch}){
  const target=new URL(url);
  if(target.protocol!=='https:'||target.username||target.password||target.search||target.hash||target.pathname!=='/webhook')throw Error('Use the exact HTTPS Pi /webhook URL.');
  return async request=>{
    const headers={'Cache-Control':'no-store','X-Content-Type-Options':'nosniff'};
    if(!verifyToken||!secrets?.filter(Boolean).length)return Response.json({error:'Forwarding is not configured.'},{status:503,headers});
    const incoming=new URL(request.url);let raw,signature='';
    if(request.method==='GET'){
      if(!incoming.searchParams.has('hub.mode'))return Response.json({receiver:'instagram',delivery:'direct-to-pi',ready:true},{headers});
      if(incoming.searchParams.get('hub.mode')!=='subscribe'||!equal(incoming.searchParams.get('hub.verify_token'),verifyToken))return new Response('Verification denied.',{status:403,headers});
    }else if(request.method==='POST'){
      if(Number(request.headers.get('content-length'))>4*1024*1024)return new Response('Payload too large.',{status:413,headers});
      raw=Buffer.from(await request.arrayBuffer());
      if(raw.length>4*1024*1024)return new Response('Payload too large.',{status:413,headers});
      signature=request.headers.get('x-hub-signature-256')||'';
      if(!secrets.filter(Boolean).some(secret=>equal(signature,'sha256='+createHmac('sha256',secret).update(raw).digest('hex'))))return new Response('Signature denied.',{status:403,headers});
    }else return new Response('Method not allowed.',{status:405,headers:{...headers,Allow:'GET, POST'}});
    const destination=new URL(target);destination.search=incoming.search;
    try{
      const response=await fetchImpl(destination,{method:request.method,headers:{'Content-Type':'application/json',...(signature?{'X-Hub-Signature-256':signature}:{})},
        ...(raw?{body:raw}:{}),redirect:'error',signal:AbortSignal.timeout(15000)});
      if(!response.ok)throw Error('Receiver did not accept delivery');
      const body=await response.text();
      return new Response(body,{status:200,headers:{...headers,'Content-Type':response.headers.get('Content-Type')||'text/plain; charset=utf-8'}});
    }catch{return Response.json({error:'Pi receiver unavailable; retry delivery.'},{status:503,headers});}
  };
}
