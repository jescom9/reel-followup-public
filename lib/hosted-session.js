const crypto=require('node:crypto');
const {mac,safeEqual,cookies}=require('./instagram-oauth');
const NAME='__Host-reel_session';
function issue(accountId,secret,now=Date.now()/1000){
  if(!/^\d+$/.test(accountId)||!secret)throw Error('Invalid account session.');
  const payload=Buffer.from(JSON.stringify({sub:accountId,exp:Math.floor(now)+7200,id:crypto.randomBytes(16).toString('hex')})).toString('base64url');
  return payload+'.'+mac('reel-session-v1:'+payload,secret);
}
function verify(value,secret,now=Date.now()/1000){
  if(!value||value.length>1024||!secret)return null;
  const [payload,signature,...extra]=value.split('.');
  if(extra.length||!safeEqual(signature,mac('reel-session-v1:'+payload,secret)))return null;
  try{const data=JSON.parse(Buffer.from(payload,'base64url'));return /^\d+$/.test(data.sub)&&data.exp>now?data:null;}catch{return null;}
}
function cookie(value,maxAge=7200){return `${NAME}=${encodeURIComponent(value)}; HttpOnly; Secure; SameSite=Lax; Path=/; Max-Age=${maxAge}`;}
function session(req,secret){return verify(cookies(req)[NAME],secret);}
module.exports={issue,verify,cookie,session};
