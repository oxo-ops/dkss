/* Presentation only; original GET fields, category links and values are preserved. */
(()=>{'use strict';const panel=document.querySelector('.karte-history-filter-disclosure');if(!panel)return;const mobile=matchMedia('(max-width:768px)');const adapt=()=>{panel.open=!mobile.matches;};adapt();mobile.addEventListener('change',adapt);})();
