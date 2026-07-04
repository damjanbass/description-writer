/* =========================================================
   Korpus first-run guided tour.
   Vanilla JS, no deps. Reads step data from
   window.KORPUS_TOUR_STEPS[document.body.dataset.tourPage]
   (defined in korpus-app.js, loaded before this file).
   Exposes window.KorpusTour = { start, restart }.
   ========================================================= */
(function () {
  'use strict';

  /* localStorage can throw (private mode, disabled storage) — never fatal. */
  function storeGet(key) {
    try { return window.localStorage.getItem(key); } catch (err) { return null; }
  }
  function storeSet(key, value) {
    try { window.localStorage.setItem(key, value); } catch (err) { /* non-fatal */ }
  }
  function storeRemove(key) {
    try { window.localStorage.removeItem(key); } catch (err) { /* non-fatal */ }
  }

  function prefersReducedMotion() {
    return window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  }

  var state = null; /* { page, steps, index, overlay, ring, card } */

  function storageKey(page) { return 'korpus-tour:' + page; }

  function getStepsForPage(page) {
    var all = window.KORPUS_TOUR_STEPS || {};
    var steps = all[page];
    if (!steps || !steps.length) return [];
    return steps.filter(function (step) {
      return !!document.querySelector(step.target);
    });
  }

  function buildDom() {
    var overlay = document.createElement('div');
    overlay.className = 'korpus-tour-overlay';

    var ring = document.createElement('div');
    ring.className = 'korpus-tour-ring';
    overlay.appendChild(ring);

    var card = document.createElement('div');
    card.className = 'korpus-tour-card';
    card.setAttribute('role', 'dialog');
    card.setAttribute('aria-modal', 'true');
    card.innerHTML =
      '<div class="korpus-tour-step mono"></div>' +
      '<div class="korpus-tour-title"></div>' +
      '<div class="korpus-tour-text"></div>' +
      '<div class="korpus-tour-actions">' +
        '<button type="button" class="btn btn-ghost" data-tour-skip>Preskoči</button>' +
        '<div class="korpus-tour-actions-right">' +
          '<button type="button" class="btn btn-ghost" data-tour-back>Nazad</button>' +
          '<button type="button" class="btn btn-primary" data-tour-next>Dalje</button>' +
        '</div>' +
      '</div>';
    overlay.appendChild(card);

    document.body.appendChild(overlay);
    return { overlay: overlay, ring: ring, card: card };
  }

  function teardownDom() {
    if (!state) return;
    if (state.overlay && state.overlay.parentNode) {
      state.overlay.parentNode.removeChild(state.overlay);
    }
    document.removeEventListener('keydown', onKeydown);
    window.removeEventListener('resize', onResize);
  }

  function positionFor(step) {
    var target = document.querySelector(step.target);
    if (!target) return null;
    target.scrollIntoView({
      block: 'center',
      behavior: prefersReducedMotion() ? 'auto' : 'smooth'
    });
    return target;
  }

  function render() {
    if (!state) return;
    var step = state.steps[state.index];
    var target = document.querySelector(step.target);
    if (!target) { next(); return; }

    var rect = target.getBoundingClientRect();
    var pad = 8;
    state.ring.style.top = (rect.top - pad) + 'px';
    state.ring.style.left = (rect.left - pad) + 'px';
    state.ring.style.width = (rect.width + pad * 2) + 'px';
    state.ring.style.height = (rect.height + pad * 2) + 'px';

    var card = state.card;
    card.querySelector('.korpus-tour-step').textContent =
      (state.index + 1) + ' / ' + state.steps.length;
    card.querySelector('.korpus-tour-title').textContent = step.title;
    card.querySelector('.korpus-tour-text').textContent = step.text;

    var backBtn = card.querySelector('[data-tour-back]');
    backBtn.style.display = state.index === 0 ? 'none' : '';

    var nextBtn = card.querySelector('[data-tour-next]');
    nextBtn.textContent = state.index === state.steps.length - 1 ? 'Završi' : 'Dalje';

    positionCard(rect);
  }

  function positionCard(targetRect) {
    var card = state.card;
    /* Mobile: bottom-sheet, positioning handled entirely by CSS. */
    if (window.innerWidth < 480) {
      card.style.top = '';
      card.style.left = '';
      return;
    }

    var margin = 16;
    var cardRect = card.getBoundingClientRect();
    var cardWidth = cardRect.width || 340;
    var cardHeight = cardRect.height || 160;

    var top = targetRect.bottom + margin;
    if (top + cardHeight > window.innerHeight) {
      top = targetRect.top - cardHeight - margin;
      if (top < margin) top = Math.max(margin, window.innerHeight - cardHeight - margin);
    }

    var left = targetRect.left;
    if (left + cardWidth > window.innerWidth - margin) {
      left = window.innerWidth - cardWidth - margin;
    }
    if (left < margin) left = margin;

    card.style.top = top + 'px';
    card.style.left = left + 'px';
  }

  function next() {
    if (!state) return;
    if (state.index >= state.steps.length - 1) {
      finish();
      return;
    }
    state.index += 1;
    positionFor(state.steps[state.index]);
    render();
  }

  function back() {
    if (!state || state.index === 0) return;
    state.index -= 1;
    positionFor(state.steps[state.index]);
    render();
  }

  function finish() {
    if (!state) return;
    storeSet(storageKey(state.page), 'done');
    teardownDom();
    state = null;
  }

  function skip() {
    if (!state) return;
    storeSet(storageKey(state.page), 'done');
    teardownDom();
    state = null;
  }

  function onKeydown(e) {
    if (e.key === 'Escape') { skip(); return; }
    if (e.key === 'ArrowRight') { next(); return; }
    if (e.key === 'ArrowLeft') { back(); return; }
  }

  function onResize() {
    if (!state) return;
    render();
  }

  function start(page) {
    page = page || document.body.dataset.tourPage;
    if (!page) return;
    var steps = getStepsForPage(page);
    if (!steps.length) return;

    if (state) teardownDom();

    var dom = buildDom();
    state = {
      page: page,
      steps: steps,
      index: 0,
      overlay: dom.overlay,
      ring: dom.ring,
      card: dom.card
    };

    dom.card.querySelector('[data-tour-skip]').addEventListener('click', skip);
    dom.card.querySelector('[data-tour-back]').addEventListener('click', back);
    dom.card.querySelector('[data-tour-next]').addEventListener('click', next);

    document.addEventListener('keydown', onKeydown);
    window.addEventListener('resize', onResize);

    positionFor(steps[0]);
    render();
  }

  function restart() {
    var page = document.body.dataset.tourPage;
    if (!page) return;
    storeRemove(storageKey(page));
    start(page);
  }

  function maybeAutoStart() {
    var page = document.body.dataset.tourPage;
    if (!page) return;
    var steps = getStepsForPage(page);
    if (!steps.length) return;
    if (storeGet(storageKey(page)) === 'done') return;
    start(page);
  }

  document.addEventListener('DOMContentLoaded', maybeAutoStart);

  window.KorpusTour = { start: start, restart: restart };
})();
