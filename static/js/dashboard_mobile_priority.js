/* Move the one existing request panel, never clone links or change counts.
   DOM order follows mobile reading/keyboard order; desktop returns to its slot. */
(() => {
 'use strict';
 function initialize() {
 const page = document.querySelector('.dashboard-page.dashboard-design-v2');
 const panel = page && page.querySelector('[data-personal-requests]');
 const attention = page && page.querySelector('.dashboard-attention-list');
 if (!panel || !attention || !window.matchMedia) return;
 const marker = document.createComment('personal requests original position');
 panel.parentNode.insertBefore(marker, panel);
 const media = window.matchMedia('(max-width:600px)');
 const place = () => {
  const active = panel.contains(document.activeElement) ? document.activeElement : null;
  if (media.matches) {
   if (panel.nextElementSibling !== attention) attention.parentNode.insertBefore(panel, attention);
  } else if (marker.nextSibling !== panel) marker.parentNode.insertBefore(panel, marker.nextSibling);
  if (active && document.activeElement !== active) active.focus({preventScroll:true});
 };
 place();
 if (media.addEventListener) media.addEventListener('change', place);
 else media.addListener(place);
 }
 if(document.readyState === 'loading') document.addEventListener('DOMContentLoaded',initialize,{once:true});
 else initialize();
})();
