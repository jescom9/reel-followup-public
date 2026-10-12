export function piEventRouter({legacyAccounts,hostedAccountIds=[],sendPi,saveLegacy}){
  const legacy=new Set(legacyAccounts.flatMap(a=>[a.accountId,...(a.aliases||[])]));
  const hosted=new Set(hostedAccountIds);
  return async(events,accountId)=>{
    if(legacy.has(accountId)&&!hosted.has(accountId))return saveLegacy(events,accountId);
    const result=await sendPi({account_id:accountId,events});
    return result.managed?result.saved:0;
  };
}
