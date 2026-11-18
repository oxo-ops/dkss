(function () {
  'use strict';
  const root = document.querySelector('.vehicle-workspace-top');
  if (!root) return;
  const date = root.querySelector('.vehicle-workspace-date');
  const input = date?.querySelector('input');
  const label = date?.querySelector('.vehicle-date-japanese');
  if (input && label) {
    const sync = () => {
      const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(input.value);
      if (!match) return;
      label.textContent = Number(match[2]) + '/' + Number(match[3]);
      input.setAttribute('aria-label', '表示する点検日 ' + match[1] + '年' + Number(match[2]) + '月' + Number(match[3]) + '日');
    };
    sync();
    input.addEventListener('input', sync);
    input.addEventListener('change', sync);
  }
  const actions = root.querySelector('.header-actions');
  const subtitle = root.querySelector('.vehicle-workspace-subtitle');
  const target = root.querySelector('#vehicle-target-settings');
  const button = root.querySelector('.vehicle-search-action');
  if (target && button) {
    button.hidden = false;
    root.classList.add('vehicle-toolbar-ready');
    const update = () => button.setAttribute('aria-expanded', String(target.open));
    target.addEventListener('toggle', update);
    button.addEventListener('click', () => { target.open = !target.open; update(); if(target.open) target.querySelector('input')?.focus({preventScroll:true}); });
    update();
  }
  const media = window.matchMedia('(max-width:600px)');
  function layout() {
    if (!date || !actions || !subtitle) return;
    if (media.matches) subtitle.appendChild(date);
    else actions.insertBefore(date, actions.firstChild);
  }
  media.addEventListener('change', layout);
  layout();
  const defects = root.querySelector('.vehicle-other-defects-menu');
  if (defects) {
    document.addEventListener('click', event => { if (!defects.contains(event.target)) defects.open = false; });
    defects.addEventListener('keydown', event => { if(event.key==='Escape'){defects.open=false;defects.querySelector('summary').focus();} });
    defects.querySelector('a')?.addEventListener('click', () => {defects.open=false;});
  }
})();
