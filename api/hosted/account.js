const {config}=require('../../lib/instagram-oauth');
const {session,cookie}=require('../../lib/hosted-session');
const {piRequest}=require('../../lib/pi-service');
module.exports=async function account(req,res){
  res.setHeader('Cache-Control','no-store');res.setHeader('X-Content-Type-Options','nosniff');
  let cfg;try{cfg=config();}catch{return res.status(503).json({error:'The connection service is not ready.'});}
  let user;try{user=session(req,cfg.stateSecret);}catch{user=null;}
  if(!user)return res.status(401).json({error:'Sign in with Instagram to open your account.'});
  if(!['GET','POST'].includes(req.method))return res.status(405).json({error:'Method not allowed.'});
  if(req.method==='GET'){
    try{return res.status(200).json(await piRequest('/host/portal',{account_id:user.sub,operation:'status'}));}
    catch{return res.status(503).json({error:'Your Pi workspace is temporarily unavailable. Please try again.'});}
  }
  if(req.headers.origin!==new URL(cfg.redirectUri).origin)return res.status(403).json({error:'Submit changes from your dashboard.'});
  const data=req.body;
  if(!data||typeof data!=='object'||Array.isArray(data)||Buffer.byteLength(JSON.stringify(data))>65536)return res.status(400).json({error:'Invalid account request.'});
  if(data.operation==='logout'){res.setHeader('Set-Cookie',cookie('',0));return res.status(200).json({signed_out:true});}
  if(!['account.toggle','flows.save','flows.toggle'].includes(data.operation))return res.status(400).json({error:'Unsupported operation.'});
  try{return res.status(200).json(await piRequest('/host/portal',{account_id:user.sub,operation:data.operation,data:data.data}));}
  catch(error){return res.status(400).json({error:error.userMessage||'The change could not be saved. Check the flow settings and account pause state.'});}
};
