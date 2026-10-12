import test from 'node:test';import assert from 'node:assert/strict';import {piEventRouter} from '../lib/pi-event-router.mjs';
test('legacy accounts retain their queue and only new connected accounts route to Pi',async()=>{
 const legacy=[],pi=[];const route=piEventRouter({legacyAccounts:[{accountId:'111',aliases:['112']}],saveLegacy:async(events,id)=>{legacy.push(id);return events.length;},sendPi:async data=>{pi.push(data.account_id);return {managed:data.account_id==='222',saved:1};}});
 assert.equal(await route([{}],'111'),1);assert.equal(await route([{}],'112'),1);assert.deepEqual(pi,[]);assert.equal(await route([{}],'222'),1);assert.equal(await route([{}],'999'),0);assert.deepEqual(legacy,['111','112']);
});
test('offline Pi deliveries remain retryable without putting new account events in legacy storage',async()=>{
 let saved=false;const route=piEventRouter({legacyAccounts:[],saveLegacy:async()=>{saved=true;},sendPi:async()=>{throw Error('offline');}});await assert.rejects(route([{}],'222'));assert.equal(saved,false);
});
test('an explicit migration moves the account and its aliases without changing other legacy accounts',async()=>{
 const legacy=[],pi=[];const route=piEventRouter({legacyAccounts:[{accountId:'111',aliases:['112']},{accountId:'333',aliases:[]}],hostedAccountIds:['111','112'],saveLegacy:async(events,id)=>{legacy.push(id);return events.length;},sendPi:async data=>{pi.push(data.account_id);return {managed:true,saved:1};}});
 assert.equal(await route([{}],'111'),1);assert.equal(await route([{}],'112'),1);assert.equal(await route([{}],'333'),1);
 assert.deepEqual(pi,['111','112']);assert.deepEqual(legacy,['333']);
});
