/* Page existing authorized rows; no fetching, scoring or data changes. */
(() => {
 'use strict';
 const initialize = () => document.querySelectorAll('[data-office-actions]').forEach(panel => {
  if (panel.dataset.actionsReady) return;
  const rows = [...panel.querySelectorAll('[data-action-kind]')];
  const tabs = [...panel.querySelectorAll('[data-action-tab]')];
  if (!rows.length || !tabs.length) return;
  panel.dataset.actionsReady = 'true';
  const tablist = panel.querySelector('[role=tablist]');
  const content = panel.querySelector('.office-action-page');
  const pager = panel.querySelector('.office-action-pager');
  const previous = panel.querySelector('[data-action-prev]');
  const next = panel.querySelector('[data-action-next]');
  const range = panel.querySelector('[data-action-range]');
  const pages = Object.create(null);
  let kind = tabs[0].dataset.actionTab;
  tablist.hidden = tabs.length < 2;
  const render = () => {
   const selected = rows.filter(row => row.dataset.actionKind === kind);
   const page = Math.min(pages[kind] || 0, Math.floor((selected.length-1)/5));
   pages[kind] = page;
   rows.forEach(row => { row.hidden = true; });
   selected.slice(page*5, page*5+5).forEach(row => { row.hidden = false; });
   tabs.forEach(tab => {
    const active = tab.dataset.actionTab === kind;
    tab.setAttribute('aria-selected', String(active));tab.tabIndex = active ? 0 : -1;
    if (active) content.setAttribute('aria-labelledby',tab.id);
   });
   content.setAttribute('role','tabpanel');
   pager.hidden = selected.length <= 5;
   previous.disabled = page === 0;
   next.disabled = (page+1)*5 >= selected.length;
   range.textContent = (page*5+1)+'〜'+Math.min((page+1)*5,selected.length)+' / '+selected.length+'件';
  };
  tabs.forEach((tab,index) => {
   tab.addEventListener('click',() => {kind=tab.dataset.actionTab;render();});
   tab.addEventListener('keydown',event => {
    let target;
    if(event.key==='ArrowRight')target=(index+1)%tabs.length;
    if(event.key==='ArrowLeft')target=(index+tabs.length-1)%tabs.length;
    if(event.key==='Home')target=0;
    if(event.key==='End')target=tabs.length-1;
    if(target===undefined)return;
    event.preventDefault();tabs[target].click();tabs[target].focus();
   });
  });
  previous.addEventListener('click',() => {pages[kind]--;render();if(previous.disabled)next.focus();});
  next.addEventListener('click',() => {pages[kind]=(pages[kind]||0)+1;render();if(next.disabled)previous.focus();});
  render();
 });
 if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',initialize,{once:true});
 else initialize();
})();

