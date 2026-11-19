/* Presentation only: preserve the original GET form, fields and listeners. */
(()=>{'use strict';const form=document.querySelector('#km-maintenance-filters');if(!form)return;
const marker=document.createComment('maintenance-filter-original');form.before(marker);
const panel=document.createElement('details');panel.className='karte-maintenance-filter';
const summary=document.createElement('summary');summary.setAttribute('aria-label','整備・修理の検索条件を開閉');
summary.innerHTML='<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><path d="m21 21-5-5"/><circle cx="10" cy="10" r="7"/></svg>';
const label=document.createElement('span');const selected=[...form.querySelectorAll('select')].filter(e=>e.value).map(e=>e.selectedOptions[0].textContent.trim());if([...form.querySelectorAll('input[type="date"]')].some(e=>e.value))selected.push('期間指定あり');label.textContent=selected.join('・')||'絞り込み';summary.append(label);panel.append(summary);
const mobile=matchMedia('(max-width:767px)');const adapt=()=>{if(mobile.matches){if(!panel.isConnected){marker.after(panel);panel.append(form);panel.open=false;}}else{marker.after(form);panel.remove();}};adapt();mobile.addEventListener('change',adapt);})();
