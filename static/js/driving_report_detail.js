(function(){
 'use strict';
 function reveal(hash=location.hash){
  let target;try{target=document.getElementById(decodeURIComponent(hash.slice(1)));}catch{return;}
  if(!target)return;
  for(let node=target;node;node=node.parentElement)if(node.tagName==='DETAILS')node.open=true;
  requestAnimationFrame(()=>target.scrollIntoView({block:'start'}));
 }
 document.addEventListener('DOMContentLoaded',()=>reveal());
 window.addEventListener('hashchange',()=>reveal());
 document.addEventListener('click',event=>{
  const link=event.target.closest('a[href^="#"]');if(link)reveal(link.hash);
 });
})();
