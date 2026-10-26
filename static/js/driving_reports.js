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
