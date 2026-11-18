/* Relocate existing guide entry; preserve its handlers, targets and desktop home. */
(()=>{'use strict';const planner=document.querySelector('[data-inspection-planner]'),guide=document.getElementById('firstUseGuide');if(!planner)return;const actions=planner.querySelector('.ip-top-actions'),home=guide?.parentElement,anchor=guide?.nextSibling,mq=matchMedia('(max-width:700px)');
function sync(){if(mq.matches){if(guide)actions.append(guide);document.body.classList.add('ip-mobile-workspace');}else{document.body.classList.remove('ip-mobile-workspace');if(guide&&home)home.insertBefore(guide,anchor?.parentElement===home?anchor:null);}window.dispatchEvent(new Event('resize'));}
mq.addEventListener('change',sync);sync();})();
