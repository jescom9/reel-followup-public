const $ = (selector) => document.querySelector(selector);
let nonce = '';
let selectedProfile=localStorage.getItem('reel-account') || 'default',accountBusy=false,connectedAccounts=[];
let chatPage = 0, chatView = 'matches', chatLoading = false, lastBatchState = '';
const formatNumber = (value) => new Intl.NumberFormat().format(value || 0);
const states = {ready:'Ready to send',window_closed:'Window closed',sent:'Sent',review:'Needs review',attempting:'Needs review',rejected:'Rejected by Meta',not_matching:'Does not match',unknown_recipient:'Needs review'};
function renderStats(stats = {}) {
  for (const [id,key] of [['total-chats','conversations'],['total-messages','messages'],['eligible-count','eligible'],['sent-count','sent']]) note('#'+id,formatNumber(stats[key]));
  note('#match-summary',`${formatNumber(stats.matches)} chats still match · ${formatNumber(stats.window_closed)} outside the reply window · ${formatNumber(stats.needs_review)} need review. ${stats.unavailable ? formatNumber(stats.unavailable)+' histories unavailable from Meta.' : ''}`);
  $('#routing-help').hidden = !stats.rejected;
}
function renderChats(data) {
  const rows = data.rows || [];
  $('#chats').replaceChildren(...(rows.length ? rows.map((chat) => {
    const row = document.createElement('tr');
    for (const text of [chat.username ? '@'+chat.username : 'Instagram user',chat.preview || 'Photo or attachment',chat.latest_at ? new Date(chat.latest_at).toLocaleString() : 'Unknown',states[chat.status] || chat.status]) {
      const cell = document.createElement('td'); cell.textContent = text; row.append(cell);
    }
    row.lastChild.className = 'delivery-state '+chat.status;
    if (chat.delivery_detail) row.lastChild.title = chat.delivery_detail;
    return row;
  }) : [(() => { const row=document.createElement('tr'),cell=document.createElement('td'); cell.colSpan=4; cell.textContent=chatView==='matches' ? 'No matching chats yet. Sync the history to check again.' : 'No chats have been saved yet. Sync the history to get started.';row.append(cell);return row; })()]));
  $('#previous-chats').disabled = chatPage === 0;
  $('#next-chats').disabled = (chatPage+1)*30 >= data.total;
  note('#chat-page',`Page ${chatPage+1} of ${Math.max(1,Math.ceil((data.total || 0)/30))} · ${formatNumber(data.total)} chats`);
}
async function loadChats() {
  if (chatLoading) return;
  chatLoading = true; const profile=selectedProfile; $('#refresh-chats').disabled = true; $('#chat-error').hidden = true;
  try {
    const response = await fetch(`/api/chats?page=${chatPage}&view=${encodeURIComponent(chatView)}`,{cache:'no-store',headers:{'X-Reel-Account':profile}});
    const data = await response.json();if(profile!==selectedProfile)return; if (!response.ok) throw Error(data.error || 'Could not load chats.');
    renderStats(data.stats); renderChats(data);
  } catch (error) { $('#chat-error').hidden=false; note('#chat-error',error.message+' Use Refresh chats to retry.'); }
  finally { chatLoading=false; $('#refresh-chats').disabled=false; }
}
const request = async (path, data) => {
  if(accountBusy)throw Error('Wait until the account workspace has loaded.');
  const response = await fetch(path, { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Local-Token': nonce,'X-Reel-Account':selectedProfile }, body: JSON.stringify(data) });
  const result = await response.json();
  if (!response.ok) throw Error(result.error || 'Request failed');
  return result;
};
const note = (selector, value) => { const element = $(selector); if (element) element.textContent = value; };
async function refresh() {
  const profile=selectedProfile;
  const response = await fetch('/api/status', { cache: 'no-store',headers:{'X-Reel-Account':profile} });
  const data = await response.json();
  if(profile!==selectedProfile)return;
  if(!response.ok){if(response.status===404&&profile!=='default'){selectedProfile='default';localStorage.removeItem('reel-account');return refresh();}throw Error(data.error || 'Could not load this account.');}
  connectedAccounts=data.accounts || [];
  if(document.activeElement!==$('#account-selector')){const select=$('#account-selector');select.replaceChildren(...connectedAccounts.map(account=>new Option((account.username ? '@'+account.username : 'Unconnected account')+(account.enabled?' · running':' · paused'),account.profile_id)));select.value=selectedProfile;}
  nonce = data.nonce;
  const connector=$('#connector-link');
  try{const url=new URL(data.connector_url);if(url.protocol!=='https:'||url.username||url.password)throw Error();connector.href=url.href;connector.textContent='Open your Instagram connector';}
  catch{connector.href='https://reelfollowups.app/tutorial/';connector.textContent='Set up your own Meta app and Instagram connector';}
  const config = data.config;
  $('#toggle-workspace').disabled=!config.verified;$('#toggle-workspace').textContent=config.enabled?'Pause account':'Resume account';
  note('#account-state',config.enabled?'All active flows in this workspace can run.':'This account is paused; its flows and reminders do not send.');
  renderWorkflows(config.flows || [], data.workflow_stats || []);
  const manychatEnabled=config.workflow_mode==='manychat' && config.enabled;
  if (document.activeElement !== $('#mc-keyword')) $('#mc-keyword').value=config.keyword || 'Fit';
  $('#cloud-verify-token').value=config.verify_token || '';
  $('#save-manychat').disabled=!config.verified;
  $('#toggle-manychat').disabled=!config.verified;
  $('#toggle-manychat').textContent=manychatEnabled ? 'Pause webhook service' : 'Enable webhook service';
  note('#manychat-note',manychatEnabled ? 'Enabled: keyword comments on all your Reels can trigger this flow.' : config.webhook_verified ? 'Meta callback verified. The flow is paused.' : 'The flow is paused until Meta verifies the callback URL.');
  const hook=data.webhook || {},hookStats=hook.stats || {};
  const storage=data.storage || {};
  note('#storage-status',`${storage.backend==='sqlite' ? 'SQLite on this host' : 'Neon archive'} · ${storage.delivery==='direct' ? 'signed webhooks delivered to this host' : 'cloud queue delivered through Neon'}`);
  $('#cloud-webhook').value=hook.url || '';
  note('#webhook-progress',hook.state==='error' ? hook.detail : `${formatNumber(hookStats.received)} webhook events received · ${formatNumber(hookStats.pending)} waiting · ${formatNumber(hookStats.done)} processed · ${formatNumber(hookStats.review)} need review.${hookStats.last_received ? ' Last event: '+new Date(hookStats.last_received).toLocaleString() : ''}`);
  $('#credentials [name=app_id]').value = config.app_id || '';
  $('#poll-status').textContent = data.poll_status || 'Polling is paused.';
  $('#status').textContent = config.enabled ? 'Campaign enabled' : config.verified ? 'Connected · @' + config.username : 'Not connected';
  $('#status').className = 'pill ' + (config.enabled ? '' : 'off');
  $('#keyword').value = config.keyword || 'Fit';
  $('#media').dataset.selected = config.media_id || '';
  $('#toggle').disabled = !config.verified || !config.media_id || manychatEnabled;
  $('#toggle').textContent = config.enabled ? 'Pause campaign' : 'Enable campaign';
  $('#toggle').className = config.enabled ? 'secondary' : 'danger';
  $('#tunnel-origin').value = config.public_webhook_origin || '';
  $('#webhook').value = (config.public_webhook_origin || 'Enter tunnel origin above') + '/webhook';
  $('#verify-token').value = config.verify_token || '';
  const archive = data.archive || {};
  $('#archive-status').textContent = archive.detail || 'Chat archive has not synced yet.';
  $('#sync-chats').disabled = !config.verified || archive.state === 'syncing';
  $('#sync-chats').textContent = archive.state === 'syncing' ? 'Syncing all pages…' : 'Sync chat history now';
  const overview = data.dashboard || {};
  if (overview.state === 'ready') {
    renderStats(overview.stats);
    if (!chatLoading && chatPage === 0 && chatView === 'matches') renderChats(overview);
  } else if (overview.state === 'error') { $('#chat-error').hidden=false; note('#chat-error',overview.detail); }
  const followup = data.followup || {};
  note('#followup-status',followup.detail || 'Ready to check matching chats.');
  $('#send-followups').disabled = !config.verified || followup.state === 'sending' || !(overview.stats || {}).eligible;
  $('#send-followups').textContent = followup.state === 'sending' ? 'Sending follow-ups…' : `Send to ${formatNumber((overview.stats || {}).eligible)} eligible chats`;
  $('#send-followups').setAttribute('aria-busy',String(followup.state === 'sending'));
  $('#retry-rejected').disabled = followup.state === 'sending';
  if (lastBatchState === 'sending' && followup.state !== 'sending' && (chatPage || chatView !== 'matches')) loadChats();
  lastBatchState = followup.state;
  if (data.events.length) {
    $('#events').replaceChildren(...data.events.map((event) => {
      const article = document.createElement('article');
      const title = document.createElement('div');
      const detail = document.createElement('div');
      const time = document.createElement('div');
      title.className = 'event-title'; title.textContent = event.state;
      detail.className = 'event-detail'; detail.textContent = event.detail || 'Event accepted';
      time.className = 'event-time'; time.textContent = new Date(event.created * 1000).toLocaleString();
      article.append(title, detail, time);
      return article;
    }));
  }
}
async function action(fn) { try { await fn(); await refresh(); } catch (error) { alert(error.message); } }
$('#credentials').addEventListener('submit', (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  action(async () => { const result = await request('/api/config', Object.fromEntries(new FormData(form))); form.reset(); note('#connect-note', result.message); });
});
$('#verify').onclick = () => action(async () => { const result = await request('/api/verify', {}); note('#connect-note', result.message); });
$('#load-media').onclick = () => action(async () => {
  const result = await request('/api/media', {}), select = $('#media'), old = select.dataset.selected;
  select.replaceChildren(new Option('Select your Reel', ''));
  for (const media of result.media || []) { const option = new Option(`${media.caption || '(no caption)'} · ${media.permalink || media.id}`, media.id); if (media.id === old) option.selected = true; select.add(option); }
});
$('#media').onchange = () => action(async () => request('/api/config', { media_id: $('#media').value, keyword: $('#keyword').value }));
$('#keyword').onchange = () => action(async () => request('/api/config', { media_id: $('#media').value, keyword: $('#keyword').value }));
$('#toggle').onclick = () => action(async () => { const result = await request('/api/enable', { enabled: $('#toggle').textContent === 'Enable campaign' }); note('#campaign-note', result.message); });
$('#save-tunnel').onclick = () => action(async () => { const result = await request('/api/config', { public_webhook_origin: $('#tunnel-origin').value }); note('#campaign-note', result.message); });
$('#sync-chats').onclick = () => action(async () => { const result = await request('/api/sync-chats', {}); note('#archive-status', result.message); });
$('#save-manychat').onclick = () => action(async () => {
  const result=await request('/api/manychat',{keyword:$('#mc-keyword').value});note('#manychat-note',result.message);
});
$('#toggle-manychat').onclick = () => action(async () => {
  const result=await request('/api/manychat',{keyword:$('#mc-keyword').value,enabled:$('#toggle-manychat').textContent==='Enable webhook service'});note('#manychat-note',result.message);
});
$('#send-followups').onclick = () => {
  $('#send-followups').disabled = true;
  action(async () => { const result=await request('/api/followups/send',{});note('#followup-status',result.message); });
};
$('#retry-rejected').onclick = () => {
  $('#retry-rejected').disabled = true;
  action(async () => { const result=await request('/api/followups/retry-rejected',{});note('#followup-status',result.message); });
};
$('#refresh-chats').onclick = loadChats;
$('#chat-view').onchange = () => { chatView=$('#chat-view').value;chatPage=0;loadChats(); };
$('#previous-chats').onclick = () => { chatPage=Math.max(0,chatPage-1);loadChats(); };
$('#next-chats').onclick = () => { chatPage++;loadChats(); };
$('#refresh').onclick = () => action(async () => {});
refresh().catch(() => note('#status', 'Local app unavailable'));
setInterval(() => refresh().catch(() => {}), 5000);

let flowDirty=false,flowSnapshot='',savedFlows=[],flowBusy=false;
const flowFields=['name','keywords','link_url','opening_text','follow_text','link_text','button_text','public_reply_text','followup_text','followup_delay_minutes','comment_reminder_after_hours','comment_reminder_text'];
function renderWorkflows(items,stats){
  savedFlows=items;
  const signature=JSON.stringify(items);
  if(!flowDirty && signature!==flowSnapshot){
    flowSnapshot=signature;
    $('#workflow-list').replaceChildren(...items.map(flow=>{
      const card=$('#flow-template').content.firstElementChild.cloneNode(true);card.dataset.id=flow.id;
      for(const name of flowFields){card.querySelector(`[name="${name}"]`).value=name==='keywords' ? flow.keywords.join(', ') : (flow[name] ?? (name==='comment_reminder_after_hours' ? 24 : name==='comment_reminder_text' ? 'Hey, this is the official account. Check your DMs or find our link in the bio.' : ''));}
      for(const name of ['require_follow','link_button','public_reply','comment_reminder_enabled'])card.querySelector(`[name="${name}"]`).checked=flow[name];
      card.querySelector('.flow-title').textContent=flow.name;
      card.querySelector('.flow-toggle').textContent=flow.enabled?'Pause flow':'Resume flow';
      card.querySelector('.followup-toggle').textContent=flow.followup_enabled?'Pause follow-ups':'Resume follow-ups';
      card.querySelector('.flow-toggle').onclick=()=>toggleFlow(flow.id,'enabled',!flow.enabled);
      card.querySelector('.followup-toggle').onclick=()=>toggleFlow(flow.id,'followup_enabled',!flow.followup_enabled);
      card.querySelector('.delete-flow').onclick=()=>{if($('#workflow-list').children.length<=1){note('#flows-status','Keep at least one flow.');return;}card.remove();markFlowDirty();};
      return card;
    }));
  }
  for(const card of $('#workflow-list').children){
    const flow=items.find(f=>f.id===card.dataset.id);if(!flow)continue;
    const counts=stats.filter(row=>row.flow_id===flow.id);
    const count=(kind,state)=>counts.filter(row=>row.kind===kind&&row.state===state).reduce((sum,row)=>sum+Number(row.count),0);
    card.querySelector('.flow-results').textContent=`${flow.enabled?'Flow active':'Flow paused'} · ${flow.followup_enabled?'Follow-ups active':'Follow-ups paused'} · ${formatNumber(count('follow','waiting'))} follower checks waiting · ${formatNumber(count('followup','waiting'))} follow-ups scheduled · ${formatNumber(count('followup','sent'))} follow-ups sent · ${formatNumber(count('followup','waiting_inbound'))} waiting for a reply · ${formatNumber(count('followup','expired'))} reply windows closed · ${formatNumber(count('followup','review')+count('follow','review')+count('reminder','review'))} need review · ${formatNumber(count('reminder','waiting'))} comment reminders waiting · ${formatNumber(count('reminder','sent'))} reminders sent · ${formatNumber(count('reminder','blocked'))} blocked by account permissions`;
  }
}
function markFlowDirty(){flowDirty=true;note('#flows-status','Unsaved changes. Save before resuming or pausing a flow.');for(const button of document.querySelectorAll('.flow-toggle,.followup-toggle'))button.disabled=true;}
$('#workflow-editor').addEventListener('input',markFlowDirty);
function collectFlows(){return [...$('#workflow-list').children].map(card=>{
  const prior=savedFlows.find(f=>f.id===card.dataset.id)||{enabled:false,followup_enabled:true};
  const flow={id:card.dataset.id,enabled:prior.enabled,followup_enabled:prior.followup_enabled,media_scope:prior.media_scope||'all',media_ids:[...(prior.media_ids||[])]};
  for(const name of flowFields)flow[name]=card.querySelector(`[name="${name}"]`).value;
  flow.keywords=flow.keywords.split(',').map(word=>word.trim());flow.followup_delay_minutes=Number(flow.followup_delay_minutes);flow.comment_reminder_after_hours=Number(flow.comment_reminder_after_hours);flow.comment_reminder_account='self';
  for(const name of ['require_follow','link_button','public_reply','comment_reminder_enabled'])flow[name]=card.querySelector(`[name="${name}"]`).checked;
  return flow;
});}
$('#workflow-editor').onsubmit=async event=>{
  event.preventDefault();if(flowBusy)return;flowBusy=true;$('#save-flows').disabled=true;$('#save-flows').setAttribute('aria-busy','true');note('#flows-status','Saving flows…');
  try{const result=await request('/api/flows',{flows:collectFlows()});flowDirty=false;flowSnapshot='';await refresh();note('#flows-status',result.message);}
  catch(error){note('#flows-status',error.message);}
  finally{flowBusy=false;$('#save-flows').disabled=false;$('#save-flows').setAttribute('aria-busy','false');}
};
async function toggleFlow(id,setting,value){
  if(flowDirty||flowBusy)return;flowBusy=true;
  for(const button of document.querySelectorAll('.flow-toggle,.followup-toggle'))button.disabled=true;
  try{const result=await request('/api/flows/toggle',{id,setting,value});flowSnapshot='';await refresh();note('#flows-status',result.message);}
  catch(error){note('#flows-status',error.message);}
  finally{flowBusy=false;for(const button of document.querySelectorAll('.flow-toggle,.followup-toggle'))button.disabled=flowDirty;}
}
$('#add-flow').onclick=()=>{
  const card=$('#flow-template').content.firstElementChild.cloneNode(true);card.dataset.id=Array.from(crypto.getRandomValues(new Uint8Array(16)),value=>value.toString(16).padStart(2,'0')).join('');card.querySelector('.flow-title').textContent='New paused flow';
  const values={name:'New flow',keywords:'',link_url:'',opening_text:'Folge meinem Account und tippe auf Following 👇',follow_text:'Folge meinem Account und tippe danach auf Following 👇',link_text:'Hier ist dein Link:',button_text:'Open link',public_reply_text:'Sent you a message! Check it out!',followup_text:'Hi, ich hoffe, dir hat’s geholfen. Teile dein Ergebnis gerne mit deinen Freunden.',followup_delay_minutes:60,comment_reminder_after_hours:24,comment_reminder_text:'Hey, this is the official account. Check your DMs or find our link in the bio.'};
  for(const name of flowFields)card.querySelector(`[name="${name}"]`).value=values[name];
  for(const name of ['require_follow','link_button','public_reply','comment_reminder_enabled'])card.querySelector(`[name="${name}"]`).checked=name!=='comment_reminder_enabled';
  card.querySelector('details').open=true;card.querySelector('.flow-toggle').textContent='Flow paused';card.querySelector('.followup-toggle').textContent='Follow-ups active after resume';
  card.querySelector('.delete-flow').onclick=()=>{card.remove();markFlowDirty();};
  $('#workflow-list').append(card);markFlowDirty();card.querySelector('[name="name"]').focus();
};

$('#account-selector').onchange=async event=>{
  if(flowDirty||flowBusy){event.target.value=selectedProfile;note('#flows-status','Save your flow changes before switching accounts.');return;}
  selectedProfile=event.target.value;localStorage.setItem('reel-account',selectedProfile);nonce='';flowSnapshot='';chatPage=0;accountBusy=true;
  $('#chats').replaceChildren();note('#match-summary','Loading this account’s conversations…');for(const id of ['total-chats','total-messages','eligible-count','sent-count'])note('#'+id,'—');
  try{await refresh();$('#credentials [name=access_token]').value='';}
  catch(error){note('#account-error',error.message);}
  finally{accountBusy=false;}
};
$('#toggle-workspace').onclick=async()=>{
  try{const result=await request('/api/manychat',{enabled:$('#toggle-workspace').textContent==='Resume account'});await refresh();note('#account-state',result.message);}
  catch(error){note('#account-error',error.message);}
};
$('#add-account-form').onsubmit=async event=>{
  event.preventDefault();const button=$('#add-account-submit');button.disabled=true;button.setAttribute('aria-busy','true');note('#account-error','Verifying account…');
  try{const result=await request('/api/accounts/create',Object.fromEntries(new FormData(event.target)));event.target.reset();await refresh();flowSnapshot='';note('#account-error',result.message+' Choose it in the account list.');}
  catch(error){note('#account-error',error.message);}
  finally{button.disabled=false;button.setAttribute('aria-busy','false');}
};
