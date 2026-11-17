/* Public hint, never a credential. Preserve the application's navigation first. */
(() => {
  'use strict';
  const marker='__aonagi_entry';
  const fields=['vehicle_record_id','year','month','active_day','vehicle_return_year','vehicle_return_month','vehicle_return_day','vehicle_saved'];
  function eligible(url) {return url.origin===location.origin && (url.pathname==='/' || /^\/vehicle\/checklists\/\d+$/.test(url.pathname));}
  function shared(url) {
    if(!eligible(url))return null;
    const allowed=url.pathname==='/'?[]:fields;
    // Never erase a business parameter or anchor to make the URL shareable.
    // Unknown/private text remains in the existing app flow, without automatic sharing.
    for(const [key,value] of url.searchParams){
      if(key===marker){if(value!=='1'||url.searchParams.getAll(key).length!==1)return null;continue;}
      const valid=key==='vehicle_saved'?value==='complete':/^\d{1,10}$/.test(value);
      if(!allowed.includes(key)||!valid||url.searchParams.getAll(key).length!==1)return null;
    }
    if(url.hash && !/^#(?:vehicle-flow-(?:judgment|completed|defect-\d+-\d+)|vehicle-inspection-(?:record|response))$/.test(url.hash))return null;
    url.searchParams.set(marker,'1');return url;
  }
  function prepare(){
    const current=shared(new URL(location.href));
    if(current)history.replaceState(history.state,'',current.href);
    document.querySelectorAll('a[href]').forEach(a=>{
      const href=a.getAttribute('href');if(href.startsWith('#'))return;
      const url=shared(new URL(href,location.href));if(url)a.href=url.href;
    });
    document.querySelectorAll('form').forEach(form=>{
      if((form.getAttribute('method')||'get').toLowerCase()!=='get')return;
      const action=new URL(form.getAttribute('action')||location.href,location.href);
      if(!eligible(action))return;
      const allowed=action.pathname==='/'?[]:fields;
      if([...form.elements].some(el=>el.name&&!el.disabled&&el.name!==marker&&!allowed.includes(el.name)))return;
      if(!form.querySelector('input[name="'+marker+'"]')){
        const input=document.createElement('input');input.type='hidden';input.name=marker;input.value='1';form.append(input);
      }
    });
  }
  // Existing inspection code consumes save flags asynchronously when it adds
  // feedback. Observe only that signal; do not replace history APIs or timers.
  new MutationObserver(records=>{
    if(records.some(record=>[...record.addedNodes].some(node=>node.nodeType===1 &&
      (node.matches('.vehicle-save-feedback') || node.querySelector('.vehicle-save-feedback')))))prepare();
  }).observe(document.body,{childList:true,subtree:true});
  // Existing inspection DOMContentLoaded handlers consume saved/notice flags first.
  if(document.readyState==='complete')prepare();
  else {
    document.addEventListener('DOMContentLoaded',prepare,{once:true});
    window.addEventListener('load',prepare,{once:true}); // idempotent after existing saved-feedback handlers
  }
})();
