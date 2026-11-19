/* Presentation only: keep the original GET form and every filter unchanged. */
(function () {
  'use strict';
  var panel = document.querySelector('.patrol-filter-disclosure');
  if (!panel) return;
  var mobile = window.matchMedia('(max-width: 768px)');
  function adapt() { panel.open = !mobile.matches; }
  adapt();
  mobile.addEventListener('change', adapt);
})();
