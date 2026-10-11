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
    $('#flow-list').replaceChildren(...data.flows.map(flow=>{const card=document.createElement('article');card.className='choice';const h=document.createElement('h3'),p=document.createElement('p');h.textContent=flow.name;p.textContent=flow.keywords.join(', ')+' · '+(flow.enabled?'active':'paused')+' · follow-ups '+(flow.followup_enabled?'active':'paused');card.append(h,p,button('Edit flow',()=>edit(flow)),
      button(flow.enabled?'Pause flow':'Resume flow',()=>api('flows.toggle',{id:flow.id,setting:'enabled',value:!flow.enabled})),
      button(flow.followup_enabled?'Pause follow-ups':'Resume follow-ups',()=>api('flows.toggle',{id:flow.id,setting:'followup_enabled',value:!flow.followup_enabled})));return card;}));
  }catch(error){showError(error.message);}finally{loading=false;}
}
$('#account-toggle').onclick=async()=>{try{await api('account.toggle',{enabled:!account.enabled});await load();}catch(error){showError(error.message);}};
$('#logout').onclick=async()=>{try{await api('logout');location.href='/';}catch(error){showError(error.message);}};
function edit(flow){editingId=flow.id;const form=$('#new-flow');for(const name of ['name','link_url','opening_text','follow_text','link_text','button_text','followup_text','followup_delay_minutes'])form.elements[name].value=flow[name];form.elements.keywords.value=flow.keywords.join(', ');form.elements.require_follow.checked=flow.require_follow;$('#editor-title').textContent='Edit '+flow.name;$('#cancel-edit').hidden=false;form.scrollIntoView({block:'start',behavior:'instant'});}
$('#cancel-edit').onclick=()=>{editingId=null;$('#new-flow').reset();$('#editor-title').textContent='Add a paused flow';$('#cancel-edit').hidden=true;};
$('#new-flow').onsubmit=async event=>{event.preventDefault();const form=event.target,b=form.querySelector('button[type=submit]');b.disabled=true;b.textContent='Saving…';
  try{const values=Object.fromEntries(new FormData(form));const existing=editingId?account.flows.find(f=>f.id===editingId):null;const flow={...existing,...values,id:existing?existing.id:crypto.randomUUID().replaceAll('-',''),keywords:values.keywords.split(',').map(v=>v.trim()),enabled:existing?existing.enabled:false,require_follow:form.elements.require_follow.checked,link_button:true,public_reply:true,public_reply_text:'Sent you a message! Check your DMs.',followup_enabled:existing?existing.followup_enabled:false,followup_delay_minutes:Number(values.followup_delay_minutes)};
    await api('flows.save',{flows:existing?account.flows.map(f=>f.id===existing.id?flow:f):[...account.flows,flow]});$('#flow-message').textContent=existing?'Flow changes saved.':'Flow saved, paused.';await load();
  }catch(error){showError(error.message);}finally{b.disabled=false;b.textContent='Save paused flow';}
};load();
