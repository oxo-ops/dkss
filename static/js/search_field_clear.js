/* Clears only the named query input. It does not submit or reset other filters. */
(()=>{'use strict';
const scopes=[['.pointouts-filter-form',{keyword:'安全記録'}],['.patrol-search-box',{keyword:'車両整備記録'}],['.checklist-master-filter-form',{keyword:'チェックリスト名'}],['.driver-master-filter-form',{keyword:'氏名・ユーザーID',vehicle:'使用車両'}],['.vehicle-master-filter-form',{plate_number_search:'車番',chassis_number_search:'車台番号'}]];
function init(){for(const [selector,names] of scopes){const panel=document.querySelector(selector);if(!panel)continue;
for(const [name,label] of Object.entries(names)){const input=panel.querySelector('input[name="'+name+'"]');if(!input||input.dataset.searchClearReady)continue;input.dataset.searchClearReady='true';
const wrap=document.createElement('span');wrap.className='query-clear-field';input.before(wrap);wrap.append(input);
const button=document.createElement('button');button.type='button';button.className='query-clear-button';button.textContent='×';button.setAttribute('aria-label',label+'の検索文字を消去');button.title=label+'の検索文字を消去';wrap.append(button);
const sync=()=>{button.hidden=!input.value||input.disabled||input.readOnly;};input.addEventListener('input',sync);input.addEventListener('change',sync);
button.addEventListener('click',()=>{if(input.disabled||input.readOnly)return;input.value='';input.dispatchEvent(new Event('input',{bubbles:true}));sync();input.focus();});
input.form?.addEventListener('reset',()=>setTimeout(sync,0));sync();
}}}init();document.addEventListener('dkss:vehicle-workflow',init);
})();
