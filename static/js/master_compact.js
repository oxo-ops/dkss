(()=>{'use strict';
function init(){document.querySelectorAll('[data-master-filter]').forEach(button=>{
const name=button.dataset.masterFilter,panel=document.getElementById(name+'FilterPanel');
button.hidden=!panel;if(!panel)return;
const fields=[...panel.querySelectorAll('input[name]:not([type=hidden]),select[name]')];
const set=open=>{panel.hidden=!open;button.setAttribute('aria-expanded',String(open));button.setAttribute('aria-label',(name==='driver'?'ドライバー':'車両')+'の検索条件を'+(open?'閉じる':'開く'));};
if(!panel.dataset.compactReady){panel.dataset.compactReady='1';set(fields.some(e=>e.value.trim()));panel.addEventListener('keydown',e=>{if(e.key==='Escape'&&!e.isComposing){e.preventDefault();set(false);button.focus();}});}
button.onclick=()=>{const open=panel.hidden;set(open);if(open)fields[0]?.focus();};
});}
init();document.addEventListener('dkss:vehicle-workflow',init);
})();