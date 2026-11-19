/* Relocate existing controls, never clone handlers or recreate permission gates. */
(()=>{'use strict';
function init(){
 const main=document.querySelector('.main-content'),tabs=main?.querySelector('.master-unified-tabs');
 if(!tabs)return;
 let toolbar=main.querySelector('.master-top-toolbar');
 if(!toolbar){toolbar=document.createElement('div');toolbar.className='master-top-toolbar';toolbar.setAttribute('role','group');toolbar.setAttribute('aria-label','マスタの登録・検索');tabs.before(toolbar);}
 const controls=[...main.querySelectorAll('.page-header .entry-add-icon,.master-list-actions .entry-add-icon,.vehicle-workflow-tabs .entry-add-icon,[data-master-filter]')];
 controls.forEach(control=>{if(control.parentElement===toolbar)return;const old=control.parentElement;toolbar.append(control);if(!old.textContent.trim()&&!old.querySelector('input,button,a,select')){old.classList.add('master-empty-actions');const header=old.closest('.page-header');if(header&&!header.querySelector('a,button,input,select'))header.classList.add('master-empty-actions');}});
 toolbar.hidden=!toolbar.children.length;
}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init);else init();
document.addEventListener('dkss:vehicle-workflow',init);
})();
