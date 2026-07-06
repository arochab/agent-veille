/* The Wire - PWA du radar. Vanilla JS, zéro build, zéro dépendance externe.
   Lit data/radar.json (réel) puis data/radar.demo.json (repli) - ordre dans pwa/config.js.
   Rendu conforme à DESIGN-SPEC.md + pwa/design-system.css (« LE CALIBRE ») :
   readout → verdict/headline → move ★ déplié (stamp, verdict €, do now, GO,
   insight LCD, plan d'exécution) → moves repliés (registre 01/02/03) →
   tes go en cours (pipeline local) → skill → footer.
   États : squelettes au chargement, jour calme élégant, erreur factuelle,
   bandeau hors-ligne (dernière version gardée en localStorage), badge démo.

   RÈGLE DURE : ce fichier ne parle JAMAIS au poller réel ni au réseau Telegram.
   Le pipeline "Tes go en cours" est un miroir visuel LOCAL (localStorage) du
   rituel "go N" réel - aucune requête sortante n'est ajoutée par ce module. */
(function () {
  "use strict";

  var DEMO_SOURCE = "data/radar.demo.json";
  var CACHE_KEY = "twRadarCache";   // dernière version reçue → repli hors-ligne
  var DONE_PREFIX = "twDone:";      // étapes cochées, une clé par date de radar
  var GOS_KEY = "twGosPipeline";    // pipeline local des go déclenchés depuis ce PWA
  var RAMPS = { blue: 1, teal: 1, purple: 1, coral: 1, amber: 1, gray: 1 };
  var reducedMotion = false;
  try { reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches; } catch (e) {}

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

  function pad(n) {
    var v = parseInt(n, 10);
    if (isNaN(v)) return String(n);   // rank non numérique : rendu tel quel (m1)
    return (v < 10 ? "0" : "") + v;
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

  /* ---------- extraction du verdict (règle de rendu, pas un champ inventé) ----------
     Le gain en euros est EXTRAIT du champ title du move star, affiché en chiffre
     géant ; le reste du champ redevient le titre affiché sous le verdict.
     ÉLARGI (contre-audit 2026-07-06, bloquant B1) : l'ancienne regex exigeait
     "gagne/gain" collé au montant - 5 des 6 titres star réellement produits en
     prod ne matchaient pas, le verdict (pièce maîtresse de la DA) ne s'affichait
     jamais. Désormais : PREMIER montant en € trouvé n'importe où dans le titre,
     suffixe /mois·/an conservé. Anti-invention inchangé : pas de € dans le
     titre → pas de verdict, jamais de valeur inventée. */
  function extractVerdict(title) {
    var t = String(title || "");
    var m = /(?:(?:gagne|gain|rapporte|encaisse)\s+)?~?\s*([\d][\d\s.,]*)\s*€\s*(\/\s*(?:mois|an|semaine|jour))?/i.exec(t);
    if (!m) return null;
    var num = m[1].replace(/[\s.,](?=\d{3}\b)/g, "")   // séparateurs de milliers
                  .replace(/,00$/, "")                  // ",00" décoratif
                  .replace(/[\s.,]+$/, "").trim();
    if (!num || !/\d/.test(num)) return null;
    var suffix = m[2] ? "/" + m[2].replace(/[\s\/]+/g, "") : "";
    /* rest peut légitimement être vide (titre réduit au montant) : le rendu
       masque alors le sous-titre au lieu de dupliquer le montant (M1). */
    var rest = t.replace(m[0], " ").replace(/\s*[:—–-]\s*/, " ").replace(/\s{2,}/g, " ").trim();
    return { num: num, suffix: suffix, rest: rest };
  }

  /* ---------- rendu ---------- */

  function renderStep(s, idx, isLast, isDone) {
    var html = '<div class="tw-step' + (isDone ? " is-done" : "") + '" data-step="' + idx + '">';
    html += '<div class="tw-step__rail">';
    html += '<button type="button" class="tw-step__num" aria-pressed="' + (isDone ? "true" : "false") +
            '" aria-label="Étape ' + (idx + 1) + ' - marquer comme faite">' +
            (isDone ? "✓" : pad(idx + 1)) + '</button>';
    html += '</div><div class="tw-step__body">';
    if (s.t) html += '<div class="tw-step__t">' + esc(s.t) + '</div>';
    if (s.how) html += '<div class="tw-step__how">' + esc(s.how) + '</div>';
    if (s.paste) {
      html += '<button type="button" class="tw-paste" data-copy="' + esc(s.paste) +
              '" aria-label="Texte à coller, étape ' + (idx + 1) + '">' + esc(s.paste) +
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
    var verdict = isStar ? extractVerdict(m.title) : null;
    var displayTitle = verdict ? verdict.rest : m.title;

    var top = "";
    if (isStar) {
      top += '<span class="tw-badge-star"></span>';
    } else if (m.rank != null && m.rank !== "") {
      top += '<span class="tw-rank" aria-hidden="true">' + pad(m.rank) + '</span>';
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
      /* Titre masqué s'il est vide après extraction du verdict (M1 : un titre
         réduit à "Gagne ~290€" ne doit pas se dupliquer sous le chiffre géant). */
      (displayTitle ? '<h2 class="tw-move__title">' + esc(displayTitle) + '</h2>' : '') +
    '</div>';

    var verdictHtml = "";
    if (verdict) {
      verdictHtml =
        '<div class="tw-verdict">' +
          '<p class="tw-verdict__kicker">💶 Gagne · EUR</p>' +
          '<p class="tw-verdict__row">' +
            '<span class="tw-verdict__approx" aria-hidden="true">~</span>' +
            '<span class="tw-verdict__num">' + esc(verdict.num) + '</span>' +
            '<span class="tw-verdict__unit">€' + esc(verdict.suffix || "") + '</span>' +
          '</p>' +
        '</div>';
    }

    var body = "";
    if (m.pourquoi_maintenant) body += '<p class="tw-why">' + esc(m.pourquoi_maintenant) + '</p>';
    /* Insight : la lecture stratégique (ce que le fait implique) - champ optionnel,
       exigé pour le move star par le prompt d'analyse. Tronqué à 160 (spec 2B).
       Rendu en fenêtre LCD inversée (signature n°3 du Calibre). */
    if (m.insight) body += '<p class="tw-insight">' + esc(String(m.insight).slice(0, 160)) + '</p>';
    if (m.do_now) {
      body += '<div class="tw-donow"><span class="tw-donow__label">👉 Maintenant - le premier euro</span>' +
              '<div>' + esc(m.do_now) + '</div></div>';
    }
    /* Le GO - collé immédiatement après le premier geste (do_now), dans TOUTES
       les dépêches (greffe jury). Étoile = plein ; 2..n = filaire (--ghost). */
    if (m.projet) {
      var goNum = isStar ? "1" : String(m.rank || (idx + 1));
      var step1Label = steps.length && steps[0].t ? steps[0].t : (m.do_now || "");
      body += '<button type="button" class="tw-go' + (isStar ? "" : " tw-go--ghost") + '" ' +
        'data-go="' + esc(goNum) + '" data-proj="' + esc(m.projet) + '" data-step1="' + esc(step1Label) + '">' +
        '<span class="tw-go__cmd">GO&nbsp;' + esc(goNum) + '</span>' +
        '<span class="tw-go__sub">Fable planifie<br />Sonnet exécute</span>' +
      '</button>';
      /* B2 (contre-audit 2026-07-06) : ce bouton est un APERÇU local - il ne
         transmet RIEN au vrai poller. La note le dit sans ambiguïté et son
         contraste est monté d'un cran (classe --strong, --text-2). */
      body += '<p class="tw-go__note tw-go__note--strong">Aperçu : ce bouton simule le déroulé. ' +
        'Le vrai lancement, c\'est répondre «&nbsp;go&nbsp;' + esc(goNum) + '&nbsp;» sur Telegram.</p>';
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
    if (m.ensuite) body += '<div class="tw-ensuite"><b>➡️ Ensuite</b>' + esc(m.ensuite) + '</div>';
    if (m.aussi_pour) body += '<div class="tw-aussi"><b>♻️ Aussi pour</b>' + esc(m.aussi_pour) + '</div>';

    /* Pour la star : verdict + do_now + GO doivent tenir sans scroll (tier 1).
       Le "pourquoi maintenant"/insight/steps suivent en tier 2/3, donc l'ordre
       du corps place le verdict avant "why". */
    var starBody = isStar ? (verdictHtml + body) : body;

    return '<article class="tw-move' + (isStar ? " tw-move--star" : "") +
      '" data-ramp="' + esc(ramp) + '" data-move="' + idx + '" style="--i:' + idx + '">' +
      head +
      '<div class="tw-fold"><div class="tw-move__body" id="' + bodyId + '">' + starBody + '</div></div>' +
    '</article>';
  }

  /* ---------- pipeline local "Tes go en cours" ----------
     Miroir visuel du rituel Telegram réel : quand Adam tape GO ici, on ne
     transmet rien nulle part (aucun fetch, aucun accès à data/executer_move.lock,
     aucune écriture hors localStorage) - on affiche juste, en local, la même
     séquence que celle que le vrai pipeline Fable→Sonnet produit une fois
     "go N" envoyé sur Telegram. Persisté pour survivre à un rafraîchissement. */

  function loadGos() {
    var raw = lsGet(GOS_KEY);
    if (!raw) return [];
    try {
      var arr = JSON.parse(raw);
      return Array.isArray(arr) ? arr : [];
    } catch (e) { return []; }
  }
  function saveGos(list) { lsSet(GOS_KEY, JSON.stringify(list.slice(0, 8))); }

  function pipeGaugeHtml(stage) {
    // stage : 0 aucun, 1 plan, 2 exécution, 3 preuve, 4 tiré
    var labels = ["Plan", "Exécution", "Preuve", "Tiré"];
    return '<ul class="tw-pipe__gauge" aria-hidden="true">' +
      labels.map(function (_, i) {
        return '<li class="' + (stage > i ? "is-done" : "") + '"></li>';
      }).join("") + '</ul>';
  }

  function renderPipe(entry) {
    var stageGauge = entry.stage || 1;
    var feedHtml;
    if (entry.stage >= 3) {
      feedHtml =
        '<li class="tw-pipe__line tw-pipe__line--done"><span class="tw-ok" aria-hidden="true">✓</span>Aperçu - le vrai go se lance sur Telegram</li>' +
        '<li class="tw-pipe__line tw-pipe__line--done"><span class="tw-ok" aria-hidden="true">✓</span>Fable - plan prêt</li>' +
        '<li class="tw-pipe__line tw-pipe__line--done"><span class="tw-ok" aria-hidden="true">✓</span>Sonnet - étape 1 exécutée : ' + esc(entry.step1 || "") + '</li>';
    } else {
      feedHtml =
        '<li class="tw-pipe__line tw-pipe__line--done is-print"><span class="tw-ok" aria-hidden="true">✓</span>Aperçu - le vrai go se lance sur Telegram</li>' +
        '<li class="tw-pipe__line tw-pipe__line--live is-print" data-fable><span class="tw-pipe__dot" aria-hidden="true"></span>Fable - lit le move et le contexte ' + esc(entry.proj) + '…</li>' +
        '<li class="tw-pipe__line is-print" data-sonnet>Sonnet - en attente du plan</li>';
    }
    var proof = entry.stage >= 3
      ? '<p class="tw-pipe__proof">TIRÉ ✓ - la preuve (commit, message, euro) clôt le go</p>'
      : "";
    return '<article class="tw-pipe" data-gid="' + esc(entry.id) + '">' +
      '<div class="tw-pipe__head">' +
        '<span class="tw-pipe__cmd">GO&nbsp;' + esc(entry.n) + '</span>' +
        '<span class="tw-pipe__proj">' + esc(entry.proj) + '</span>' +
        '<span class="tw-pipe__t">' + esc(entry.label) + '</span>' +
      '</div>' +
      pipeGaugeHtml(stageGauge) +
      '<ol class="tw-pipe__feed">' + feedHtml + '</ol>' +
      proof +
    '</article>';
  }

  function renderGosSection() {
    var section = document.getElementById("gos-section");
    var list = document.getElementById("gos-list");
    if (!section || !list) return;
    var gos = loadGos();
    if (!gos.length) { section.hidden = true; list.innerHTML = ""; return; }
    section.hidden = false;
    list.innerHTML = gos.map(renderPipe).join("");
  }

  function triggerGo(btn) {
    if (btn.classList.contains("is-sent")) return;
    var n = btn.getAttribute("data-go");
    var proj = btn.getAttribute("data-proj");
    var step1 = btn.getAttribute("data-step1");
    var now = new Date();
    var hm = pad(now.getHours()) + ":" + pad(now.getMinutes());

    btn.classList.remove("tw-go--ghost");
    btn.classList.add("is-sent");
    btn.setAttribute("aria-disabled", "true");
    /* B2 : jamais "TRANSMIS" - rien ne part d'ici. L'état terminal dit ce
       qu'il est (un aperçu) et rappelle le seul vrai canal de lancement. */
    btn.querySelector(".tw-go__cmd").textContent = "APERÇU ✓";
    btn.querySelector(".tw-go__sub").innerHTML = "LANCE-LE SUR<br />TELEGRAM : GO " + esc(n);
    announce("Aperçu du go " + n + ". Rien n'est parti : pour le lancer vraiment, réponds go " + n + " sur Telegram.");

    var entry = { id: String(Date.now()), n: n, proj: proj, step1: step1, label: "Aujourd’hui · " + hm, stage: 1 };
    var gos = loadGos();
    gos.unshift(entry);
    saveGos(gos);
    renderGosSection();

    var section = document.getElementById("gos-section");
    var card = section.querySelector('[data-gid="' + entry.id + '"]');
    if (!card) return;
    var lines = card.querySelectorAll(".tw-pipe__line");

    function on(el) { if (el) el.classList.add("is-on"); }
    function fablePlan() {
      var f = card.querySelector("[data-fable]");
      if (f) {
        f.classList.remove("tw-pipe__line--live");
        f.classList.add("tw-pipe__line--done");
        f.innerHTML = '<span class="tw-ok" aria-hidden="true">✓</span>Fable - plan prêt';
      }
      var s = card.querySelector("[data-sonnet]");
      if (s) {
        s.classList.add("tw-pipe__line--live");
        s.innerHTML = '<span class="tw-pipe__dot" aria-hidden="true"></span>Sonnet - exécute l’étape 1 : ' + esc(step1 || "");
      }
      entry.stage = 2;
      var idx = gos.findIndex(function (g) { return g.id === entry.id; });
      if (idx !== -1) { gos[idx] = entry; saveGos(gos); }
      var gauge = card.querySelector(".tw-pipe__gauge");
      if (gauge) gauge.outerHTML = pipeGaugeHtml(2);
    }
    if (reducedMotion) {
      lines.forEach(on);
      fablePlan();
    } else {
      setTimeout(function () { on(lines[0]); }, 60);
      setTimeout(function () { on(lines[1]); }, 380);
      setTimeout(function () { on(lines[2]); }, 700);
      setTimeout(fablePlan, 2200);
    }
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

    /* Copie en un tap, feedback "Copié ✓" 1.2s (design-system .is-copied) */
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
        btn.textContent = nowDone ? "✓" : pad(sIdx + 1);
        var bar = card.querySelector(".tw-progress");
        if (bar) {
          bar.style.setProperty("--done", String(list.length));
          bar.setAttribute("aria-valuenow", String(list.length));
        }
      });
    });

    /* Le go (états : envoi 240ms, puis impression du fil 320ms/ligne) - miroir
       visuel local uniquement, voir commentaire au-dessus de triggerGo(). */
    container.querySelectorAll(".tw-go").forEach(function (btn) {
      btn.addEventListener("click", function () { triggerGo(btn); });
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
    var moveCount = (data.moves || []).length;
    var bits = [];
    if (st.fresh != null) bits.push('<li class="tw-cell"><span class="tw-cell__k">📶 Signaux</span><span class="tw-cell__v">' + esc(st.fresh) + '</span></li>');
    if (st.cut != null) bits.push('<li class="tw-cell"><span class="tw-cell__k">✂️ Coupés</span><span class="tw-cell__v">' + esc(st.cut) + '</span></li>');
    bits.push('<li class="tw-cell"><span class="tw-cell__k">Moves</span><span class="tw-cell__v">' + esc(moveCount) + '</span></li>');
    if (isDemo) bits.push('<li class="tw-cell"><span class="tw-badge-demo">Démo</span></li>');
    var statsEl = document.getElementById("stats");
    statsEl.hidden = !bits.length;
    statsEl.innerHTML = bits.join("");

    /* Bandeau discret quand le réseau a échoué et qu'on sert la version gardée */
    document.getElementById("banner-zone").innerHTML = opts.fromCache
      ? '<div class="tw-banner" role="status">Hors ligne - dernière version reçue' +
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

    renderGosSection();

    var skill = document.getElementById("skill");
    if (data.skill_up) {
      skill.hidden = false;
      skill.style.setProperty("--i", String(moves.length));
      document.getElementById("skill-text").textContent = data.skill_up;
    } else {
      skill.hidden = true;
    }

    document.getElementById("foot").textContent = isDemo
      ? "THE WIRE - RADAR QUOTIDIEN · DONNÉES DÉMO · 0 REQUÊTE EXTERNE · 100% OFFLINE · SW V1"
      : "THE WIRE - RADAR QUOTIDIEN · GÉNÉRÉ CHAQUE MATIN À 10H · 0 REQUÊTE EXTERNE · 100% OFFLINE · SW V1";
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
