(function () {
  'use strict';

  /* Reveal-on-scroll styles are gated on this class so content stays
     visible when JavaScript is unavailable. */
  document.documentElement.classList.add('js');

  /* ---------- transliteration (latinica -> ćirilica) ---------- */
  var SINGLE = { a:'а', b:'б', v:'в', g:'г', d:'д', đ:'ђ', e:'е', ž:'ж', z:'з', i:'и', j:'ј', k:'к', l:'л', m:'м', n:'н', o:'о', p:'п', r:'р', s:'с', t:'т', ć:'ћ', u:'у', f:'ф', h:'х', c:'ц', č:'ч', š:'ш' };
  var DIGRAPH = { 'dž':'џ', 'lj':'љ', 'nj':'њ' };

  function isUpper(ch) { return ch !== ch.toLowerCase() && ch === ch.toUpperCase(); }

  function toCyr(str) {
    var out = '';
    for (var i = 0; i < str.length;) {
      var ch = str[i], nx = str[i + 1] || '';
      var pair = (ch + nx).toLowerCase();
      if (DIGRAPH[pair]) {
        var c2 = DIGRAPH[pair];
        if (isUpper(ch)) c2 = c2.toUpperCase();
        out += c2; i += 2; continue;
      }
      var lo = ch.toLowerCase();
      if (SINGLE[lo] !== undefined) {
        var c1 = SINGLE[lo];
        if (isUpper(ch)) c1 = c1.toUpperCase();
        out += c1; i += 1; continue;
      }
      out += ch; i += 1;
    }
    return out;
  }

  /* localStorage can throw (file://, private mode); never let it kill the page. */
  function storeGet(key) {
    try { return window.localStorage.getItem(key); } catch (err) { return null; }
  }
  function storeSet(key, value) {
    try { window.localStorage.setItem(key, value); } catch (err) { /* non-fatal */ }
  }

  var script = storeGet('korpus-script') || 'lat';
  function conv(lat) { return script === 'cyr' ? toCyr(lat) : lat; }

  /* ---------- cache convertible text nodes ---------- */
  var nodes = [];
  function cacheNodes() {
    nodes = [];
    var root = document.body;
    function skip(node) {
      var el = node.parentElement;
      while (el && el !== root) {
        if (el.hasAttribute && el.hasAttribute('data-fixed')) return true;
        var t = el.tagName;
        if (t === 'SCRIPT' || t === 'STYLE' || t === 'NOSCRIPT') return true;
        el = el.parentElement;
      }
      return false;
    }
    var walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
      acceptNode: function (n) {
        return (n.nodeValue && n.nodeValue.trim() && !skip(n)) ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_REJECT;
      }
    });
    var n;
    while ((n = walker.nextNode())) nodes.push({ node: n, lat: n.nodeValue });
  }
  function applyStatic() { nodes.forEach(function (o) { o.node.nodeValue = conv(o.lat); }); }

  /* ---------- script toggle ---------- */
  function bindScriptToggle() {
    var btns = Array.prototype.slice.call(document.querySelectorAll('[data-script-toggle] [data-script]'));
    if (!btns.length) return;
    function sync() {
      btns.forEach(function (b) { b.classList.toggle('is-active', b.dataset.script === script); });
    }
    btns.forEach(function (b) {
      b.addEventListener('click', function () {
        script = b.dataset.script;
        storeSet('korpus-script', script);
        applyStatic();
        refreshDemos();
        sync();
      });
    });
    sync();
  }

  /* ---------- smooth nav ---------- */
  function bindNav() {
    Array.prototype.slice.call(document.querySelectorAll('[data-nav]')).forEach(function (a) {
      var href = a.getAttribute('href');
      if (!href || href[0] !== '#') return;
      a.addEventListener('click', function (e) {
        var id = href.slice(1);
        var t = id === 'top' ? document.getElementById('top') : document.getElementById(id);
        if (!t) return;
        e.preventDefault();
        var top = t.getBoundingClientRect().top + window.scrollY - 70;
        window.scrollTo({ top: top, behavior: 'smooth' });
      });
    });
  }

  /* ---------- agreement demo (SLAGANJE RODA) ---------- */
  var renderAgree = null;
  function bindAgreement() {
    var btns = Array.prototype.slice.call(document.querySelectorAll('[data-agree-btns] button'));
    if (!btns.length) return;
    var artEl = document.querySelector('[data-agree-art]'), nounEl = document.querySelector('[data-agree-noun]');
    if (!artEl || !nounEl) return;
    var state = { art: 'crna', noun: 'majica' };
    renderAgree = function () { artEl.textContent = conv(state.art); nounEl.textContent = conv(state.noun); };
    btns.forEach(function (b) {
      b.addEventListener('click', function () {
        state = { art: b.dataset.art, noun: b.dataset.noun };
        btns.forEach(function (x) { x.classList.toggle('is-active', x === b); });
        renderAgree();
      });
    });
    renderAgree();
  }

  /* ---------- number-agreement demo (OBLIK BROJA) ---------- */
  var renderNum = null;
  function numWord(n) { return n === 1 ? 'proizvod' : 'proizvoda'; }
  function bindNumber() {
    var sl = document.querySelector('[data-num-slider]');
    if (!sl) return;
    var v = document.querySelector('[data-num-val]'), w = document.querySelector('[data-num-word]');
    if (!v || !w) return;
    var num = 1;
    renderNum = function () { v.textContent = String(num); w.textContent = conv(numWord(num)); };
    sl.addEventListener('input', function () { num = parseInt(sl.value, 10); renderNum(); });
    renderNum();
  }

  function refreshDemos() { if (renderAgree) renderAgree(); if (renderNum) renderNum(); }

  /* ---------- provenance hover (poreklo tvrdnje) ---------- */
  function bindProvenance() {
    Array.prototype.slice.call(document.querySelectorAll('[data-claim]')).forEach(function (c) {
      var id = c.dataset.claim, attr = document.querySelector('[data-attr="' + id + '"]');
      function on() { c.classList.add('is-active'); if (attr) attr.classList.add('is-active'); }
      function off() { c.classList.remove('is-active'); if (attr) attr.classList.remove('is-active'); }
      c.addEventListener('mouseenter', on); c.addEventListener('mouseleave', off);
      c.addEventListener('focus', on); c.addEventListener('blur', off);
      c.setAttribute('tabindex', '0');
      if (attr) { attr.addEventListener('mouseenter', on); attr.addEventListener('mouseleave', off); }
    });
  }

  /* ---------- header scroll state ---------- */
  function headerScroll() {
    var h = document.querySelector('[data-header]');
    if (!h) return;
    function upd() { h.classList.toggle('is-scrolled', window.scrollY > 20); }
    window.addEventListener('scroll', upd, { passive: true });
    upd();
  }

  /* ---------- reveal on scroll + counters + pipeline ---------- */
  function countUp(el) {
    var target = parseFloat(el.dataset.count || '0'), suf = el.dataset.suffix || '';
    var dur = 1100, t0 = performance.now();
    function tick(t) {
      var p = Math.min(1, (t - t0) / dur);
      var ease = 1 - Math.pow(1 - p, 3);
      el.textContent = Math.round(target * ease) + suf;
      if (p < 1) requestAnimationFrame(tick);
    }
    requestAnimationFrame(tick);
  }

  function revealObserver() {
    var reveals = Array.prototype.slice.call(document.querySelectorAll('[data-reveal]'));
    if (!('IntersectionObserver' in window)) {
      reveals.forEach(function (el) { el.classList.add('is-visible'); });
      var pipeEl = document.querySelector('[data-pipeline]');
      if (pipeEl) pipeEl.classList.add('is-visible');
      return;
    }
    var io = new IntersectionObserver(function (ents) {
      ents.forEach(function (e) {
        if (e.isIntersecting) { e.target.classList.add('is-visible'); io.unobserve(e.target); }
      });
    }, { threshold: .14 });
    reveals.forEach(function (el) { io.observe(el); });

    Array.prototype.slice.call(document.querySelectorAll('[data-count]')).forEach(function (el) {
      var co = new IntersectionObserver(function (ents) {
        ents.forEach(function (e) { if (e.isIntersecting) { countUp(el); co.unobserve(e.target); } });
      }, { threshold: .6 });
      co.observe(el);
    });

    var pipe = document.querySelector('[data-pipeline]');
    if (pipe) {
      var po = new IntersectionObserver(function (ents) {
        ents.forEach(function (e) {
          if (e.isIntersecting) { pipe.classList.add('is-visible'); po.unobserve(e.target); }
        });
      }, { threshold: .3 });
      po.observe(pipe);
    }
  }

  /* ---------- lead form ---------- */
  function bindLeadForm() {
    var form = document.getElementById('lead-form');
    if (!form) return;
    var statusEl = form.querySelector('[data-form-status]');
    var successEl = document.querySelector('[data-form-success]');

    form.addEventListener('submit', function (e) {
      e.preventDefault();
      var data = new FormData(form);

      if (data.get('website')) { // honeypot tripped — pretend success, do nothing
        form.hidden = true;
        if (successEl) successEl.hidden = false;
        return;
      }

      var payload = {
        ime: data.get('ime'),
        email: data.get('email'),
        firma: data.get('firma'),
        poruka: data.get('poruka')
      };

      statusEl.textContent = 'Šaljemo...';
      statusEl.className = 'form-status';

      fetch('/api/lead', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      }).then(function (res) {
        if (!res.ok) throw new Error('bad status');
        form.hidden = true;
        if (successEl) successEl.hidden = false;
      }).catch(function () {
        statusEl.textContent = 'Nešto nije uspelo. Pišite nam direktno na pilot@korpus.rs.';
        statusEl.className = 'form-status is-error';
      });
    });
  }

  /* ---------- init ---------- */
  document.addEventListener('DOMContentLoaded', function () {
    cacheNodes();
    if (script === 'cyr') applyStatic();
    bindScriptToggle();
    bindNav();
    bindAgreement();
    bindNumber();
    bindProvenance();
    headerScroll();
    revealObserver();
    bindLeadForm();
  });
})();
