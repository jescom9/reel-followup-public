import {piEventRouter} from '../../lib/pi-event-router.mjs';
import piService from '../../lib/pi-service.js';
import {neon} from '@neondatabase/serverless';
import {createForwardHandler} from '../../lib/instagram-forward.mjs';
import {createWebhookHandler,webhookAccounts} from '../../lib/instagram-webhook.mjs';
import {saveWebhookEvents} from '../../lib/instagram-flow-store.mjs';

let sql;
export default {
  async fetch(request) {
    if(process.env.REEL_WEBHOOK_FORWARD_URL){
      try{
        return await createForwardHandler({url:process.env.REEL_WEBHOOK_FORWARD_URL,verifyToken:process.env.IG_WEBHOOK_VERIFY_TOKEN,
          secrets:[process.env.IG_WEBHOOK_APP_SECRET,process.env.IG_APP_SECRET]})(request);
      }catch{return Response.json({error:'Configure the exact HTTPS Pi /webhook forwarding URL.'},{status:503});}
    }
    let accounts;
    try { accounts=webhookAccounts(process.env); }
    catch { if(process.env.REEL_PI_SERVICE_URL)accounts=[];else return Response.json({error:'Webhook account registry is not configured.'},{status:503}); }
    const saveLegacy=async(events,accountId)=>{
      if(!process.env.REEL_FOLLOWUP_DATABASE_URL)throw Error('Missing event storage');
      sql ||= neon(process.env.REEL_FOLLOWUP_DATABASE_URL);return saveWebhookEvents(sql,accountId,events);
    };
    const hostedAccountIds=(process.env.REEL_PI_ACCOUNT_IDS||'').split(',').map(id=>id.trim()).filter(Boolean);
    const save=process.env.REEL_PI_SERVICE_URL?piEventRouter({legacyAccounts:accounts,hostedAccountIds,sendPi:data=>piService.piRequest('/host/events',data),saveLegacy}):saveLegacy;
    const handler=createWebhookHandler({
      accounts,acceptAuthorizedAccounts:true,
      verifyToken:process.env.IG_WEBHOOK_VERIFY_TOKEN,
      secrets:[process.env.IG_WEBHOOK_APP_SECRET,process.env.IG_APP_SECRET],
      save
    });
    return handler(request);
  }
};
