/* =========================================================
   Korpus app — micro-interactions + tour step definitions.
   Vanilla JS, no deps. Loaded before korpus-tour.js on every
   page (see base.html).
   ========================================================= */
(function () {
  'use strict';

  /* ---------- tour step definitions, keyed by data-tour-page ---------- */
  window.KORPUS_TOUR_STEPS = {
    'batch-list': [
      {
        target: '[data-tour="upload-btn"]',
        title: 'Nova serija',
        text: 'Ovde otpremate katalog. Svaki red fajla postaje jedan proizvod.'
      },
      {
        target: '[data-tour="demo-btn"]',
        title: 'Probajte bez fajla',
        text: 'Učitava demo seriju sa gotovim opisima — najbrži način da vidite kako sve radi.'
      },
      {
        target: '[data-tour="batch-table"]',
        title: 'Vaše serije',
        text: 'Svaka serija je jedno otpremanje kataloga. Kliknite da vidite opise i statuse.'
      }
    ],
    'batch-detail': [
      {
        target: '[data-tour="counts"]',
        title: 'Pregled statusa',
        text: 'Koliko opisa čeka, koliko je odobreno, odbijeno i objavljeno.'
      },
      {
        target: '[data-tour="filters"]',
        title: 'Filteri',
        text: 'Suzite tabelu po statusu. ‘Za pregled’ izdvaja stavke koje traže pažnju.'
      },
      {
        target: '[data-tour="items"]',
        title: 'Stavke',
        text: 'Svaki proizvod ima svoj opis na oba pisma. Kliknite ‘Pregledaj’ za odluku.'
      },
      {
        target: '[data-tour="artifacts"]',
        title: 'Preuzimanja',
        text: 'CSV sa svim opisima i JSON izveštaj o poreklu tvrdnji.'
      },
      {
        target: '[data-tour="publish"]',
        title: 'Objava',
        text: 'Kada odobrite stavke, odavde ih šaljete u prodavnicu.'
      }
    ],
    'review-item': [
      {
        target: '[data-tour="panels"]',
        title: 'Oba pisma odjednom',
        text: 'Ćirilica i latinica iz jedne generacije — uvek usklađene.'
      },
      {
        target: '[data-tour="provenance"]',
        title: 'Poreklo svake tvrdnje',
        text: 'Zelene rečenice imaju izvor u atributima. Narandžaste NEMAJU izvor — proverite ih pre odobravanja.'
      },
      {
        target: '[data-tour="attributes"]',
        title: 'Ulazni atributi',
        text: 'Jedini izvor podataka za opis. Ništa van ovoga ne sme da se tvrdi.'
      },
      {
        target: '[data-tour="action-bar"]',
        title: 'Vaša odluka',
        text: 'Odobrite ili odbijte uz razlog. Ništa se ne objavljuje bez odobrenja.'
      }
    ]
  };

  /* ---------- toast auto-dismiss ---------- */
  function bindToasts() {
    var toasts = Array.prototype.slice.call(document.querySelectorAll('.toast'));
    toasts.forEach(function (toast) {
      var timer = setTimeout(remove, 6000);
      function remove() {
        clearTimeout(timer);
        if (!toast.parentNode) return;
        toast.parentNode.removeChild(toast);
      }
      toast.addEventListener('click', remove);
    });
  }

  /* ---------- count-up animation for counts-strip numbers ---------- */
  function prefersReducedMotion() {
    return window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  }

  function countUp(el) {
    var raw = el.textContent.trim();
    if (!/^\d+$/.test(raw)) return;
    var target = parseInt(raw, 10);
    if (prefersReducedMotion()) { el.textContent = String(target); return; }
    var dur = 900, t0 = performance.now();
    function tick(t) {
      var p = Math.min(1, (t - t0) / dur);
      var ease = 1 - Math.pow(1 - p, 3);
      el.textContent = String(Math.round(target * ease));
      if (p < 1) requestAnimationFrame(tick);
      else el.textContent = String(target);
    }
    requestAnimationFrame(tick);
  }

  function bindCountUp() {
    Array.prototype.slice.call(document.querySelectorAll('.counts-strip-num')).forEach(countUp);
  }

  document.addEventListener('DOMContentLoaded', function () {
    bindToasts();
    bindCountUp();
  });
})();
