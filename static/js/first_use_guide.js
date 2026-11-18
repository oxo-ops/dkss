(function () {
  'use strict';
  const plans = {
    dashboard: [
      { selector: '.dashboard-vehicle-action-primary', title: '日常点検を開く', text: 'ここから、この車両の日常点検表を開けます。' },
      { selector: '.dashboard-vehicle-action', title: '車両の点検表', text: '車両ごとの点検表を開けます。' },
      { selector: '#sidebarToggle', title: 'ほかの画面へ', text: 'メニューを開くと、点検や車両の一覧へ移動できます。' }
    ],
    vehicle_checklist_results: [
      { selector: '#vehicle_check_filter select[name="vehicle_record_id"]', title: '車両を選ぶ', text: 'ここで、点検表を表示する車両を選べます。' },
      { selector: '.inspection-item-detail', title: '項目の詳細を見る', text: '項目名を押すと、評価基準や詳細が開きます。入力できる記録では、コメントや写真も追加できます。' }
    ]
  };
  function key(mode, page) { return 'dkss:first-guide:v1:' + mode + ':' + page; }
  function state(storage, name) {
    try { const test=name+':probe'; storage.setItem(test,'1'); storage.removeItem(test); return { available:true, seen:storage.getItem(name)==='1' }; }
    catch (_) { return { available:false, seen:true }; }
  }
  function candidates(page, find) {
    const result=[];
    for (const step of plans[page] || []) {
      const target=find(step.selector);
      if (target && !result.some(s=>s.target===target)) result.push({...step,target});
    }
    return result;
  }
  if (typeof module !== 'undefined' && module.exports) module.exports={key,state,candidates};
  if (typeof document === 'undefined') return;
  const root=document.getElementById('firstUseGuide');
  if (!root) return;
  const panel=root.querySelector('.first-guide-panel'), launch=root.querySelector('[data-guide-open]');
  const title=root.querySelector('[data-guide-title]'), text=root.querySelector('[data-guide-text]'), count=root.querySelector('[data-guide-count]');
  const next=root.querySelector('[data-guide-next]');
  const name=key(root.dataset.mode,root.dataset.page);
  let storage; try { storage=window.localStorage; } catch (_) { storage=null; }
  const initial=state(storage,name);
  let steps=[], index=0, active=null, previous=null;
  const visible=el=>el && el.isConnected && el.getClientRects().length && getComputedStyle(el).visibility!=='hidden' && !el.closest('[hidden], [inert]');
  const find=selector=>Array.from(document.querySelectorAll(selector)).find(visible);
  if(find('.public-demo-notice')) { root.hidden=true; return; }
  function remember(){try{storage.setItem(name,'1');}catch(_){}}
  function clearTarget(){if(active) active.classList.remove('first-guide-target'); active=null;}
  function close(restore=true){clearTarget();panel.hidden=true;remember();if(restore && previous && previous.isConnected) previous.focus({preventScroll:true});}
  function position(){
    if(panel.hidden || !active) return;
    if(!visible(active)){close(false);return;}
    const r=active.getBoundingClientRect(), h=panel.offsetHeight, w=panel.offsetWidth;
    const above=r.top-h-12, below=r.bottom+12;
    const preferred=below>=12 && below+h<=innerHeight-12?below:above>=12?above:innerHeight-h-12;
    const top=Math.max(12,Math.min(Math.max(12,innerHeight-h-12),preferred));
    panel.style.top=top+'px';panel.style.left=Math.max(12,Math.min(innerWidth-w-12,r.left))+'px';
  }
  function show(){
    clearTarget();
    while(index<steps.length && !visible(steps[index].target)) index++;
    if(index>=steps.length){close();return;}
    const s=steps[index];active=s.target;active.classList.add('first-guide-target');
    title.textContent=s.title;text.textContent=s.text;count.textContent=(index+1)+' / '+steps.length;
    next.textContent=index===steps.length-1?'終了':'次へ';panel.hidden=false;
    active.scrollIntoView({block:'center',behavior:'instant'});position();
  }
  function open(manual){
    if(document.querySelector('dialog[open], .modal-bg.is-open')) return;
    if(find('.public-demo-notice')) return; // Never restore/interfere with initial role selection.
    steps=candidates(root.dataset.page,find);if(!steps.length)return;
    previous=document.activeElement;index=0;show();remember();
    if(manual) root.querySelector('[data-guide-close]').focus({preventScroll:true});
  }
  launch.addEventListener('click',()=>open(true));
  root.querySelector('[data-guide-close]').addEventListener('click',()=>close(true));
  next.addEventListener('click',()=>{index++;show();});
  document.addEventListener('keydown',e=>{if(e.key==='Escape'&&!panel.hidden){e.preventDefault();close();}});
  // If the user operates the real UI, get out of the way. Never trigger that UI ourselves.
  document.addEventListener('click',e=>{if(!panel.hidden&&!root.contains(e.target)) close(false);},true);
  new MutationObserver(()=>{if(!panel.hidden && active && !visible(active)) close(false);}).observe(document.body,{subtree:true,childList:true,attributes:true,attributeFilter:['hidden','class']});
  window.addEventListener('resize',position);window.addEventListener('scroll',position,{passive:true});
  if(initial.available&&!initial.seen && !/INPUT|TEXTAREA|SELECT/.test(document.activeElement.tagName)) open(false);
})();
