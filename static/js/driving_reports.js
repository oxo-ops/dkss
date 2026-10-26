document.addEventListener('DOMContentLoaded',()=>{
 const ns='http://www.w3.org/2000/svg';
 document.querySelectorAll('[data-driving-chart]').forEach(svg=>{
  let rows;try{rows=JSON.parse(svg.dataset.series).filter(r=>Number.isFinite(Number(r.value))&&/^\d{4}-\d{2}-\d{2}$/.test(r.date)).sort((a,b)=>a.date.localeCompare(b.date));}catch{return;}
  if(!rows.length)return;
  const values=rows.map(r=>Number(r.value)),lo=Math.min(...values),hi=Math.max(...values),span=hi-lo||1;
  const first=Date.parse(rows[0].date),last=Date.parse(rows.at(-1).date);
  const point=(r,i)=>[50+(first===last?250:510*(Date.parse(r.date)-first)/(last-first)),108-78*(Number(r.value)-lo)/span];
  function el(name,attrs,text){const e=document.createElementNS(ns,name);for(const [k,v] of Object.entries(attrs))e.setAttribute(k,v);if(text!==undefined)e.textContent=text;svg.append(e);return e;}
  el('path',{d:'M45 18V112H570',fill:'none',stroke:'#bbcfdf'});
  el('polyline',{points:rows.map((r,i)=>point(r,i).join(',')).join(' '),fill:'none',stroke:'#3a78a7','stroke-width':2});
  rows.forEach((r,i)=>{const [cx,cy]=point(r,i);const c=el('circle',{cx,cy,r:3,fill:'#3a78a7'});const t=document.createElementNS(ns,'title');t.textContent=`${r.date} ${r.value} 日報${r.report_id}`;c.append(t);});
  for(const [x,y,t] of [[2,28,String(hi)],[2,110,String(lo)],[50,135,rows[0].date||'日付不明'],[480,135,rows.at(-1).date||'日付不明']])el('text',{x,y,'font-size':11,fill:'#46647d'},t);
 });
});
