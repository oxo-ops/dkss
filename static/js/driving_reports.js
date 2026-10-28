(function () {
 'use strict';
 function validDay(value) {
  if(typeof value!=='string'||!/^\d{4}-\d{2}-\d{2}$/.test(value))return false;
  const stamp=Date.parse(value+'T00:00:00Z');
  return Number.isFinite(stamp)&&new Date(stamp).toISOString().slice(0,10)===value;
 }
 function series(input) {
  if(!Array.isArray(input))return [];
  return input.filter(row=>row&&validDay(row.date)).map(row=>({
   date:row.date,report_id:row.report_id,
   value:row.value!==null&&row.value!==undefined&&String(row.value).trim()!==''&&Number.isFinite(Number(row.value))?Number(row.value):null
  })).sort((a,b)=>a.date.localeCompare(b.date));
 }
 if(typeof module!=='undefined'&&module.exports)module.exports={series,validDay};
 if(typeof document==='undefined')return;
 document.addEventListener('DOMContentLoaded',()=>{
  const ns='http://www.w3.org/2000/svg';
  const form=document.getElementById('driving-filter-form');
  const positionKey='driving-workspace-position';
  const workspace=document.querySelector('.driving-page');
  const localURL=value=>{
   const url=new URL(value,location.href);url.searchParams.sort();
   return url.pathname+url.search+url.hash;
  };
  function scrollRoot(target){
   for(let node=target?.parentElement;node;node=node.parentElement){
    if(/^(auto|scroll)$/.test(getComputedStyle(node).overflowY)&&node.scrollHeight>node.clientHeight)return node;
   }
   return document.scrollingElement;
  }
  function restorePosition(target,top,fallback){
   requestAnimationFrame(()=>requestAnimationFrame(()=>{
    const root=scrollRoot(target||workspace);
    if(root)root.scrollTop=target?root.scrollTop+target.getBoundingClientRect().top-top:fallback;
   }));
  }
  function capturePosition(url,target){
   const root=scrollRoot(target||workspace),folds={};
   workspace?.querySelectorAll('details[id]').forEach(item=>{folds[item.id]=item.open;});
   return {url:localURL(url),id:target?.id||'',top:target?.getBoundingClientRect().top||0,
    y:root?.scrollTop||0,folds,at:Date.now()};
  }
  function rememberPosition(url,target){
   try{sessionStorage.setItem(positionKey,JSON.stringify(capturePosition(url,target)));}catch{}
  }
  const returnKey='driving-workspace-returns',owner=workspace?.dataset.positionOwner;
  const withoutHash=value=>localURL(value).split('#')[0];
  let returns=[];
  try{
   returns=JSON.parse(sessionStorage.getItem(returnKey)||'[]').filter(item=>
    item.owner===owner&&Date.now()-item.at>=0&&Date.now()-item.at<1800000&&
    Number.isFinite(item.top)&&Number.isFinite(item.y)&&new URL(item.url,location.href).origin===location.origin&&
    new URL(item.url,location.href).pathname===location.pathname);
  }catch{}
  function saveReturns(){try{sessionStorage.setItem(returnKey,JSON.stringify(returns.slice(-12)));}catch{}}
  const focus=new URL(location.href).searchParams.get('focus');
  const previousView=returns.findLast(item=>item.focus&&item.focus===focus);
  if(previousView){
   const back=workspace?.querySelector('.driving-back-link');if(back)back.href=previousView.url;
  }
  let position=null;
  try{
   const saved=JSON.parse(sessionStorage.getItem(positionKey)||'null');
   sessionStorage.removeItem(positionKey);
   if(saved&&saved.url===localURL(location.href)&&Number.isFinite(saved.top)&&Number.isFinite(saved.y)&&
      Date.now()-saved.at>=0&&Date.now()-saved.at<60000)position=saved;
  }catch{}
  if(!position){
   const index=returns.findLastIndex(item=>withoutHash(item.url)===withoutHash(location.href));
   if(index>=0&&document.referrer.startsWith(location.origin+'/safety/driving-reports')){
    position=returns.splice(index,1)[0];saveReturns();
   }
  }
  function revealPanel(target){
   const panel=target?.closest('[data-workspace-panel]');
   if(!panel)return;
   workspace?.querySelectorAll('[data-workspace-panel]').forEach(item=>{item.hidden=item!==panel;});
   workspace?.querySelectorAll('[data-panel-link]').forEach(link=>{
    if(link.dataset.panelLink===panel.dataset.workspacePanel)link.setAttribute('aria-current','page');
    else link.removeAttribute('aria-current');
   });
  }
  function revealHash(hash){
   let target;try{target=document.getElementById(decodeURIComponent(hash.slice(1)));}catch{return;}
   if(!target)return;
   revealPanel(target);
   for(let node=target;node;node=node.parentElement)if(node.tagName==='DETAILS')node.open=true;
   requestAnimationFrame(()=>target.scrollIntoView({block:'start'}));
  }
  if(position){
   for(const [id,open] of Object.entries(position.folds||{})){
    const item=document.getElementById(id);if(item?.tagName==='DETAILS'&&typeof open==='boolean')item.open=open;
   }
   const target=document.getElementById(position.id);
   revealPanel(target);
   for(let node=target;node;node=node.parentElement)if(node.tagName==='DETAILS')node.open=true;
   restorePosition(target,position.top,position.y);
  }else if(location.hash){requestAnimationFrame(()=>revealHash(location.hash));}
  window.addEventListener('hashchange',()=>revealHash(location.hash));
  document.addEventListener('click',event=>{
   const link=event.target.closest('a[href]');
   if(!link||!workspace?.contains(link)||event.defaultPrevented||event.button!==0||event.metaKey||event.ctrlKey||event.shiftKey||event.altKey||link.target==='_blank'||link.hasAttribute('download'))return;
   const url=new URL(link.href,location.href);
   if(url.origin!==location.origin)return;
   if(link.classList.contains('driving-back-link')&&previousView){
    try{sessionStorage.setItem(positionKey,JSON.stringify({...previousView,url:localURL(url.href),at:Date.now()}));}catch{}
    returns=returns.filter(item=>item!==previousView);saveReturns();return;
   }
   const personLink=url.pathname===location.pathname&&url.searchParams.get('focus')&&
    url.searchParams.get('focus')!==focus&&(link.closest('#driver-comparison')||['#driving-analysis-top','#driver-trend','#reader-setting'].includes(url.hash));
   const reportLink=url.pathname.startsWith(location.pathname+'/')&&url.searchParams.has('return_to');
   if(personLink||reportLink){
    const saved=capturePosition(location.href,link.closest('tr[id]')||link.closest('[id]'));
    returns=returns.filter(item=>withoutHash(item.url)!==withoutHash(saved.url));
    returns.push({...saved,owner,focus:personLink?url.searchParams.get('focus'):null});saveReturns();
    if(reportLink){url.searchParams.set('return_to',location.pathname+location.search+location.hash);link.href=url.href;}
    return;
   }
   if(url.pathname!==location.pathname)return;
   if(link.closest('#office-comparison')&&url.searchParams.get('scope')==='office')return;
   if(link.closest('.driving-analysis-path'))return;
   let target=null;
   if(link.hasAttribute('data-panel-link'))target=document.getElementById('driving-view');
   else if(link.hasAttribute('data-preserve-driving-metrics'))target=document.getElementById('driving-metrics');
   else if(link.closest('.driving-view-switch')||link.classList.contains('driving-reset'))target=form;
   else if(link.closest('.driving-analysis-actions'))target=document.getElementById('driving-view');
   else if(link.closest('.driving-comparison-tabs'))target=document.getElementById('comparison-detail');
   else if(!url.hash)target=link.closest('#driving-roster')||link.closest('details[id],section[id],form[id]')||form;
   if(target){
    if(localURL(url.href)===localURL(location.href)||url.search===location.search){event.preventDefault();return;}
    rememberPosition(url.href,target);
   }else if(url.search===location.search&&url.hash)revealHash(url.hash);
  });
  workspace?.addEventListener('submit',event=>{
   const submitted=event.target;
   if(submitted.tagName!=='FORM'||submitted.method.toLowerCase()!=='get'||event.defaultPrevented)return;
   const url=new URL(submitted.action||location.href,location.href);
   if(url.origin!==location.origin||url.pathname!==location.pathname)return;
   const data=new FormData(submitted);if(event.submitter?.name)data.append(event.submitter.name,event.submitter.value);
   url.search=new URLSearchParams(data).toString();
   rememberPosition(url.href,submitted.closest('form[id],details[id],section[id]')||form);
  });
  // Native details toggles can invoke scroll anchoring; keep the clicked summary visible in place.
  workspace?.addEventListener('click',event=>{
   const summary=event.target.closest('summary');
   if(!summary||summary.parentElement.tagName!=='DETAILS')return;
   restorePosition(summary,summary.getBoundingClientRect().top,0);
  },true);
  form?.querySelector('[data-office-select]')?.addEventListener('change',event=>{
   const scope=form.querySelector('[name=scope]');if(scope)scope.value=event.target.value==='__company__'?'company':event.target.value==='__self__'?'self':'office';
   form.querySelector('[name=focus]')?.remove();form.querySelector('[name=listing]')?.remove();
   form.requestSubmit();
  });
  const reflection=document.querySelector('[data-reflection]');
  const reflectionForm=reflection?.querySelector('[data-reflection-form]');
  let pollTimer=null,polls=0;
  async function pollReflection(){
   if(document.hidden){pollTimer=setTimeout(pollReflection,3000);return;}
   try{
    const response=await fetch(reflection.dataset.endpoint,{headers:{Accept:'application/json'},cache:'no-store'});
    if(!response.ok)throw new Error('読み込みできませんでした。再表示してください。');
    const state=await response.json();
    if(state.key!==reflection.dataset.key){reflection.querySelector('[data-reflection-status]').textContent='対象の記録が更新されました。再表示してください。';return;}
    if(state.status==='completed'){rememberPosition(location.href,reflection);location.reload();return;}
    if(state.status==='failed'||++polls>65)throw new Error('作成できませんでした。画面を再表示して再試行できます。');
    pollTimer=setTimeout(pollReflection,2000);
   }catch(error){reflection.querySelector('[data-reflection-status]').hidden=false;reflection.querySelector('[data-reflection-status]').textContent=error.message;const button=reflectionForm?.querySelector('button');if(button){button.disabled=false;button.textContent='再試行';}}
  }
  reflectionForm?.addEventListener('submit',async event=>{
   event.preventDefault();const button=reflectionForm.querySelector('button');button.disabled=true;
   try{
    const response=await fetch(reflectionForm.action,{method:'POST',body:new FormData(reflectionForm),headers:{Accept:'application/json'}});
    if(!response.ok)throw new Error(response.status===409?'対象の記録が変わりました。再表示してください。':response.status===429?'ほかの分析を作成中です。少し待ってから再試行してください。':response.status===503?'AI分析を利用できません。管理者に接続設定を確認してください。':'作成できませんでした。再試行してください。');
    const state=await response.json();
    if(state.status==='completed'){rememberPosition(location.href,reflection);location.reload();return;}
    reflection.querySelector('[data-reflection-status]').hidden=false;reflection.querySelector('[data-reflection-status]').textContent='振り返りを作成しています。このまま記録を確認できます。';button.textContent='作成中';polls=0;pollTimer=setTimeout(pollReflection,1500);
   }catch(error){reflection.querySelector('[data-reflection-status]').hidden=false;reflection.querySelector('[data-reflection-status]').textContent=error.message;button.disabled=false;button.textContent='再試行';}
  });
  if(reflection?.dataset.status==='pending')pollTimer=setTimeout(pollReflection,1500);
  // Refresh only a previously requested scope whose authorized data changed.
  // An ordinary page open with unchanged data never starts a paid job.
  if(reflection?.dataset.status==='new'&&reflection.dataset.autoRefresh==='true')reflectionForm?.requestSubmit();
  window.addEventListener('pagehide',()=>clearTimeout(pollTimer));
  form?.querySelectorAll('input[name=start],input[name=end]').forEach(input=>input.addEventListener('change',()=>{
   const select=form.querySelector('[name=period]');if(select)select.value='custom';
  }));
  const comparisonSelect=form?.querySelector('[name=compare]');
  function comparisonFields(){
   const custom=comparisonSelect?.value==='custom';
   form?.querySelectorAll('[data-comparison-date]').forEach(label=>{
    label.hidden=!custom;
    const input=label.querySelector('input');input.required=custom;input.disabled=!custom;
   });
   if(custom&&form?.querySelector('[name=period]')?.value==='all')form.querySelector('[name=period]').value='custom';
   const targetStart=form?.querySelector('[name=start]')?.value;
   const beforeStart=form?.querySelector('[name=compare_start]'),beforeEnd=form?.querySelector('[name=compare_end]');
   if(beforeStart&&beforeEnd){
    const limit=validDay(targetStart)?new Date(Date.parse(targetStart)-86400000).toISOString().slice(0,10):'';
    beforeEnd.max=limit;beforeEnd.min=beforeStart.value;
    beforeStart.max=beforeEnd.value||limit;
   }
  }
  comparisonSelect?.addEventListener('change',comparisonFields);comparisonFields();
  form?.querySelector('[name=period]')?.addEventListener('change',event=>{
   if(event.target.value==='all'&&comparisonSelect?.value==='custom')comparisonSelect.value='previous';
   comparisonFields();
   // Normalize successful controls before requestSubmit serializes and validates them.
   if(event.target.value==='custom'){
    const details=form.querySelector('.driving-extra-filters');if(details)details.open=true;
   }else form.requestSubmit();
  });
  form?.querySelectorAll('input[type=date]').forEach(input=>input.addEventListener('change',comparisonFields));
  document.querySelectorAll('[data-driving-chart]').forEach(svg=>{
   let rows;try{rows=series(JSON.parse(svg.dataset.series));}catch{return;}
   const measured=rows.filter(r=>r.value!==null);
   if(measured.length<2){svg.hidden=true;return;}
   const before=svg.dataset.previous;
   const previous=before!==undefined&&before.trim()!==''&&Number.isFinite(Number(before))?Number(before):null;
   const values=measured.map(r=>r.value);if(previous!==null)values.push(previous);
   const rawLo=Math.min(0,...values),rawHi=Math.max(...values);
   const magnitude=Math.pow(10,Math.floor(Math.log10((rawHi-rawLo)||1)));
   const scaled=((rawHi-rawLo)||1)/magnitude;
   const step=(scaled<=2?0.5:scaled<=5?1:2)*magnitude;
   const lo=Math.floor(rawLo/step)*step,hi=Math.ceil(rawHi/step)*step||step,span=hi-lo||step;
   const first=Date.parse(rows[0].date),last=Date.parse(rows.at(-1).date);
   function draw(){
    const width=Math.max(220,Math.round(svg.getBoundingClientRect().width));
    svg.replaceChildren();svg.setAttribute('viewBox',`0 0 ${width} 145`);
    const left=30,right=width-12,top=12,bottom=116;
    const y=value=>bottom-(bottom-top)*(value-lo)/span;
    const point=r=>[left+(first===last?(right-left)/2:(right-left)*(Date.parse(r.date)-first)/(last-first)),y(r.value)];
    function el(name,attrs,text){const e=document.createElementNS(ns,name);for(const [k,v] of Object.entries(attrs))e.setAttribute(k,v);if(text!==undefined)e.textContent=text;svg.append(e);return e;}
    for(let tick=lo;tick<=hi+step/100;tick+=step){
     el('line',{x1:left,y1:y(tick),x2:right,y2:y(tick),stroke:'#e1eafa','stroke-width':1});
     el('text',{x:left-8,y:y(tick)+4,'text-anchor':'end','font-size':10,fill:'#6582ac'},String(Number(tick.toPrecision(6))));
    }
    if(previous!==null)el('line',{x1:left,y1:y(previous),x2:right,y2:y(previous),stroke:'#b2b6da','stroke-dasharray':'4 4'});
    let segment=[];
    function line(){if(segment.length>1)el('polyline',{points:segment.map(r=>point(r).join(',')).join(' '),fill:'none',stroke:'#4695ee','stroke-width':2});segment=[];}
    rows.forEach(r=>{if(r.value===null){line();return;}segment.push(r);});line();
    measured.forEach(r=>{const [cx,cy]=point(r);const c=el('circle',{cx,cy,r:3,fill:'#4695ee',stroke:'#fff','stroke-width':1});const t=document.createElementNS(ns,'title');t.textContent=`${r.date} ${r.value} ${svg.dataset.unit||''} 日報${r.report_id}`;c.append(t);});
    const maxLabels=Math.max(2,Math.min(6,Math.floor((right-left)/55)));
    const labelRows=rows.filter((r,i)=>i===0||i===rows.length-1||i%Math.max(1,Math.ceil((rows.length-1)/(maxLabels-1)))===0);
    const lastX=right;let priorX=-100;
    labelRows.forEach((r,i)=>{const x=point(r)[0];if(i<labelRows.length-1&&lastX-x<45)return;if(x-priorX<45&&i!==labelRows.length-1)return;priorX=x;
     el('text',{x,y:136,'text-anchor':i===0?'start':i===labelRows.length-1?'end':'middle','font-size':10,fill:'#6582ac'},`${Number(r.date.slice(5,7))}/${Number(r.date.slice(8))}`);
    });
   }
   draw();if(typeof ResizeObserver!=='undefined')new ResizeObserver(draw).observe(svg);
  });
 });
})();
