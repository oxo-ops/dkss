(function(){
 'use strict';
 const title=document.querySelector('[data-mobile-page-title]');
 if(!title)return;
 const bar=title.closest('.top-bar');
 const normal=s=>String(s||'').replace(/\s+/g,' ').trim();
 const driving=bar.querySelector('.driving-page-title');
 if(driving){
  const heading=driving.querySelector('h2');
  if(heading)title.querySelector('[data-mobile-title-text]').textContent=heading.textContent;
  const office=driving.querySelector(':scope > span');
  if(office){const sub=document.createElement('small');sub.textContent=office.textContent;title.append(sub);}
  driving.classList.add('mobile-title-source');
 }else{
  const expected=normal(title.textContent);
  const original=Array.from(document.querySelectorAll('.main-content h1,.main-content h2')).find(e=>
   !bar.contains(e)&&!e.closest('dialog,[role="dialog"],.modal-bg,[hidden]')&&normal(e.textContent)===expected);
  if(original)original.classList.add('mobile-title-source');
 }
})();
