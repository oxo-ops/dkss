(function(){
 'use strict';
 function reveal(hash=location.hash){
  let target;try{target=document.getElementById(decodeURIComponent(hash.slice(1)));}catch{return;}
  if(!target)return;
  for(let node=target;node;node=node.parentElement)if(node.tagName==='DETAILS')node.open=true;
  requestAnimationFrame(()=>target.scrollIntoView({block:'start'}));
 }
 document.addEventListener('DOMContentLoaded',()=>reveal());
 window.addEventListener('hashchange',()=>reveal());
 document.addEventListener('click',event=>{
  const link=event.target.closest('a[href^="#"]');if(link)reveal(link.hash);
 });
})();

// Reconstructed from previously reviewed candidate; requires fresh tests on exact baseline.
(function () {
 'use strict';
 document.addEventListener('DOMContentLoaded', () => {
  const form = document.querySelector('form[data-review-inplace]');
  if (!form || !window.fetch || !window.AbortController) return;
  const status = form.querySelector('[data-review-status]');
  const recovery = form.querySelector('[data-review-recovery]');
  if (!status || !recovery) return;
  let attempted = false, dirty = false;
  form.addEventListener('input', () => { dirty = true; });
  form.addEventListener('change', () => { dirty = true; });
  window.addEventListener('beforeunload', event => {
   if (dirty) { event.preventDefault(); event.returnValue = ''; }
  });
  form.addEventListener('submit', async event => {
   event.preventDefault();
   if (attempted) return;
   attempted = true; dirty = true;
   const body = new FormData(form);
   const controls = Array.from(form.elements).map(el => [el, el.disabled, el.readOnly]);
   controls.forEach(([el]) => {
    if (el.tagName === 'TEXTAREA' || (el.tagName === 'INPUT' && el.type !== 'hidden')) el.readOnly = true;
    else if (el.type !== 'hidden') el.disabled = true;
   });
   status.hidden = false; status.textContent = '保存結果を確認しています。この画面を閉じないでください。';
   const controller = new AbortController();
   const timer = window.setTimeout(() => controller.abort(), 120000);
   try {
    const response = await window.fetch(form.action, {
     method: 'POST', body, credentials: 'same-origin', redirect: 'error',
     headers: {'X-DKSS-Review-Inplace': '1'}, signal: controller.signal
    });
    if (response.ok && response.headers.get('X-DKSS-Review-Saved') === '1') {
     const result = await response.json();
     const target = new URL(result.detail_url, window.location.href);
     const expected = new URL(form.action, window.location.href).pathname.replace(/\/review$/, '');
     if (result.saved === true && target.origin === window.location.origin && target.pathname === expected) {
      dirty = false; window.location.assign(target.href); return;
     }
    }
    status.textContent = [400, 401, 403, 409].includes(response.status)
     ? '送信が受け付けられませんでした。入力内容・ログイン状態・最新の記録を別タブで確認してください。'
     : '保存結果を確認できません。保存済みの可能性があるため、再送せず最新の記録を確認してください。';
   } catch (_) {
    dirty = true;
    status.textContent = '保存結果を確認できません。通信切断やログイン期限切れの可能性があります。再送せず別タブで最新の記録を確認してください。';
   } finally { window.clearTimeout(timer); }
   controls.forEach(([el, disabled, readOnly]) => {
    el.readOnly = readOnly;
    if (el.type !== 'submit') el.disabled = disabled;
   });
   recovery.hidden = false; status.focus();
  });
 });
})();
