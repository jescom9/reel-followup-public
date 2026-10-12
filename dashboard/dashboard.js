const $=s=>document.querySelector(s);let account,loading=false,editingId=null;
async function api(operation,data){const response=await fetch('/api/hosted/account',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({operation,data})});const result=await response.json();if(!response.ok)throw Error(result.error);return result;}
function button(text,action){const b=document.createElement('button');b.type='button';b.className='button secondary';b.textContent=text;b.onclick=async()=>{b.disabled=true;try{await action();await load();}catch(error){showError(error.message);}finally{b.disabled=false;}};return b;}
function showError(message){$('#account-error').textContent=message;$('#account-error').hidden=false;}
async function load(){
  if(loading)return;loading=true;
  try{const response=await fetch('/api/hosted/account',{cache:'no-store'});const data=await response.json();if(!response.ok){if(response.status===401){$('#account-title').textContent='Sign in to your account';$('#sign-in').hidden=false;$('#account-controls').hidden=true;}throw Error(data.error);}
    account=data;$('#account-error').hidden=true;$('#account-controls').hidden=false;$('#sign-in').hidden=true;$('#account-title').textContent='@'+data.username;
    $('#connection-state').textContent=data.reserved?'This account runs on another installation. Contact the host to migrate it.':data.enabled?'Account active. Enabled flows can run.':'Account paused. Review your flows before activating.';
    $('#account-toggle').textContent=data.enabled?'Pause account':'Resume account';$('#account-toggle').disabled=data.reserved;
    const history=data.history;$('#history-summary').textContent=history?`${number(history.contacts)} contacts · ${number(history.conversations)} conversations · ${number(history.messages)} saved messages · ${number(history.reached)} contacts reached`:'Your archive is available in the private Pi dashboard. Contact the host to enable it here.';
    $('#history-browser').hidden=!history;if(history)await loadContacts();
    $('#flow-list').replaceChildren(...data.flows.map(flow=>{const card=document.createElement('article');card.className='choice';const h=document.createElement('h3'),p=document.createElement('p');h.textContent=flow.name;p.textContent=flow.keywords.join(', ')+' · '+(flow.enabled?'active':'paused')+' · follow-ups '+(flow.enabled&&flow.followup_enabled?'active':flow.enabled?'paused':'paused with flow');card.append(h,p,button('Edit flow',()=>edit(flow)),
      button(flow.enabled?'Pause flow':'Resume flow',()=>api('flows.toggle',{id:flow.id,setting:'enabled',value:!flow.enabled})),
      button(flow.followup_enabled?'Pause follow-ups':'Resume follow-ups',()=>api('flows.toggle',{id:flow.id,setting:'followup_enabled',value:!flow.followup_enabled})));return card;}));
  }catch(error){showError(error.message);}finally{loading=false;}
}
$('#account-toggle').onclick=async()=>{try{await api('account.toggle',{enabled:!account.enabled});await load();}catch(error){showError(error.message);}};
$('#logout').onclick=async()=>{try{await api('logout');location.href='/';}catch(error){showError(error.message);}};
function edit(flow){editingId=flow.id;const form=$('#new-flow');for(const name of ['name','link_url','opening_text','follow_text','link_text','button_text','followup_text','followup_delay_minutes'])form.elements[name].value=flow[name];form.elements.keywords.value=flow.keywords.join(', ');form.elements.require_follow.checked=flow.require_follow;$('#editor-title').textContent='Edit '+flow.name;form.querySelector('button[type=submit]').textContent='Save flow changes';$('#cancel-edit').hidden=false;form.scrollIntoView({block:'start',behavior:'instant'});}
$('#cancel-edit').onclick=()=>{editingId=null;$('#new-flow').reset();$('#editor-title').textContent='Add a paused flow';$('#new-flow').querySelector('button[type=submit]').textContent='Save paused flow';$('#cancel-edit').hidden=true;};
$('#new-flow').onsubmit=async event=>{event.preventDefault();const form=event.target,b=form.querySelector('button[type=submit]');b.disabled=true;b.textContent='Saving…';
  try{const values=Object.fromEntries(new FormData(form));const existing=editingId?account.flows.find(f=>f.id===editingId):null;const flow={...existing,...values,id:existing?existing.id:crypto.randomUUID().replaceAll('-',''),keywords:values.keywords.split(',').map(v=>v.trim()),enabled:existing?existing.enabled:false,require_follow:form.elements.require_follow.checked,link_button:true,public_reply:true,public_reply_text:'Sent you a message! Check your DMs.',followup_enabled:existing?existing.followup_enabled:false,followup_delay_minutes:Number(values.followup_delay_minutes)};
    if(existing){flow.link_button=existing.link_button;flow.public_reply=existing.public_reply;flow.public_reply_text=existing.public_reply_text;}
    await api('flows.save',{flows:existing?account.flows.map(f=>f.id===existing.id?flow:f):[...account.flows,flow]});$('#flow-message').textContent=existing?'Flow changes saved.':'Flow saved, paused.';await load();
  }catch(error){showError(error.message);}finally{b.disabled=false;b.textContent=editingId?'Save flow changes':'Save paused flow';}
};
let contactPage=0,contactSearch='',conversationId=null,messagePage=0,historyLoading=false;
const number=value=>new Intl.NumberFormat().format(value||0);
const date=value=>value?new Date(value).toLocaleString():'Date unavailable';
async function loadContacts(){
 if(historyLoading)return;historyLoading=true;$('#contacts-prev').disabled=true;$('#contacts-next').disabled=true;$('#contact-list').setAttribute('aria-busy','true');$('#history-state').textContent='Loading contacts…';$('#history-error').hidden=true;
 try{const data=await api('archive.list',{page:contactPage,search:contactSearch});$('#history-state').textContent=data.total?'':'No saved contacts match this search. Try another username or refresh the list.';
  $('#contact-list').replaceChildren(...data.rows.map(row=>{const card=document.createElement('article');card.className='contact-card';const title=document.createElement('h3'),preview=document.createElement('p'),when=document.createElement('time');title.textContent='@'+row.username;preview.textContent=row.preview||'[Attachment]';when.textContent=date(row.latest_at);card.append(title,when,preview,button('View conversation',()=>openConversation(row)));return card;}));
  $('#contacts-page').textContent=data.total?`${number(contactPage*30+1)}–${number(Math.min((contactPage+1)*30,data.total))} of ${number(data.total)}`:'0 contacts';$('#contacts-prev').disabled=contactPage===0;$('#contacts-next').disabled=(contactPage+1)*30>=data.total;
 }catch(error){$('#history-state').textContent='';$('#history-error').textContent=error.message||'Could not load your history. Try Refresh.';$('#history-error').hidden=false;}
 finally{historyLoading=false;$('#contact-list').removeAttribute('aria-busy');}
}
async function openConversation(row){conversationId=row.conversation_id;messagePage=0;$('#conversation-title').textContent='Conversation with @'+row.username;$('#conversation-view').hidden=false;await loadMessages();$('#conversation-view').scrollIntoView({block:'start',behavior:'instant'});}
async function loadMessages(){
 $('#conversation-state').textContent='Loading messages…';$('#conversation-messages').setAttribute('aria-busy','true');$('#messages-newer').disabled=true;$('#messages-older').disabled=true;
 try{const data=await api('archive.conversation',{conversation_id:conversationId,page:messagePage});$('#conversation-state').textContent=data.messages.length?'':'No saved messages in this conversation.';
  $('#conversation-messages').replaceChildren(...data.messages.map(message=>{const card=document.createElement('article');card.className='chat-message'+(message.outgoing?' outgoing':'');const text=document.createElement('p'),meta=document.createElement('small');text.textContent=message.text;meta.textContent=(message.outgoing?'You':'@'+message.sender)+' · '+date(message.created_at);card.append(text,meta);return card;}));
  $('#messages-page').textContent=`Page ${number(messagePage+1)} · ${number(data.total)} messages`;$('#messages-newer').disabled=messagePage===0;$('#messages-older').disabled=(messagePage+1)*30>=data.total;
 }catch(error){$('#conversation-state').textContent=(error.message||'Could not load messages.')+' Use View conversation to try again.';}
 finally{$('#conversation-messages').removeAttribute('aria-busy');}
}
$('#contact-search').onsubmit=event=>{event.preventDefault();contactSearch=$('#contact-query').value.trim();contactPage=0;loadContacts();};
$('#refresh-history').onclick=()=>loadContacts();$('#contacts-prev').onclick=()=>{contactPage--;loadContacts();};$('#contacts-next').onclick=()=>{contactPage++;loadContacts();};
$('#close-conversation').onclick=()=>{$('#conversation-view').hidden=true;conversationId=null;};$('#messages-newer').onclick=()=>{messagePage--;loadMessages();};$('#messages-older').onclick=()=>{messagePage++;loadMessages();};
load();
