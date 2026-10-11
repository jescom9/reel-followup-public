const form=document.querySelector('#waitlist-form'),button=document.querySelector('#join-waitlist'),error=document.querySelector('#form-error');
form.addEventListener('submit',async event=>{
  event.preventDefault();if(!form.reportValidity())return;
  error.hidden=true;for(const id of ['email','instagram']){document.querySelector('#'+id+'-error').hidden=true;document.querySelector('#'+id).removeAttribute('aria-invalid');}
  button.disabled=true;button.setAttribute('aria-busy','true');button.textContent='Joining…';
  const values=Object.fromEntries(new FormData(form));values.consent=form.elements.consent.checked;
  try{
    const response=await fetch('/api/waitlist',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(values)});
    const data=await response.json();
    if(!response.ok){
      if(data.field&&['email','instagram'].includes(data.field)){
        const input=document.querySelector('#'+data.field),message=document.querySelector('#'+data.field+'-error');
        message.textContent=data.error;message.hidden=false;input.setAttribute('aria-invalid','true');input.focus();
      }else{error.textContent=data.error||'Could not join. Please try again.';error.hidden=false;}
      return;
    }
    form.hidden=true;const success=document.querySelector('#waitlist-success');success.hidden=false;success.focus();
  }catch{error.textContent='Could not reach the waitlist. Your details are still here; please try again.';error.hidden=false;}
  finally{button.disabled=false;button.removeAttribute('aria-busy');button.textContent='Join the waitlist';}
});
