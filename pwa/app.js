/* The Wire — PWA du radar. Vanilla JS, zéro build, zéro dépendance externe.
   Lit data/radar.json (réel) puis data/radar.demo.json (repli) — ordre dans pwa/config.js.
   Rendu conforme à DESIGN-SPEC.md + pwa/design-system.css :
   headline serif → move ★ déplié → moves repliés (tap pour ouvrir) → skill → stats/footer.
   États : squelettes au chargement, jour calme élégant, erreur factuelle,
   bandeau hors-ligne (dernière version gardée en localStorage), badge démo. */
(function () {
  "use strict";

  var DEMO_SOURCE = "data/radar.demo.json";
  var CACHE_KEY = "twRadarCache";   // dernière version reçue → repli hors-ligne
  var DONE_PREFIX = "twDone:";      // étapes cochées, une clé par date de radar
  var RAMPS = { blue: 1, teal: 1, purple: 1, coral: 1, amber: 1, gray: 1 };

  /* ---------- utilitaires ---------- */

  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;")
      .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }

  /* localStorage peut être indisponible (navigation privée) : tout est gardé. */
  function lsGet(key) {
    try { return window.localStorage.getItem(key); } catch (e) { return null; }
  }
  function lsSet(key, val) {
    try { window.localStorage.setItem(key, val); } catch (e) {}
  }

  function announce(msg) {
    var live = document.getElementById("live");
    if (live) { live.textContent = ""; live.textContent = msg; }
  }

  /* ---------- chargement ---------- */

  function loadRadar() {
    var sources = (window.VEILLE_SOURCES || [DEMO_SOURCE]).slice();
    function tryNext() {
      if (!sources.length) return Promise.reject(new Error("no source"));
      var url = sources.shift();
      return fetch(url, { cache: "no-store" })
        .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
        .then(function (j) { j.__source = url; return j; })
        .catch(function () { return tryNext(); });
    }
    return tryNext();
  }

  /* ---------- étapes cochées (persistance par date de radar) ---------- */

  function doneKey(data) { return DONE_PREFIX + (data.date || "sans-date"); }

  function loadDone(data) {
    var raw = lsGet(doneKey(data));
    if (!raw) return {};
    try {
      var o = JSON.parse(raw);
      return (o && typeof o === "object") ? o : {};
    } catch (e) { return {}; }
  }

  function saveDone(data, done) { lsSet(doneKey(data), JSON.stringify(done)); }

  /* Un radar par jour : on jette les clés de coche des jours précédents. */
  function pruneDone(data) {
    try {
      var keep = doneKey(data), kill = [], i, k;
      for (i = 0; i < window.localStorage.length; i++) {
        k = window.localStorage.key(i);
        if (k && k.indexOf(DONE_PREFIX) === 0 && k !== keep) kill.push(k);
      }
      kill.forEach(function (key) { window.localStorage.removeItem(key); });
    } catch (e) {}
  }

  /* ---------- copie en un tap ---------- */

  function copyLegacy(txt) {
    try {
      var ta = document.createElement("textarea");
      ta.value = txt;
      ta.setAttribute("readonly", "");
      ta.style.position = "fixed";
      ta.style.top = "-1000px";
      document.body.appendChild(ta);
      ta.select();
      document.execCommand("copy");
      document.body.removeChild(ta);
    } catch (e) {}
  }

  function copyText(txt) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      return navigator.clipboard.writeText(txt).catch(function () { copyLegacy(txt); });
    }
    copyLegacy(txt);
    return Promise.resolve();
  }

  /* ---------- rendu ---------- */

  function renderStep(s, idx, isLast, isDone) {
    var html = '<div class="tw-step' + (isDone ? " is-done" : "") + '" data-step="' + idx + '">';
    html += '<div class="tw-step__rail">';
    html += '<button type="button" class="tw-step__num" aria-pressed="' + (isDone ? "true" : "false") +
            '" aria-label="Étape ' + (idx + 1) + ' — marquer comme faite">' +
            (isDone ? "✓" : (idx + 1)) + '</button>';
    if (!isLast) html += '<div class="tw-step__line"></div>';
    html += '</div><div class="tw-step__body">';
    if (s.t) html += '<div class="tw-step__t">' + esc(s.t) + '</div>';
    if (s.how) html += '<div class="tw-step__how">' + esc(s.how) + '</div>';
    if (s.paste) {
      html += '<button type="button" class="tw-paste" data-copy="' + esc(s.paste) +
              '" aria-label="Copier ce texte">' + esc(s.paste) +
              '<span class="tw-paste__hint" aria-hidden="true"></span></button>';
    }
    if (s.done) html += '<div class="tw-step__done">' + esc(s.done) + '</div>';
    html += '</div></div>';
    return html;
  }

  function renderMove(m, idx, doneList) {
    var isStar = m.rank === "star";
    var ramp = RAMPS[m.ramp] ? m.ramp : "gray";
    var steps = m.steps || [];
    var bodyId = "tw-body-" + idx;

    var top = "";
    if (isStar) {
      top += '<span class="tw-badge-star">move du jour</span>';
    } else if (m.rank != null && m.rank !== "") {
      top += '<span class="tw-rank" aria-hidden="true">#' + esc(m.rank) + '</span>';
    }
    if (m.projet) top += '<span class="tw-chip">' + esc(m.projet) + '</span>';
    if (m.meta) top += '<span class="tw-meta">' + esc(m.meta) + '</span>';
    if (!isStar) top += '<span class="tw-move__chev" aria-hidden="true"></span>';

    /* Star : toujours dépliée, head non interactif.
       Autres : head = bouton accessible qui déplie/replie. */
    var headAttrs = isStar
      ? ' class="tw-move__head tw-move__head--static"'
      : ' class="tw-move__head" role="button" tabindex="0" aria-expanded="false" aria-controls="' + bodyId + '"';
    var head = '<div' + headAttrs + '>' +
      '<div class="tw-move__top">' + top + '</div>' +
      '<h2 class="tw-move__title">' + esc(m.title) + '</h2>' +
    '</div>';

    var body = "";
    if (m.pourquoi_maintenant) body += '<p class="tw-why">' + esc(m.pourquoi_maintenant) + '</p>';
    /* Insight : la lecture stratégique (ce que le fait implique) — champ optionnel,
       exigé pour le move star par le prompt d'analyse. Tronqué à 160 (spec 2B). */
    if (m.insight) body += '<p class="tw-insight">' + esc(String(m.insight).slice(0, 160)) + '</p>';
    if (m.do_now) {
      body += '<div class="tw-donow"><span class="tw-donow__label">do now</span>' +
              '<div>' + esc(m.do_now) + '</div></div>';
    }
    if (steps.length) {
      body += '<div class="tw-progress" style="--done:' + doneList.length + ';--total:' + steps.length +
              '" role="progressbar" aria-valuemin="0" aria-valuemax="' + steps.length +
              '" aria-valuenow="' + doneList.length + '" aria-label="Étapes faites">' +
              '<div class="tw-progress__fill"></div></div>';
      body += '<div class="tw-steps">' + steps.map(function (s, i) {
        return renderStep(s, i, i === steps.length - 1, doneList.indexOf(i) !== -1);
      }).join("") + '</div>';
    }
    if (m.ensuite) body += '<div class="tw-ensuite"><b>Ensuite</b>' + esc(m.ensuite) + '</div>';
    if (m.aussi_pour) body += '<div class="tw-aussi"><b>Aussi pour</b>' + esc(m.aussi_pour) + '</div>';

    return '<article class="tw-move' + (isStar ? " tw-move--star" : "") +
      '" data-ramp="' + esc(ramp) + '" data-move="' + idx + '" style="--i:' + idx + '">' +
      head +
      '<div class="tw-fold"><div class="tw-move__body" id="' + bodyId + '">' + body + '</div></div>' +
    '</article>';
  }

  /* ---------- interactions ---------- */

  function wireInteractions(container, data) {
    /* Dépliage des moves 2..n (tap ou Entrée/Espace) */
    container.querySelectorAll('.tw-move__head[role="button"]').forEach(function (head) {
      var card = head.closest(".tw-move");
      if (!card) return;
      function toggle() {
        var open = card.classList.toggle("is-open");
        head.setAttribute("aria-expanded", open ? "true" : "false");
      }
      head.addEventListener("click", toggle);
      head.addEventListener("keydown", function (e) {
        if (e.key === "Enter" || e.key === " " || e.key === "Spacebar") {
          e.preventDefault();
          toggle();
        }
      });
    });

    /* Copie en un tap, feedback "✓ copié" 1.2s (design-system .is-copied) */
    container.querySelectorAll(".tw-paste").forEach(function (btn) {
      var timer = null;
      btn.addEventListener("click", function () {
        copyText(btn.getAttribute("data-copy") || "").then(function () {
          btn.classList.add("is-copied");
          announce("Copié dans le presse-papiers");
          if (timer) clearTimeout(timer);
          timer = setTimeout(function () { btn.classList.remove("is-copied"); }, 1200);
        });
      });
    });

    /* Étapes cochables → barre de progression du move */
    container.querySelectorAll(".tw-step__num").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var step = btn.closest(".tw-step");
        var card = btn.closest(".tw-move");
        if (!step || !card) return;
        var mIdx = card.getAttribute("data-move");
        var sIdx = parseInt(step.getAttribute("data-step"), 10);
        var done = loadDone(data);
        var list = done[mIdx] || [];
        var pos = list.indexOf(sIdx);
        var nowDone = pos === -1;
        if (nowDone) list.push(sIdx); else list.splice(pos, 1);
        done[mIdx] = list;
        saveDone(data, done);
        step.classList.toggle("is-done", nowDone);
        btn.setAttribute("aria-pressed", nowDone ? "true" : "false");
        btn.textContent = nowDone ? "✓" : String(sIdx + 1);
        var bar = card.querySelector(".tw-progress");
        if (bar) {
          bar.style.setProperty("--done", String(list.length));
          bar.setAttribute("aria-valuenow", String(list.length));
        }
      });
    });
  }

  /* ---------- écran ---------- */

  function hideSkeletons() {
    var skel = document.getElementById("headline-skeleton");
    if (skel) skel.hidden = true;
    var main = document.getElementById("moves");
    if (main) main.setAttribute("aria-busy", "false");
  }

  function render(data, opts) {
    opts = opts || {};
    var isDemo = !!(data.stats && data.stats.demo) || data.__source === DEMO_SOURCE;

    hideSkeletons();
    document.getElementById("date").textContent = data.date || "";

    var headline = document.getElementById("headline");
    headline.hidden = !data.headline;
    headline.textContent = data.headline || "";

    var st = data.stats || {};
    var bits = [];
    if (st.fresh != null) bits.push("<span><b>" + esc(st.fresh) + "</b> fresh</span>");
    if (st.cut != null) bits.push("<span><b>" + esc(st.cut) + "</b> coupés</span>");
    if (isDemo) bits.push('<span class="tw-badge-demo">données démo</span>');
    var statsEl = document.getElementById("stats");
    statsEl.hidden = !bits.length;
    statsEl.innerHTML = bits.join("");

    /* Bandeau discret quand le réseau a échoué et qu'on sert la version gardée */
    document.getElementById("banner-zone").innerHTML = opts.fromCache
      ? '<div class="tw-banner" role="status">Hors ligne — dernière version reçue' +
        (data.date ? " (" + esc(data.date) + ")" : "") + ".</div>"
      : "";

    var main = document.getElementById("moves");
    var moves = data.moves || [];
    if (!moves.length) {
      /* Jour calme : un état élégant, pas un écran cassé */
      main.innerHTML =
        '<div class="tw-empty">' +
          '<div class="tw-empty__rings" aria-hidden="true"></div>' +
          '<p class="tw-empty__t">Rien d’urgent aujourd’hui.</p>' +
          '<p class="tw-empty__p">Un jour calme, c’est du temps pour shipper.</p>' +
        '</div>';
    } else {
      var done = loadDone(data);
      main.innerHTML = '<div class="tw-moves">' + moves.map(function (m, i) {
        return renderMove(m, i, done[String(i)] || []);
      }).join("") + '</div>';
      wireInteractions(main, data);
      /* La démo ne doit JAMAIS purger les étapes cochées du vrai radar du jour
         (sa date diffère → pruneDone effacerait les clés du jour réel). */
      if (!isDemo) pruneDone(data);
    }

    var skill = document.getElementById("skill");
    if (data.skill_up) {
      skill.hidden = false;
      skill.style.setProperty("--i", String(moves.length));
      document.getElementById("skill-text").textContent = data.skill_up;
    } else {
      skill.hidden = true;
    }

    document.getElementById("foot").textContent = isDemo
      ? "Généré par The Wire · données démo en attendant le premier vrai radar"
      : "Généré par The Wire · chaque matin à 10h";
  }

  function fail() {
    /* Réseau muet : on ressert la dernière version gardée, avec bandeau. */
    var cached = lsGet(CACHE_KEY);
    if (cached) {
      try {
        render(JSON.parse(cached), { fromCache: true });
        return;
      } catch (e) {}
    }
    hideSkeletons();
    document.getElementById("moves").innerHTML =
      '<div class="tw-error">' +
        '<p class="tw-error__t">Radar injoignable</p>' +
        '<p class="tw-error__p">Il se génère chaque matin à 10h. Réessaie dans un moment.</p>' +
      '</div>';
  }

  loadRadar()
    .then(function (data) {
      /* On ne garde en repli hors-ligne QUE le vrai radar : si le réseau a servi
         la démo (radar.json absent), écraser la dernière vraie version reçue
         ferait perdre le repli utile au prochain passage hors-ligne. */
      var isDemo = !!(data.stats && data.stats.demo) || data.__source === DEMO_SOURCE;
      if (!isDemo) lsSet(CACHE_KEY, JSON.stringify(data));
      render(data, { fromCache: false });
    })
    .catch(fail);
})();
