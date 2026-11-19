(()=>{'use strict';
 const details=document.getElementById('driving-extra-filters');if(!details||details.dataset.stableTrigger)return;
 const summary=details.querySelector(':scope > summary');if(!summary)return;
 const button=document.createElement('button');button.type='button';button.className='driving-filter-trigger';button.setAttribute('aria-label',summary.getAttribute('aria-label')||'絞り込み条件');button.setAttribute('aria-controls',details.id);
 for(const node of summary.childNodes)button.append(node.cloneNode(true));
 const sync=()=>button.setAttribute('aria-expanded',String(details.open));
 button.addEventListener('click',()=>{details.open=!details.open;sync()});details.addEventListener('toggle',sync);
 details.before(button);details.dataset.stableTrigger='true';sync();
})();
