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
    if(state.status==='completed'){sessionStorage.setItem(positionKey,String(scrollY));location.reload();return;}
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
    if(state.status==='completed'){location.reload();return;}
    reflection.querySelector('[data-reflection-status]').hidden=false;reflection.querySelector('[data-reflection-status]').textContent='振り返りを作成しています。このまま記録を確認できます。';button.textContent='作成中';polls=0;pollTimer=setTimeout(pollReflection,1500);
   }catch(error){reflection.querySelector('[data-reflection-status]').hidden=false;reflection.querySelector('[data-reflection-status]').textContent=error.message;button.disabled=false;button.textContent='再試行';}
  });
  if(reflection?.dataset.status==='pending')pollTimer=setTimeout(pollReflection,1500);
  // Refresh only a previously requested scope whose authorized data changed.
  // An ordinary page open with unchanged data never starts a paid job.
  if(reflection?.dataset.status==='new'&&reflection.dataset.autoRefresh==='true')reflectionForm?.requestSubmit();
  window.addEventListener('pagehide',()=>clearTimeout(pollTimer));
  form?.querySelector('[name=period]')?.addEventListener('change',event=>{if(event.target.value==='custom'){const details=form.querySelector('.driving-extra-filters');if(details)details.open=true;}else{form.requestSubmit();}});
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
