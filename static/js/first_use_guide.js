(function () {
  'use strict';
  const plans = {
    dashboard: [
      { selector: '.dashboard-vehicle-action-primary', title: '日常点検を開く', text: 'ここから、この車両の日常点検表を開けます。' },
      { selector: '.dashboard-vehicle-action', title: '車両の点検表', text: '車両ごとの点検表を開けます。' },
      { selector: '#sidebarToggle', title: 'メニューから画面を選ぶ', text: 'メニューを開き、「安全管理」「車両管理」から使いたい画面を選べます。' }
    ],
    vehicle_checklist_results: [
      { selector: '#vehicle_check_filter select[name="vehicle_record_id"]', title: '車両を選ぶ', text: 'ここで、点検表を表示する車両を選べます。' },
      { selector: '.inspection-item-detail', title: '項目の詳細を見る', text: '項目名を押すと、評価基準や詳細が開きます。入力できる記録では、コメントや写真も追加できます。' },
      { selector: '.check-choice-buttons', title: '評価を入れる', text: '各項目の評価を選びます。✓・×の意味は、その項目の評価基準で確認できます。' },
      { selector: '.vehicle-check-complete-form .approval-user-search', title: '依頼先を選ぶ', text: '名前で検索し、候補から依頼先を選びます。' },
      { selector: '#notify_user_search', title: '点検完了通知先を選ぶ', text: '点検が完了したことを知らせる相手を、名前で検索して選びます。' },
      { selector: '#reminder_notify_user_search', title: '点検未実施通知先を選ぶ', text: '未実施のときに通知する相手を、名前で検索して選びます。' },
      { selector: '.reminder-readonly', title: '点検未実施通知先を確認する', text: '設定されている通知先を確認します。変更は管理者が行います。' },
      { selector: '.vehicle-check-complete-primary', title: '点検を完了する', text: '評価と依頼先を確認したら「点検完了」を押します。差し戻し後は「修正して再申請」です。' }
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
      if (target && !result.some(s=>s.target===target)) {
        const content=target.dataset || {};
        result.push({...step,target,title:content.guideTitle || step.title,text:content.guideText || step.text});
      }
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
  const picture=root.querySelector('[data-guide-picture]');
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
    if(picture) picture.hidden=s.selector!=='.inspection-item-detail';
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
