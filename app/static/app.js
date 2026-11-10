(() => {
  'use strict';

  const $ = (selector, scope = document) => scope.querySelector(selector);
  const icons = {
    arrow: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true"><path d="M4 12h15m-6-6 6 6-6 6"/></svg>',
    lock: '<svg viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true"><rect x="5" y="10" width="14" height="11" rx="2"/><path d="M8 10V7a4 4 0 0 1 8 0v3M12 14v3"/></svg>',
    unlock: '<svg viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true"><rect x="5" y="10" width="14" height="11" rx="2"/><path d="M8 10V7a4 4 0 0 1 7.5-2M12 14v3"/></svg>',
    image: '<svg viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8" cy="8" r="1.5"/><path d="m3 18 6-6 4 4 3-4 5 6"/></svg>',
    check: '<svg viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor" stroke-width="1.7" aria-hidden="true"><path d="m5 12 4.5 4.5L19 7"/></svg>',
    download: '<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true"><path d="M12 3v12m-5-5 5 5 5-5M4 16v5h16v-5"/></svg>',
    expand: '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true"><path d="M14 4h6v6M20 4l-7 7M10 20H4v-6M4 20l7-7"/></svg>',
    chat: '<svg viewBox="0 0 24 24" width="23" height="23" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true"><path d="M21 11.5a8.5 8.5 0 0 1-8.5 8.5H6l-4 3V11.5A9.5 9.5 0 0 1 12.5 2 8.5 8.5 0 0 1 21 11.5Z"/><path d="M7 10h10M7 14h6"/></svg>',
    close: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true"><path d="m6 6 12 12M18 6 6 18"/></svg>',
    copy: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true"><rect x="8" y="8" width="12" height="13" rx="2"/><path d="M15 8V3H3v13h5"/></svg>',
    left: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true"><path d="m14 5-7 7 7 7"/></svg>',
    right: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true"><path d="m10 5 7 7-7 7"/></svg>',
    mail: '<svg viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true"><rect x="3" y="5" width="18" height="14" rx="2"/><path d="m3 6 9 7 9-7"/></svg>',
  };
  const esc = (value) => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const state = {
    slug: getSlug(), data: null, latestOrder: null, modal: null, lightboxIndex: 0,
    checkoutEmail: '', recoveryToken: '', recoveryPurpose: '', busy: false,
    toastTimer: null, pollTimer: null, pollCount: 0, previousFocus: null,
    returnRecovery: false, swipe: null, touchPointers: new Set(),
    deckIndex: 0, deckCollectionKey: null, imageNodes: new Map(), suppressClickUntil: 0,
  };
  const modal = $('#modal');
  const modalContent = $('#modalContent');

  function getSlug() {
    const match = location.pathname.match(/^\/c\/([^/]+)/);
    if (!match) return null;
    try { return decodeURIComponent(match[1]); } catch { return null; }
  }
  function routeOrderId() {
    const match = location.pathname.match(/^\/checkout\/demo\/([^/]+)\/?$/);
    if (!match) return null;
    try { return decodeURIComponent(match[1]); } catch { return null; }
  }
  function safeLocalUrl(value) {
    if (!value) return '';
    try {
      const url = new URL(value, location.origin);
      return url.origin === location.origin && /^https?:$/.test(url.protocol) ? url.pathname + url.search : '';
    } catch { return ''; }
  }
  function downloadUrl(value) {
    const local = safeLocalUrl(value);
    if (!local) return '';
    const url = new URL(local, location.origin);
    url.searchParams.set('download', '1');
    return url.pathname + url.search;
  }
  function money(cents = 0, currency = 'CNY') {
    return new Intl.NumberFormat('zh-CN', {style:'currency', currency, minimumFractionDigits:2, maximumFractionDigits:2}).format(cents / 100).replace('CN¥', '¥');
  }
  function price() { return money(state.data?.collection.price_cents, state.data?.collection.currency); }
  function receiptReference() { return state.data?.access?.order_reference || state.latestOrder?.reference || ''; }
  function visibleItems() { return (state.data?.collection.items || []).filter(item => item.unlocked && safeLocalUrl(item.url)); }
  function pendingOrder() { return state.latestOrder?.status === 'pending' ? state.latestOrder : null; }

  async function request(path, options = {}) {
    const method = options.method || 'GET';
    const headers = {Accept:'application/json'};
    if (method !== 'GET') {
      headers['Content-Type'] = 'application/json';
      headers['X-CSRF-Token'] = state.data?.csrf_token || '';
    }
    let response;
    try {
      response = await fetch(path, {
        method, headers, credentials:'same-origin', cache:'no-store',
        ...(method !== 'GET' ? {body:JSON.stringify(options.body || {})} : {}),
      });
    } catch { throw new Error('网络连接暂时不可用，请检查网络后重试。'); }
    let result;
    try { result = await response.json(); } catch { result = {}; }
    if (!response.ok) {
      let message = typeof result.detail === 'string' ? result.detail : '暂时无法完成操作，请稍后重试。';
      if (response.status === 429) message = '操作有点频繁，请稍等片刻再试。';
      if (response.status === 422) message = '请检查填写的信息后重试。';
      const error = new Error(message);
      error.status = response.status;
      throw error;
    }
    return result;
  }

  async function loadCollection({quiet = false} = {}) {
    if (!quiet) $('#loadingState').hidden = false;
    const query = new URLSearchParams();
    const isPaymentReturn = location.pathname === '/payment/return';
    const returnReference = isPaymentReturn ? (new URLSearchParams(location.search).get('out_trade_no') || '').trim() : '';
    const incompleteReturn = isPaymentReturn && !returnReference;
    // An incomplete return can only load public settings for recovery. Even an
    // existing purchase of the default collection must not show as its result.
    if (incompleteReturn) state.returnRecovery = true;
    if (!incompleteReturn && state.slug && !state.returnRecovery) query.set('slug',state.slug);
    else if (isPaymentReturn) {
      // The backend resolves this only against session-owned orders. It is a
      // collection selector, never evidence that payment succeeded.
      if (returnReference) query.set('order_reference',returnReference);
    } else {
      const orderId = routeOrderId();
      if (orderId) query.set('order_id',orderId);
    }
    const queryString = query.toString();
    let data;
    const selectingOrder = query.has('order_reference') || query.has('order_id');
    try {
      data = await request('/api/bootstrap' + (queryString ? '?' + queryString : ''));
      if (selectingOrder) state.returnRecovery = false;
    } catch (error) {
      if (!selectingOrder || error.status !== 404) throw error;
      // A payment return URL does not prove ownership. Load public site
      // settings/CSRF only, then offer recovery without displaying an unrelated
      // default collection or treating the returned order as paid.
      data = await request('/api/bootstrap');
      state.returnRecovery = true;
    }
    const collectionKey = data.collection.id + '@' + data.collection.version;
    if (state.deckCollectionKey !== collectionKey) {
      state.deckIndex = 0;
      state.imageNodes.clear();
      state.deckCollectionKey = collectionKey;
    }
    const allowedUrls = new Set((data.collection.items || []).filter(item => item.unlocked).map(item => safeLocalUrl(item.url)).filter(Boolean));
    for (const [key, entry] of state.imageNodes) if (!allowedUrls.has(entry.url)) state.imageNodes.delete(key);
    state.data = data;
    state.slug = state.returnRecovery ? null : data.collection.slug;
    state.latestOrder = state.returnRecovery ? null : data.latest_order || null;
    document.title = state.returnRecovery ? '恢复购买访问 — PaidDrive' : data.collection.title + ' — PaidDrive';
    render();
    $('#loadingState').hidden = true;
    $('#app').setAttribute('aria-busy','false');
    return data;
  }

  function render() {
    const {collection:c, access:a, site} = state.data;
    const banner = $('#environmentBanner');
    banner.hidden = site.mode !== 'demo';
    banner.innerHTML = '<span class="environment-dot"></span><strong>演示模式</strong> &nbsp;·&nbsp; 不会真实扣款';
    if (state.returnRecovery) { renderReturnRecovery(); return; }
    state.deckIndex = Math.max(0,Math.min(state.deckIndex,c.items.length-1));
    const pending = pendingOrder();
    $('#app').innerHTML = `
      <div class="collection-wrap" id="collection">
        <section class="product-intro" aria-labelledby="collectionTitle">
          <div class="eyebrow"><span class="dot"></span>一小叠，值得留住的画面</div>
          <h1 id="collectionTitle">${esc(c.title)}</h1>
          <div class="product-meta"><span class="preview-chip">${a.unlocked ? icons.check + ' 整套已解锁' : esc(c.preview_count) + ' 张免费预览'}</span><span>共 ${esc(c.total_count)} 张</span><span class="meta-divider"></span><span>一次购买</span></div>
        </section>
        ${pending && !a.unlocked ? `<div class="pending-strip" role="status"><span>有一笔订单等待确认</span><button class="text-button" data-action="pending" type="button">${pending.mode === 'demo' ? '继续演示' : '查询付款'} ↗</button></div>` : ''}
        <section class="deck-gallery" id="gallery" tabindex="0" role="region" aria-roledescription="轮播图" aria-label="合集图片，可左右滑动，或使用方向键切换">
          <div class="collection-deck" id="deckStage"><div class="deck-back back-two" aria-hidden="true"></div><div class="deck-back back-one" aria-hidden="true"></div><div id="deckCardHost"></div></div>
          <div class="deck-controls"><button class="deck-arrow" id="deckPrevious" data-action="prev-deck" type="button" aria-label="上一张图片">${icons.left}</button><div class="deck-position"><p id="deckCounter" aria-live="polite" aria-atomic="true"></p><span id="deckHint">左右滑动，翻看下一张</span></div><button class="deck-arrow" id="deckNext" data-action="next-deck" type="button" aria-label="下一张图片">${icons.right}</button></div>
          <div class="deck-position-picker"><div class="deck-dots-visual" aria-hidden="true">${c.items.map((item,index) => `<span class="deck-dot ${item.unlocked ? 'free-dot' : 'locked-dot'}" data-deck-dot="${index}"></span>`).join('')}</div><input id="deckPosition" class="deck-range" type="range" min="0" max="${Math.max(0,c.items.length-1)}" step="1" value="${state.deckIndex}" aria-label="选择图片位置"></div>
        </section>
        <section class="collection-value" aria-label="购买内容"><div class="value-icon">${a.unlocked ? icons.check : icons.unlock}</div><div><h2>${a.unlocked ? '整套已解锁，随时回来查看' : '一次购买，解锁全部 ' + esc(c.total_count) + ' 张'}</h2><p>可反复查看与下载<span>·</span>无需注册</p></div></section>
        ${renderPurchaseDetails()}
      </div>`;
    renderDeck();
    renderPurchaseBar();
    if (state.modal === 'lightbox') renderLightbox();
  }

  function mountCollectionImage(host, item, className) {
    const url = item?.unlocked ? safeLocalUrl(item.url) : '';
    if (!host || !url) return;
    const key = state.deckCollectionKey + '/' + item.id;
    let entry = state.imageNodes.get(key);
    if (!entry || entry.url !== url) {
      const image = document.createElement('img');
      image.alt = item.title;
      image.decoding = 'async';
      image.draggable = false;
      if (item.width) image.width = Number(item.width);
      if (item.height) image.height = Number(item.height);
      image.src = url;
      entry = {element:image,url};
      state.imageNodes.set(key,entry);
    }
    entry.element.className = className;
    host.replaceChildren(entry.element);
  }

  function renderDeck(direction = 0) {
    if (!state.data || state.returnRecovery || !$('#deckCardHost')) return;
    const {collection:c,access:a} = state.data;
    const index = state.deckIndex;
    const item = c.items[index];
    if (!item) return;
    const allowed = Boolean(item.unlocked && safeLocalUrl(item.url));
    const animation = direction > 0 ? ' enter-next' : direction < 0 ? ' enter-previous' : '';
    const number = String(index+1).padStart(2,'0');
    $('#deckCardHost').innerHTML = allowed ? `<article class="deck-card available${animation}" aria-label="第 ${index+1} 张，共 ${c.total_count} 张"><button class="deck-image-button" type="button" data-action="lightbox" data-image-id="${esc(item.id)}" aria-label="放大查看：${esc(item.title)}"><span class="deck-image-viewport" id="deckImageHost"></span><span class="deck-image-tag">${a.unlocked ? '已解锁' : '免费预览'}</span><span class="deck-expand">${icons.expand}</span></button><div class="deck-card-caption"><span class="deck-card-number">${number}</span><h2>${esc(item.title)}</h2>${a.unlocked ? `<a class="deck-image-download" href="${esc(downloadUrl(item.url))}" download aria-label="下载图片：${esc(item.title)}">${icons.download}<span>下载图片</span></a>` : '<span class="deck-caption-note">轻点放大</span>'}</div></article>` : `<article class="deck-card locked${animation}" aria-label="第 ${index+1} 张，共 ${c.total_count} 张，购买后解锁"><div class="deck-locked-art tone-${index % 4}"><span class="scene-sun" aria-hidden="true"></span><span class="scene-hill hill-one" aria-hidden="true"></span><span class="scene-hill hill-two" aria-hidden="true"></span><div class="deck-lock-copy"><span class="deck-lock-seal">${icons.lock}</span><p class="lock-kicker">完整的风景，值得慢慢看</p><h2>还有 ${Math.max(0,c.total_count-c.preview_count)} 张，<br>等你打开。</h2><p>解锁整套 ${esc(c.total_count)} 张图片</p><button class="deck-unlock-button" type="button" data-action="purchase">解锁整套 <span>${esc(price())}</span>${icons.arrow}</button></div></div><div class="deck-card-caption"><span class="deck-card-number">${number}</span><h2>${esc(item.title)}</h2><span class="deck-caption-note">购买后查看</span></div></article>`;
    if (allowed) mountCollectionImage($('#deckImageHost'),item,'deck-image');
    $('#deckPrevious').disabled = index === 0;
    $('#deckNext').disabled = index === c.items.length - 1;
    $('#deckCounter').innerHTML = `<strong>${number}</strong><span>/ ${String(c.total_count).padStart(2,'0')}</span>`;
    $('#deckHint').textContent = allowed ? '左右滑动 · 轻点图片放大' : '喜欢这套画面？一次解锁全部';
    const range = $('#deckPosition');
    range.value = String(index);
    range.disabled = c.items.length <= 1;
    range.setAttribute('aria-valuetext',`第 ${index+1} 张，共 ${c.total_count} 张，${allowed ? a.unlocked ? '已解锁' : '免费预览' : '购买后解锁'}`);
    document.querySelectorAll('[data-deck-dot]').forEach(dot => dot.classList.toggle('current',Number(dot.dataset.deckDot) === index));
  }

  function goToDeck(index, {focus = false} = {}) {
    if (!state.data || state.returnRecovery) return;
    const target = Math.max(0,Math.min(Math.trunc(Number(index)),state.data.collection.items.length-1));
    if (!Number.isFinite(target)) return;
    const direction = target - state.deckIndex;
    state.deckIndex = target;
    renderDeck(direction);
    if (focus) $('#gallery')?.focus({preventScroll:true});
  }

  function renderPurchaseBar() {
    const {collection:c,access:a} = state.data;
    const download = safeLocalUrl(c.download_url);
    $('#mobileBar').innerHTML = `<div class="mobile-bar ${a.unlocked ? 'purchased' : ''}"><div class="mobile-price">${a.unlocked ? '已购买' : esc(price())}<span>${a.unlocked ? '随时再看' : '一次购买 · 不自动续费'}</span></div><div class="mobile-actions">${a.unlocked ? `<button class="primary-button dark" type="button" data-action="view-images">查看图片</button>${download ? `<a class="secondary-button mobile-download" href="${esc(download)}" download>整套 ZIP</a>` : ''}` : `<button class="primary-button" type="button" data-action="purchase">${pendingOrder() ? '继续付款' : '解锁全部 ' + c.total_count + ' 张'} ${icons.arrow}</button>`}</div></div>`;
  }

  function renderReturnRecovery() {
    $('#app').innerHTML = `<section class="return-recovery" aria-labelledby="returnRecoveryTitle"><div class="recovery-symbol">${icons.lock}</div><p class="eyebrow">找回购买记录</p><h1 id="returnRecoveryTitle">付款后，回到了<br>另一个浏览器？</h1><p class="recovery-lead">当前浏览器暂未识别到这笔购买记录。请先回到发起付款时的浏览器，打开原来的合集页面并查询付款结果。</p><div class="recovery-explanation"><h2>已经换了设备或浏览器？</h2><p>如果添加并验证过邮箱，可通过邮箱恢复访问；没有填写邮箱，也可以联系微信客服，提供订单和付款信息。</p></div><div class="recovery-actions"><button class="primary-button" type="button" data-action="restore">邮箱恢复访问 ${icons.arrow}</button><button class="secondary-button" type="button" data-action="support">联系微信客服</button><button class="text-button small-link" type="button" data-action="retry">重新检查当前浏览器</button></div><p class="field-help">返回链接本身不能证明购买成功。确认付款结果前，请勿重复支付。</p></section>`;
    $('#mobileBar').innerHTML = '<div class="mobile-bar recovery-bar"><button class="primary-button" type="button" data-action="restore">邮箱恢复访问</button><button class="secondary-button" type="button" data-action="support">微信客服</button></div>';
  }

  function renderPurchaseDetails() {
    const {collection:c,access:a,site} = state.data;
    return `<details class="purchase-details"><summary><span>${a.unlocked ? '购买记录与找回访问' : '合集说明与购买须知'}</span>${icons.right}</summary><div class="purchase-details-content"><p class="details-creator">${esc(c.creator)}</p><p>${esc(c.description || c.subtitle)}</p><p>购买内容为当前固定合集。在合集持续提供期间，可反复查看与下载。</p>${a.unlocked ? `<div class="receipt-row"><div><span class="receipt-label">订单号</span><span class="order-reference">${esc(a.order_reference)}</span></div><button type="button" data-action="copy-order" aria-label="复制订单号">${icons.copy}</button></div><p class="details-email">${a.email_verified ? '找回邮箱已验证：' + esc(a.email_hint || '邮箱已保存') : '当前浏览器会记住购买记录。添加并验证邮箱，可在其他设备恢复访问。'}</p>${site.email_enabled ? `<button class="text-button small-link" type="button" data-action="attach">${a.email_verified ? '更换找回邮箱' : '添加或验证找回邮箱'}</button>` : '<p>请保存订单号，丢失访问时可联系微信客服。</p>'}<p>整套下载为 ZIP 压缩文件，可在浏览器下载记录或文件应用中查找，解压后查看。</p>` : '<p>邮箱可以不填。添加并验证邮箱，方便以后在其他设备恢复访问；没有邮箱也可联系微信客服协助。</p>'}<button class="text-button small-link" data-action="support" type="button">联系微信客服 ↗</button></div></details>`;
  }

  function shell({eyebrow='', title, lead='', body='', actions=''}) {
    return `<div class="modal-shell"><button class="modal-close" type="button" data-action="close" aria-label="关闭弹窗">${icons.close}</button>${eyebrow ? `<p class="modal-eyebrow">${esc(eyebrow)}</p>` : ''}<h2 id="modalTitle" tabindex="-1">${esc(title)}</h2>${lead ? `<p class="modal-lead">${esc(lead)}</p>` : ''}${body}${actions}</div>`;
  }
  function openModal(name, html, {lightbox=false} = {}) {
    if (!modal.open) state.previousFocus = document.activeElement;
    const wasLightbox = state.modal === 'lightbox';
    state.modal = name;
    modal.classList.toggle('lightbox', lightbox);
    modalContent.innerHTML = html;
    if (!modal.open) modal.showModal();
    document.body.style.overflow = 'hidden';
    if (wasLightbox && !lightbox) renderDeck();
    requestAnimationFrame(() => {
      const mobile = window.matchMedia('(max-width: 760px), (pointer: coarse)').matches;
      const focus = mobile ? modal.querySelector('#modalTitle') || modal.querySelector('button') : modal.querySelector('input:not(:disabled)') || modal.querySelector('button');
      focus?.focus({preventScroll:true});
    });
  }
  function closeModal() {
    if (state.busy) return;
    modal.close();
  }
  modal.addEventListener('close', () => {
    state.modal = null;
    state.swipe = null;
    state.touchPointers.clear();
    document.body.style.overflow = '';
    renderDeck();
    if (state.previousFocus?.isConnected) state.previousFocus.focus({preventScroll:true});
    else ($('#gallery') || document.querySelector('[data-action="purchase"]'))?.focus({preventScroll:true});
  });
  modal.addEventListener('cancel', event => { if (state.busy) event.preventDefault(); });
  modal.addEventListener('click', event => {
    if (event.target !== modal || state.busy) return;
    const rect = modal.getBoundingClientRect();
    if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) closeModal();
  });
  function showToast(message, error=false) {
    clearTimeout(state.toastTimer);
    const toast = $('#toast');
    toast.textContent = message;
    toast.classList.toggle('error',error);
    toast.hidden = false;
    state.toastTimer = setTimeout(() => { toast.hidden = true; }, error ? 6500 : 4200);
  }
  function formMessage(message, error=false) {
    let box = $('.form-message',modal);
    if (!box) {
      box = document.createElement('div');
      box.setAttribute('role',error ? 'alert' : 'status');
      ($('form',modal) || $('.modal-shell',modal)).appendChild(box);
    }
    box.className = 'form-message' + (error ? ' form-error' : '');
    box.textContent = message;
  }
  function setBusy(busy, button, label) {
    state.busy = busy;
    if (button) {
      if (busy) {
        button.dataset.original = button.innerHTML;
        button.textContent = label || '请稍候…';
      } else if (button.dataset.original) button.innerHTML = button.dataset.original;
      button.disabled = busy;
    }
  }
  function demoMailNote() {
    return state.data.site.mail_mode === 'file' ? '<div class="demo-note">仅本地演示：不会发送邮件。验证和找回链接保存在本地邮件目录（默认 data/outbox/）。</div>' : '';
  }

  function showCheckout() {
    if (!state.data) return;
    if (state.data.access.unlocked) { $('#gallery')?.scrollIntoView(); return; }
    if (pendingOrder()) { showPending(); return; }
    const {collection:c,site} = state.data;
    openModal('checkout', shell({eyebrow:'确认购买',title:'解锁这套图片。',body:`
      <div class="checkout-summary"><div><strong>${esc(c.title)}</strong><small>共 ${esc(c.total_count)} 张图片 · 一次购买</small></div><span class="summary-price">${esc(price())}</span></div>
      ${site.mode === 'demo' ? '<div class="demo-note">演示模式 · 不会真实扣款。下一步可模拟付款，体验解锁流程。</div>' : ''}
      <form data-form="checkout">
        <fieldset class="payment-fieldset"><legend class="field-label payment-legend">付款方式</legend><div class="payment-options"><label class="payment-choice"><input type="radio" name="payment_method" value="wxpay" checked><span class="pay-icon">微</span>微信支付</label><label class="payment-choice"><input type="radio" name="payment_method" value="alipay"><span class="pay-icon alipay">支</span>支付宝</label></div></fieldset>
        <label class="field-label" for="checkoutEmail">找回邮箱 <span class="optional">（选填）</span></label>
        <input class="text-input" id="checkoutEmail" name="email" type="email" autocomplete="email" maxlength="254" placeholder="you@example.com" ${site.email_enabled ? '' : 'disabled'} value="${esc(state.checkoutEmail)}">
        <p class="field-help">${site.email_enabled ? (site.mail_mode === 'file' ? '可不填写。本地演示不会发送邮件，付款后的验证链接会保存在本地邮件目录。' : '付款后验证邮箱，即可在其他设备恢复访问。无需注册，也无需密码。') : '邮箱找回暂未开放。请保存订单号，丢失访问时可联系微信客服。'}</p>
        <div class="checkout-total"><span>合计 · 一次付款</span><strong>${esc(price())}</strong></div>
        <button class="primary-button" type="submit">${site.mode === 'demo' ? '继续演示付款' : '支付 ' + esc(price())} ${icons.arrow}</button>
        <p class="modal-footnote">${site.mode === 'demo' ? '仅体验购买流程，不会真实扣款。' : '将跳转至 ZPay 完成付款。'}</p>
      </form>`}));
  }

  function showDemoCheckout(order) {
    if (state.data.site.mode !== 'demo' || order.mode !== 'demo') { showPending(); return; }
    state.latestOrder = order;
    openModal('demo',shell({eyebrow:'演示付款',title:'体验解锁流程。',lead:'模拟付款成功后，即可查看整套示例图片。不会真实扣款。',body:`<div class="checkout-summary"><div><strong>${esc(state.data.collection.title)}</strong><small>演示订单 · ${esc(order.reference)}</small></div><span class="summary-price">${esc(price())}</span></div><div class="demo-note">演示模式 · 不会真实扣款。此操作仅模拟成功付款，不会发起 ZPay 交易。</div><div class="modal-actions"><button class="primary-button" data-action="demo-pay" type="button">模拟付款成功 ${icons.arrow}</button><button class="secondary-button" data-action="close" type="button">稍后再说</button></div>`}));
  }
  function showPending() {
    const order = pendingOrder();
    if (!order) { showCheckout(); return; }
    if (order.mode === 'demo' && state.data.site.mode === 'demo') { showDemoCheckout(order); return; }
    openModal('pending',shell({eyebrow:'付款状态',title:'正在等待付款确认。',lead:'如果你已完成付款，可以查询付款结果，无需重复支付。',body:`<div class="receipt-row"><div><span class="receipt-label">订单号</span><span class="order-reference">${esc(order.reference)}</span></div><button type="button" data-action="copy-order" aria-label="复制订单号">${icons.copy}</button></div><div class="modal-actions"><button class="primary-button" data-action="check-payment" type="button">查询付款结果 ${icons.arrow}</button>${order.payment_url ? '<button class="secondary-button" data-action="continue-payment" type="button">继续前往付款</button>' : ''}<button class="secondary-button" data-action="support" type="button">联系微信客服</button></div>`}));
  }
  function showSuccess() {
    const {collection:c,access:a,site} = state.data;
    const download = safeLocalUrl(c.download_url);
    openModal('success',shell({eyebrow:site.mode === 'demo' ? '演示购买完成' : '购买成功',title:'整套图片已解锁。',lead:`全部 ${c.total_count} 张图片已解锁，可反复查看和下载。`,body:`<div class="success-seal">${icons.check}</div><div class="receipt-row"><div><span class="receipt-label">请保存订单号</span><span class="order-reference">${esc(a.order_reference)}</span></div><button type="button" data-action="copy-order" aria-label="复制订单号">${icons.copy}</button></div><div class="success-email-box"><p>${a.email_verified ? '已验证的邮箱可帮助你在其他设备恢复访问。' : '当前浏览器会记住访问权限。添加并验证邮箱可在其他设备找回；也可保存订单号，联系微信客服协助。'}</p>${site.email_enabled && !a.email_verified ? '<button class="text-button small-link" type="button" data-action="attach">添加或验证找回邮箱</button>' : ''}</div>${site.mail_mode === 'file' && state.checkoutEmail ? '<p class="field-help">演示验证邮件已创建，没有发送真实邮件。请在本地邮件目录（默认 data/outbox/）中打开验证链接。</p>' : ''}<div class="modal-actions"><button class="primary-button dark" type="button" data-action="explore">查看我的图片 ${icons.arrow}</button>${download ? `<a class="secondary-button" href="${esc(download)}" download>${icons.download}下载整套 ZIP</a>` : ''}</div>`}));
  }

  function showRestore() {
    if (!state.data) { showToast('请先刷新页面，连接恢复后再找回购买记录。',true); return; }
    const enabled = state.data.site.email_enabled;
    openModal('restore',shell({eyebrow:'已经买过',title:'恢复访问。',lead:state.data.site.mail_mode === 'file' ? '填写购买记录中已验证的邮箱。本地演示会将找回链接保存到邮件目录，不会发送邮件。' : '填写购买记录中已验证的邮箱，我们会发送临时链接，帮你重新打开合集。',body:enabled ? `${demoMailNote()}<form data-form="restore"><label class="field-label" for="restoreEmail">已验证的找回邮箱</label><input class="text-input" id="restoreEmail" name="email" type="email" autocomplete="email" placeholder="you@example.com" maxlength="254" required><div class="modal-actions"><button class="primary-button" type="submit">${state.data.site.mail_mode === 'file' ? '生成演示找回链接' : '发送找回链接'} ${icons.arrow}</button></div></form><p class="modal-footnote">没有填写邮箱？<button type="button" class="text-button small-link" data-action="support">联系微信客服</button>。</p>` : `<p class="empty-message">邮箱找回暂未开放。请联系微信客服，并提供订单和付款信息。</p><div class="modal-actions"><button class="primary-button" data-action="support" type="button">打开微信客服 ${icons.arrow}</button></div>`}));
  }
  function showAttach() {
    if (!state.data?.access?.unlocked || !state.data.site.email_enabled) return;
    const verified = state.data.access.email_verified;
    openModal('attach',shell({eyebrow:'方便下次访问',title:verified ? '更换找回邮箱。' : '添加找回邮箱。',lead:state.data.site.mail_mode === 'file' ? '当前浏览器已有访问权限，可以添加邮箱。本地演示请使用邮件目录中的验证链接。' : verified ? '新邮箱完成验证后，才会替换本次购买的找回邮箱。' : '在当前浏览器仍能访问时添加邮箱。完成邮件验证后，即可用于以后找回。',body:`${demoMailNote()}<form data-form="attach"><label class="field-label" for="attachEmail">${verified ? '新的找回邮箱' : '找回邮箱'}</label><input class="text-input" id="attachEmail" name="email" type="email" autocomplete="email" maxlength="254" required placeholder="you@example.com" value="${esc(state.checkoutEmail)}"><p class="field-help">无需密码或注册。验证期间，当前浏览器仍可查看已购图片。</p><div class="modal-actions"><button class="primary-button" type="submit">${state.data.site.mail_mode === 'file' ? '生成演示验证链接' : '发送验证链接'} ${icons.arrow}</button></div></form>`}));
  }
  function showSupport() {
    if (!state.data) { showToast('暂时无法读取客服信息，请稍后刷新页面。',true); return; }
    const {site} = state.data;
    const qr = safeLocalUrl(site.support_qr_url);
    const reference = state.returnRecovery ? '' : receiptReference();
    openModal('support',shell({eyebrow:'需要帮助',title:'联系微信客服。',lead:'遇到付款或访问问题，可通过微信联系我们，并提供订单和付款信息。',body:`${qr ? `<div class="qr-frame"><img src="${esc(qr)}" alt="${site.support_is_placeholder ? '微信客服二维码占位图，无法扫码。' : '扫描二维码联系微信客服'}" width="260" height="260"></div>` : ''}${site.support_is_placeholder ? '<p class="placeholder-label">微信客服二维码待设置。当前为占位图，无法扫码。</p>' : `<a class="secondary-button" href="${esc(qr)}" download>${icons.download}保存二维码</a><p class="field-help">可截图保存二维码；若已将二维码图片保存到相册，在微信扫一扫中选择相册识别。下载的图片也可能保存在浏览器下载记录或文件应用中。</p>`}${reference ? `<div class="receipt-row"><div><span class="receipt-label">订单号</span><span class="order-reference">${esc(reference)}</span></div><button type="button" data-action="copy-order" aria-label="复制订单号">${icons.copy}</button></div>` : '<p class="modal-footnote">如果已有订单，请准备好订单号和付款信息。</p>'}<p class="field-help modal-title-rule">客服会核实付款归属后恢复访问。订单号用于查找记录，不能单独作为购买凭证。</p>`}));
  }

  function showLightbox(imageId) {
    const items = visibleItems();
    const index = items.findIndex(item => String(item.id) === String(imageId));
    if (index < 0) return;
    state.lightboxIndex = index;
    renderLightbox();
  }
  function renderLightbox() {
    const items = visibleItems();
    const item = items[state.lightboxIndex];
    if (!item) return;
    const paid = state.data.access.unlocked;
    const imageUrl = safeLocalUrl(item.url);
    const fullIndex = state.data.collection.items.findIndex(candidate => String(candidate.id) === String(item.id));
    if (fullIndex >= 0) state.deckIndex = fullIndex;
    openModal('lightbox',`<div class="lightbox-shell"><div class="lightbox-head"><h2 id="modalTitle" tabindex="-1">${esc(item.title)}</h2><button class="lightbox-close" type="button" data-action="close" aria-label="关闭图片">${icons.close}</button></div><div class="lightbox-stage"><div class="lightbox-image-host" id="lightboxImageHost"></div>${items.length > 1 ? `<button class="lightbox-nav prev" type="button" data-action="prev-image" aria-label="上一张图片">${icons.left}</button><button class="lightbox-nav next" type="button" data-action="next-image" aria-label="下一张图片">${icons.right}</button>` : ''}</div><div class="lightbox-bottom"><span>${paid ? '已购图片' : '免费预览'}</span><span class="lightbox-counter" aria-live="polite">第 ${state.lightboxIndex+1} / ${items.length} 张</span><span class="lightbox-gesture-hint">左右滑动或点箭头切换</span></div>${paid ? `<div class="lightbox-actions"><a class="primary-button dark" href="${esc(downloadUrl(imageUrl))}" download>${icons.download}下载图片</a><a class="secondary-button" href="${esc(imageUrl)}" target="_blank" rel="noopener noreferrer">打开原图 ↗</a></div><p class="lightbox-save-help">下载可能在浏览器中打开图片。需要时可打开原图，再使用浏览器的保存功能。</p>` : '<div class="lightbox-actions single"><button class="primary-button" data-action="purchase" type="button">解锁整套图片 ↗</button></div>'}</div>`,{lightbox:true});
    mountCollectionImage($('#lightboxImageHost'),item,'lightbox-image');
  }

  function stepImage(delta) {
    const items = visibleItems();
    if (!items.length) return;
    state.lightboxIndex = (state.lightboxIndex + delta + items.length) % items.length;
    renderLightbox();
  }

  function showRedeem() {
    const verify = state.recoveryPurpose === 'verify';
    openModal('redeem',shell({eyebrow:verify ? '验证邮箱' : '恢复访问',title:verify ? '确认你的邮箱。' : '欢迎回来。',lead:verify ? '确认邮箱后，即可启用找回功能，并在当前浏览器打开已购合集。' : '使用这条找回链接，在当前浏览器重新打开已购合集。',body:state.recoveryToken ? `<p class="field-help">这条临时链接仅能使用一次。请确认这是你本人申请的链接。</p><div class="modal-actions"><button class="primary-button" type="button" data-action="redeem">${verify ? '验证邮箱并打开合集' : '恢复访问'} ${icons.arrow}</button></div>` : `<div class="form-message form-error" role="alert">链接不完整，请重新申请找回链接，或联系微信客服。</div><div class="modal-actions"><button class="primary-button" type="button" data-action="restore">重新申请链接 ${icons.arrow}</button></div>`}));
  }

  async function refreshPayment({silent=false} = {}) {
    const order = state.latestOrder;
    if (!order) return false;
    const updated = await request('/api/orders/' + encodeURIComponent(order.id) + '/refresh',{method:'POST'});
    state.latestOrder = updated;
    if (updated.collection_slug) state.slug = updated.collection_slug;
    if (updated.status === 'paid') {
      clearTimeout(state.pollTimer);
      await loadCollection({quiet:true});
      if (state.data.access.unlocked) {
        if (!state.busy) showSuccess();
        return true;
      }
    } else {
      await loadCollection({quiet:true});
      if (!silent) showToast('付款尚未确认，请稍后再次查询。');
    }
    return false;
  }
  async function pollPayment() {
    if (!pendingOrder() || state.pollCount >= 6) return;
    state.pollCount += 1;
    try {
      const paid = await refreshPayment({silent:true});
      if (paid) return;
    } catch { /* Leave the pending order visible and offer a manual recheck. */ }
    if (pendingOrder() && state.pollCount < 6) state.pollTimer = setTimeout(pollPayment,6000);
  }

  async function copyOrder() {
    const text = receiptReference();
    if (!text) return;
    try {
      if (navigator.clipboard && window.isSecureContext) await navigator.clipboard.writeText(text);
      else {
        const field = document.createElement('textarea');
        field.value = text;
        field.readOnly = true; field.inputMode = 'none'; field.tabIndex = -1;
        field.style.position = 'fixed';field.style.opacity = '0';
        (modal.open ? modalContent : document.body).appendChild(field);
        field.select();
        const done = document.execCommand('copy');
        field.remove();
        if (!done) throw new Error('copy failed');
      }
      showToast('订单号已复制。');
    } catch { showToast('当前浏览器无法复制，请手动保存显示的订单号。',true); }
  }

  document.addEventListener('click', async event => {
    const button = event.target.closest('[data-action]');
    if (!button) return;
    const action = button.dataset.action;
    if (performance.now() < state.suppressClickUntil && button.closest('#gallery')) { event.preventDefault(); return; }
    if (state.busy && !['copy-order'].includes(action)) return;
    if (action === 'close') closeModal();
    else if (action === 'purchase') showCheckout();
    else if (action === 'restore') showRestore();
    else if (action === 'attach') showAttach();
    else if (action === 'support') showSupport();
    else if (action === 'pending') showPending();
    else if (action === 'copy-order') await copyOrder();
    else if (action === 'lightbox') showLightbox(button.dataset.imageId);
    else if (action === 'prev-image') stepImage(-1);
    else if (action === 'next-image') stepImage(1);
    else if (action === 'explore') { closeModal(); $('#gallery')?.scrollIntoView({behavior:'smooth'}); }
    else if (action === 'view-images') { const item = state.data?.collection.items[state.deckIndex]; if (item?.unlocked) showLightbox(item.id); }
    else if (action === 'prev-deck') goToDeck(state.deckIndex-1);
    else if (action === 'next-deck') goToDeck(state.deckIndex+1);
    else if (action === 'retry') { try { await loadCollection(); } catch(error) { showToast(error.message,true); } }
    else if (action === 'demo-pay') {
      const order = state.latestOrder;
      if (!order || state.data.site.mode !== 'demo' || order.mode !== 'demo') return;
      setBusy(true,button,'正在模拟付款…');
      try {
        await request('/api/demo/orders/' + encodeURIComponent(order.id) + '/pay',{method:'POST'});
        await loadCollection({quiet:true});
        setBusy(false,button);
        if (state.data.access.unlocked) showSuccess();
        else formMessage('付款记录已保存，请刷新页面查看解锁结果。');
      } catch(error) { setBusy(false,button); formMessage(error.message,true); }
    } else if (action === 'check-payment') {
      setBusy(true,button,'正在查询付款…');
      try { const paid = await refreshPayment(); setBusy(false,button); if (paid) showSuccess(); }
      catch(error) { setBusy(false,button); formMessage(error.message,true); }
    } else if (action === 'continue-payment') {
      try {
        const order = state.latestOrder;
        if (!order?.payment_url || order.mode !== 'live') return;
        const url = new URL(order.payment_url,location.origin);
        if (url.protocol !== 'https:') throw new Error('付款地址暂不可用，请联系微信客服。');
        location.assign(url.href);
      } catch(error) { formMessage(error.message,true); }
    } else if (action === 'redeem') {
      if (!state.recoveryToken) return;
      setBusy(true,button,'正在打开合集…');
      try {
        const result = await request('/api/access/redeem',{method:'POST',body:{token:state.recoveryToken}});
        state.recoveryToken = '';
        state.returnRecovery = false;
        state.slug = result.collection_slug || state.slug;
        history.replaceState(null,'','/c/' + encodeURIComponent(state.slug));
        await loadCollection({quiet:true});
        setBusy(false,button); closeModal(); showToast(result.message || '已恢复访问，可以查看图片了。');
      } catch(error) { setBusy(false,button); formMessage(error.message,true); }
    }
  });

  document.addEventListener('submit',async event => {
    const form = event.target.closest('form[data-form]');
    if (!form) return;
    event.preventDefault();
    if (state.busy || !form.reportValidity()) return;
    const values = new FormData(form);
    const button = $('button[type="submit"]',form);
    const email = String(values.get('email') || '').trim();
    const kind = form.dataset.form;
    setBusy(true,button,kind === 'checkout' ? '正在创建订单…' : state.data.site.mail_mode === 'file' ? '正在生成演示链接…' : '正在发送链接…');
    try {
      if (kind === 'checkout') {
        state.checkoutEmail = email;
        const body = {collection_id:state.data.collection.id,payment_method:String(values.get('payment_method') || 'wxpay')};
        if (email) body.email = email;
        const order = await request('/api/orders',{method:'POST',body});
        state.latestOrder = order;
        setBusy(false,button); render();
        if (order.mode === 'demo') showDemoCheckout(order);
        else {
          const url = new URL(order.payment_url,location.origin);
          if (url.protocol !== 'https:') throw new Error('付款地址暂不可用，请联系微信客服。');
          window.location.assign(url.href);
        }
      } else if (kind === 'restore') {
        const result = await request('/api/access/request',{method:'POST',body:{email}});
        setBusy(false,button);
        formMessage(state.data.site.mail_mode === 'file' ? '没有发送真实邮件。如果该邮箱关联了已验证的购买记录，演示找回链接会保存在本地邮件目录（默认 data/outbox/）。' : result.message || '如果该邮箱关联了已验证的购买记录，我们会发送找回链接。');
      } else if (kind === 'attach') {
        state.checkoutEmail = email;
        const result = await request('/api/email/attach',{method:'POST',body:{purchase_id:state.data.access.purchase_id,email}});
        setBusy(false,button);
        formMessage(state.data.site.mail_mode === 'file' ? '演示验证邮件已创建，没有发送真实邮件。请在本地邮件目录（默认 data/outbox/）中打开验证链接。' : result.message || '请查看邮箱，并打开验证链接完成设置。');
      }
    } catch(error) { setBusy(false,button); formMessage(error.message,true); }
  });
  document.addEventListener('keydown',event => {
    if (state.modal === 'lightbox') {
      if (event.key === 'ArrowLeft') { event.preventDefault(); stepImage(-1); }
      if (event.key === 'ArrowRight') { event.preventDefault(); stepImage(1); }
      return;
    }
    if (state.modal || !event.target.closest('#gallery') || event.target.tagName === 'INPUT') return;
    if (event.key === 'ArrowLeft') { event.preventDefault(); goToDeck(state.deckIndex-1); }
    if (event.key === 'ArrowRight') { event.preventDefault(); goToDeck(state.deckIndex+1); }
    if (event.key === 'Home') { event.preventDefault(); goToDeck(0); }
    if (event.key === 'End') { event.preventDefault(); goToDeck(state.data.collection.items.length-1); }
  });
  function resetDeckDrag() {
    const card = $('#deckCardHost .deck-card');
    if (!card) return;
    card.classList.remove('is-dragging');
    card.style.removeProperty('--drag-x');
    card.style.removeProperty('--drag-angle');
  }
  // One-finger horizontal gestures work on the deck and viewer. Vertical
  // scrolling and pinch zoom stay native; no event is prevented or captured.
  document.addEventListener('pointerdown', event => {
    if (event.pointerType !== 'touch') return;
    const mode = state.modal === 'lightbox' ? 'lightbox' : !state.modal && !state.returnRecovery ? 'deck' : null;
    if (!mode) return;
    state.touchPointers.add(event.pointerId);
    if (state.touchPointers.size !== 1 || !event.isPrimary) { state.swipe = null; resetDeckDrag(); return; }
    if (!event.target.closest(mode === 'lightbox' ? '.lightbox-stage' : '#deckStage')) return;
    const control = event.target.closest('button,a,input');
    if (control && !(mode === 'deck' && control.classList.contains('deck-image-button'))) return;
    if (window.visualViewport && window.visualViewport.scale > 1.01) return;
    state.swipe = {id:event.pointerId,x:event.clientX,y:event.clientY,time:performance.now(),mode};
  }, {passive:true});
  document.addEventListener('pointermove', event => {
    const swipe = state.swipe;
    if (!swipe || swipe.mode !== 'deck' || swipe.id !== event.pointerId) return;
    const dx = event.clientX-swipe.x, dy = event.clientY-swipe.y;
    if (Math.abs(dx) < 12 || Math.abs(dx) <= Math.abs(dy)*1.5) return;
    const card = $('#deckCardHost .deck-card');
    if (!card) return;
    card.classList.add('is-dragging');
    card.style.setProperty('--drag-x',Math.max(-65,Math.min(65,dx*.45)) + 'px');
    card.style.setProperty('--drag-angle',Math.max(-3,Math.min(3,dx*.018)) + 'deg');
  }, {passive:true});
  window.addEventListener('pointerup', event => {
    const swipe = state.swipe;
    const single = state.touchPointers.size === 1;
    state.touchPointers.delete(event.pointerId);
    state.swipe = null;
    resetDeckDrag();
    if (!swipe || swipe.id !== event.pointerId || !single) return;
    if (window.visualViewport && window.visualViewport.scale > 1.01) return;
    const dx = event.clientX-swipe.x, dy = event.clientY-swipe.y;
    if (Math.abs(dx) < 55 || Math.abs(dx) <= Math.abs(dy)*1.8 || Math.abs(dy) >= 55 || performance.now()-swipe.time >= 1200) return;
    if (swipe.mode === 'lightbox' && state.modal === 'lightbox') stepImage(dx < 0 ? 1 : -1);
    else if (swipe.mode === 'deck' && !state.modal) {
      state.suppressClickUntil = performance.now()+400;
      goToDeck(state.deckIndex+(dx < 0 ? 1 : -1));
    }
  }, {passive:true});
  window.addEventListener('pointercancel', event => {
    state.touchPointers.delete(event.pointerId);
    state.swipe = null;
    resetDeckDrag();
  }, {passive:true});
  document.addEventListener('invalid', event => {
    const input = event.target;
    if (input.tagName !== 'INPUT') return;
    if (input.validity.valueMissing) input.setCustomValidity(input.type === 'email' ? '请输入邮箱地址。' : '请填写此项。');
    else if (input.validity.typeMismatch && input.type === 'email') input.setCustomValidity('请输入有效的邮箱地址。');
  }, true);
  document.addEventListener('input', event => {
    if (event.target.id === 'deckPosition') { goToDeck(Number(event.target.value)); return; }
    if (event.target.tagName === 'INPUT') event.target.setCustomValidity('');
  });
  function updateVisualViewport() {
    const viewport = window.visualViewport;
    const height = viewport?.height || window.innerHeight;
    const top = viewport?.offsetTop || 0;
    document.documentElement.style.setProperty('--visual-height',height + 'px');
    document.documentElement.style.setProperty('--visual-top',top + 'px');
    document.documentElement.style.setProperty('--keyboard-offset',Math.max(0,window.innerHeight - height - top) + 'px');
  }
  updateVisualViewport();
  window.addEventListener('resize',updateVisualViewport,{passive:true});
  window.visualViewport?.addEventListener('resize',updateVisualViewport,{passive:true});
  window.visualViewport?.addEventListener('scroll',updateVisualViewport,{passive:true});
  document.addEventListener('focusin', event => {
    if (event.target.tagName !== 'INPUT' || !modal.open || !window.matchMedia('(max-width: 760px)').matches) return;
    const input = event.target;
    setTimeout(() => { if (document.activeElement === input) input.scrollIntoView({block:'center',behavior:'smooth'}); },250);
  });
  window.addEventListener('pageshow',event => {
    if (event.persisted && state.data) loadCollection({quiet:true}).catch(() => showToast('请刷新页面查看购买状态。',true));
  });

  async function init() {
    if (/^\/(recover|verify-email)\/?$/.test(location.pathname)) {
      state.recoveryToken = new URLSearchParams(location.hash.slice(1)).get('token') || '';
      state.recoveryPurpose = location.pathname.startsWith('/verify-email') ? 'verify' : 'restore';
      history.replaceState(null,'',location.pathname);
    }
    try {
      await loadCollection();
      if (state.returnRecovery) return;
      if (state.recoveryPurpose) showRedeem();
      else if (location.pathname.startsWith('/checkout/demo/')) {
        const id = routeOrderId();
        if (!id) throw new Error('付款链接不完整，请打开合集后继续。');
        const order = await request('/api/orders/' + encodeURIComponent(id));
        state.latestOrder = order;
        if (order.status === 'paid') showSuccess();
        else showDemoCheckout(order);
      } else if (location.pathname === '/payment/return') {
        history.replaceState(null,'','/c/' + encodeURIComponent(state.slug));
        if (pendingOrder()) { showPending(); await pollPayment(); }
        else if (state.data.access.unlocked) showSuccess();
      }
    } catch(error) {
      $('#loadingState').hidden = true;
      if (state.data) { showToast(error.message,true); return; }
      $('#app').setAttribute('aria-busy','false');
      $('#app').innerHTML = `<section class="fatal-error"><p class="eyebrow">稍等一下</p><h1>暂时无法打开合集。</h1><p>${esc(error.message)}</p><p class="field-help">暂时无法读取客服信息。请稍后刷新，或回到原付款浏览器查看订单。</p><button class="primary-button" data-action="retry" type="button">重试 ${icons.arrow}</button></section>`;
    }
  }
  init();
})();
