/* Progressive enhancement for authorized detail images. No automatic retries. */
(() => {
  'use strict';
  document.querySelectorAll('a .detail-image').forEach(initial => {
    const link = initial.closest('a');
    if (!link || link.dataset.imageStateReady) return;
    link.dataset.imageStateReady = '1';
    const panel = document.createElement('div');
    panel.className = 'attachment-load-state';
    const status = document.createElement('span');
    status.setAttribute('role', 'status');
    const retry = document.createElement('button');
    retry.type = 'button';
    retry.className = 'attachment-load-retry';
    retry.textContent = '再読込';
    retry.hidden = true;
    panel.append(status, retry);
    link.after(panel);
    let current = initial;
    const setState = state => {
      panel.hidden = state === 'loaded';
      retry.hidden = state !== 'failed';
      status.textContent = state === 'failed' ? '画像を読み込めませんでした' : state === 'loading' ? '画像を読み込み中…' : '';
      link.dataset.imageLoadState = state;
    };
    const watch = image => {
      setState('loading');
      const finish = () => {
        if (image !== current || !image.isConnected) return;
        setState(image.naturalWidth > 0 ? 'loaded' : 'failed');
      };
      image.addEventListener('load', finish, {once: true});
      image.addEventListener('error', finish, {once: true});
      if (image.complete) finish();
    };
    retry.addEventListener('click', () => {
      if (!link.isConnected || retry.hidden) return;
      // Preserve the exact authorized source/srcset and original anchor URL.
      const replacement = current.cloneNode(false);
      const previous = current;
      current = replacement;
      previous.replaceWith(replacement);
      watch(replacement);
    });
    watch(current);
  });
})();
