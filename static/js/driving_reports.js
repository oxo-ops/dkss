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
  const positionKey='driving-position:'+location.pathname+location.search;
  document.addEventListener('click',event=>{if(event.target.closest('a'))sessionStorage.setItem(positionKey,String(scrollY));});
  if(location.hash){requestAnimationFrame(()=>document.getElementById(location.hash.slice(1))?.scrollIntoView());}
  else if(sessionStorage.getItem(positionKey)){requestAnimationFrame(()=>scrollTo(0,Number(sessionStorage.getItem(positionKey))||0));}
  form?.querySelector('[data-office-select]')?.addEventListener('change',event=>{
   const scope=form.querySelector('[name=scope]');if(scope)scope.value=event.target.value==='__company__'?'company':'office';
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
    if(state.status==='completed'){sessionStorage.setItem(positionKey,String(scrollY));location.reload();return;}
    if(state.status==='failed'||++polls>65)throw new Error('作成できませんでした。画面を再表示して再試行できます。');
    pollTimer=setTimeout(pollReflection,2000);
   }catch(error){reflection.querySelector('[data-reflection-status]').textContent=error.message;const button=reflectionForm?.querySelector('button');if(button){button.disabled=false;button.textContent='再試行';}}
  }
  reflectionForm?.addEventListener('submit',async event=>{
   event.preventDefault();const button=reflectionForm.querySelector('button');button.disabled=true;
   try{
    const response=await fetch(reflectionForm.action,{method:'POST',body:new FormData(reflectionForm),headers:{Accept:'application/json'}});
    if(!response.ok)throw new Error(response.status===409?'対象の記録が変わりました。再表示してください。':response.status===429?'ほかの分析を作成中です。少し待ってから再試行してください。':response.status===503?'AI分析を利用できません。管理者に接続設定を確認してください。':'作成できませんでした。再試行してください。');
    const state=await response.json();
    if(state.status==='completed'){location.reload();return;}
    reflection.querySelector('[data-reflection-status]').textContent='振り返りを作成しています。このまま記録を確認できます。';button.textContent='作成中';polls=0;pollTimer=setTimeout(pollReflection,1500);
   }catch(error){reflection.querySelector('[data-reflection-status]').textContent=error.message;button.disabled=false;button.textContent='再試行';}
  });
  if(reflection?.dataset.status==='pending')pollTimer=setTimeout(pollReflection,1500);
  // Refresh only a previously requested scope whose authorized data changed.
  // An ordinary page open with unchanged data never starts a paid job.
  if(reflection?.dataset.status==='new'&&reflection.dataset.autoRefresh==='true')reflectionForm?.requestSubmit();
  window.addEventListener('pagehide',()=>clearTimeout(pollTimer));
  form?.querySelector('[name=period]')?.addEventListener('change',event=>{if(event.target.value==='custom'){const details=form.querySelector('.driving-extra-filters');if(details)details.open=true;}});
  form?.querySelectorAll('input[type=date]').forEach(input=>input.addEventListener('change',()=>{
   const select=form.querySelector('[name=period]');if(select)select.value='custom';
  }));
  document.querySelectorAll('[data-driving-chart]').forEach(svg=>{
   let rows;try{rows=series(JSON.parse(svg.dataset.series));}catch{return;}
   const measured=rows.filter(r=>r.value!==null);
   if(measured.length<2){svg.hidden=true;return;}
   const values=measured.map(r=>r.value),lo=Math.min(0,...values),hi=Math.max(1,...values),span=hi-lo||1;
   const first=Date.parse(rows[0].date),last=Date.parse(rows.at(-1).date);
   const point=r=>[55+(first===last?250:505*(Date.parse(r.date)-first)/(last-first)),108-78*(r.value-lo)/span];
   function el(name,attrs,text){const e=document.createElementNS(ns,name);for(const [k,v] of Object.entries(attrs))e.setAttribute(k,v);if(text!==undefined)e.textContent=text;svg.append(e);return e;}
   el('path',{d:'M50 18V112H570',fill:'none',stroke:'#bbcfdf'});
   let segment=[];
   function line(){if(segment.length>1)el('polyline',{points:segment.map(r=>point(r).join(',')).join(' '),fill:'none',stroke:'#3a78a7','stroke-width':2});segment=[];}
   rows.forEach(r=>{if(r.value===null){line();return;}segment.push(r);});line();
   measured.forEach(r=>{const [cx,cy]=point(r);const c=el('circle',{cx,cy,r:3,fill:'#3a78a7'});const t=document.createElementNS(ns,'title');t.textContent=`${r.date} ${r.value} 日報${r.report_id}`;c.append(t);});
   for(const [x,y,t] of [[2,28,String(hi)],[2,110,String(lo)],[55,135,rows[0].date],[475,135,rows.at(-1).date]])el('text',{x,y,'font-size':11,fill:'#46647d'},t);
  });
 });
})();
