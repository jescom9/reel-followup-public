import {neon} from '@neondatabase/serverless';
import {createWaitlistHandler,waitlistStore} from '../lib/waitlist.mjs';
export default {
  async fetch(request){
    if(!process.env.WAITLIST_DATABASE_URL)return Response.json({error:'The waitlist is temporarily unavailable. Please try again later.'},{status:503,headers:{'Cache-Control':'no-store'}});
    const store=waitlistStore(neon(process.env.WAITLIST_DATABASE_URL));
    return createWaitlistHandler({...store,secret:process.env.LOGIN_STATE_SECRET})(request);
  }
};
