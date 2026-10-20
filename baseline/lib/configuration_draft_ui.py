"""Shared browser draft lifecycle using authenticated durable web endpoints."""


def script():
    return r'''<script>
function baselineDraft({endpoint, read, restore, inputs}) {
 const status=document.getElementById('draft-status'),fields=document.getElementById('draft-fields'),retry=document.getElementById('draft-retry');
 let revision=0,ready=false,loading=false,dirty=false,running=false,blocked=false,conflict=false,timer=null,generation=0;
 function warn(event){if(dirty){event.preventDefault();event.returnValue='';}}
 window.addEventListener('beforeunload',warn);
 async function json(response){const result=await response.json();if(!response.ok||!result.ok){const error=Error(result.message||'Draft request refused');error.conflict=response.status===409;throw error;}return result;}
 async function load(){
  ready=false;loading=true;fields.disabled=true;retry.hidden=true;status.textContent='Loading saved draft…';
  try {const result=await json(await fetch(endpoint,{credentials:'same-origin',referrerPolicy:'same-origin',cache:'no-store'}));
   if(result.draft){restore(result.draft.document);revision=result.draft.revision;status.textContent='Restored saved draft, revision '+revision+'. Not applied; validate again.';}
   else {revision=0;status.textContent='No saved draft yet. Changes save automatically; nothing is applied.';}
   ready=true;dirty=false;blocked=false;conflict=false;fields.disabled=false;
  } catch(error){status.textContent='Draft unavailable: '+error.message;retry.textContent='Retry loading draft';retry.hidden=false;}
  finally {loading=false;}
 }
 async function save(){
  if(!ready||loading||running||blocked||!dirty)return;
  running=true;const version=generation;retry.hidden=true;
  try {const document=read();status.textContent='Saving draft…';
   const result=await json(await fetch(endpoint,{method:'POST',credentials:'same-origin',referrerPolicy:'same-origin',headers:{'Content-Type':'application/json'},body:JSON.stringify({document,revision})}));
   revision=result.draft.revision;if(version===generation)dirty=false;
   status.textContent='Saved draft, revision '+revision+'. Not applied; validate again.';
  } catch(error){blocked=true;conflict=!!error.conflict;status.textContent='Draft not saved: '+error.message;
   retry.textContent=conflict?'Reload saved draft (discard local edits)':'Retry saving draft';retry.hidden=false;
  } finally {running=false;if(dirty&&!blocked)save();}
 }
 function changed(){if(!ready||loading)return;dirty=true;generation++;status.textContent='Draft changes pending…';clearTimeout(timer);timer=setTimeout(save,400);}
 for(const input of inputs){input.addEventListener('input',changed);input.addEventListener('change',changed);}
 retry.addEventListener('click',()=>{if(!ready||conflict)load();else {blocked=false;save();}});
 const initialLoad=load();
 return {loaded:initialLoad,flush:async()=>{
  await initialLoad;
  if(!ready||loading||blocked)throw Error('Resolve the draft loading or saving error before preparing inputs');
  clearTimeout(timer);
  if(revision===0&&!dirty){dirty=true;generation++;}
  while(running||dirty){
   if(blocked)throw Error('Draft not saved; resolve its error before preparing inputs');
   if(!running)await save();
   else await new Promise(resolve=>setTimeout(resolve,50));
  }
  if(blocked)throw Error('Draft not saved');
  return revision;
 }};
}
</script>'''
