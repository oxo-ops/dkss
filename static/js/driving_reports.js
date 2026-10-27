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
  function revealHash(hash){
   let target;try{target=document.getElementById(decodeURIComponent(hash.slice(1)));}catch{return;}
   if(!target)return;
   for(let node=target;node;node=node.parentElement)if(node.tagName==='DETAILS')node.open=true;
   requestAnimationFrame(()=>target.scrollIntoView({block:'start'}));
  }
  if(location.hash){requestAnimationFrame(()=>revealHash(location.hash));}
  window.addEventListener('hashchange',()=>revealHash(location.hash));
  document.addEventListener('click',event=>{
   const link=event.target.closest('a[href]');if(!link)return;
   const url=new URL(link.href,location.href);
   if(url.pathname===location.pathname&&url.search===location.search&&url.hash)revealHash(url.hash);
  });
  if(!location.hash&&sessionStorage.getItem(positionKey)){requestAnimationFrame(()=>scrollTo(0,Number(sessionStorage.getItem(positionKey))||0));}
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
  form?.querySelectorAll('input[name=start],input[name=end]').forEach(input=>input.addEventListener('change',()=>{
   const select=form.querySelector('[name=period]');if(select)select.value='custom';
  }));
  const comparisonSelect=form?.querySelector('[name=compare]');
  function comparisonFields(){
   const custom=comparisonSelect?.value==='custom';
   form?.querySelectorAll('[data-comparison-date]').forEach(label=>{label.hidden=!custom;label.querySelector('input').required=custom;});
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
  });
  form?.querySelectorAll('input[type=date]').forEach(input=>input.addEventListener('change',comparisonFields));
  document.querySelectorAll('[data-driving-chart]').forEach(svg=>{
   let rows;try{rows=series(JSON.parse(svg.dataset.series));}catch{return;}
   const measured=rows.filter(r=>r.value!==null);
   if(measured.length<2){svg.hidden=true;return;}
   const before=svg.dataset.previous;
   const previous=before!==undefined&&before.trim()!==''&&Number.isFinite(Number(before))?Number(before):null;
   const values=measured.map(r=>r.value);if(previous!==null)values.push(previous);
   const lo=Math.min(...values),hi=Math.max(...values),span=hi-lo||1;
   const first=Date.parse(rows[0].date),last=Date.parse(rows.at(-1).date);
   function draw(){
    const width=Math.max(240,Math.round(svg.getBoundingClientRect().width));
    svg.replaceChildren();svg.setAttribute('viewBox',`0 0 ${width} 160`);
    const left=45,right=width-12,top=18,bottom=118;
    const y=value=>bottom-8-(bottom-top-16)*(value-lo)/span;
    const point=r=>[left+(first===last?(right-left)/2:(right-left)*(Date.parse(r.date)-first)/(last-first)),y(r.value)];
    function el(name,attrs,text){const e=document.createElementNS(ns,name);for(const [k,v] of Object.entries(attrs))e.setAttribute(k,v);if(text!==undefined)e.textContent=text;svg.append(e);return e;}
    el('path',{d:`M${left} ${top}V${bottom}H${right}`,fill:'none',stroke:'#d5dfef'});
    if(previous!==null){
     el('line',{x1:left,y1:y(previous),x2:right,y2:y(previous),stroke:'#8d82c7','stroke-dasharray':'4 4'});
     el('text',{x:right,y:Math.max(12,y(previous)-5),'text-anchor':'end','font-size':11,fill:'#6556a0'},`前期間 ${previous} ${svg.dataset.unit||''}`);
    }
    let segment=[];
    function line(){if(segment.length>1)el('polyline',{points:segment.map(r=>point(r).join(',')).join(' '),fill:'none',stroke:'#6479df','stroke-width':2});segment=[];}
    rows.forEach(r=>{if(r.value===null){line();return;}segment.push(r);});line();
    measured.forEach(r=>{const [cx,cy]=point(r);const c=el('circle',{cx,cy,r:3,fill:'#6479df'});const t=document.createElementNS(ns,'title');t.textContent=`${r.date} ${r.value} ${svg.dataset.unit||''} 日報${r.report_id}`;c.append(t);});
    for(const [x,yPos,text,anchor] of [[left-6,top+7,String(hi),'end'],[left-6,bottom,String(lo),'end'],[left,144,rows[0].date,'start'],[right,144,rows.at(-1).date,'end']])el('text',{x,y:yPos,'text-anchor':anchor,'font-size':11,fill:'#5c7391'},text);
   }
   draw();if(typeof ResizeObserver!=='undefined')new ResizeObserver(draw).observe(svg);
  });
 });
})();
