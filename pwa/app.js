/* Veille PWA — logique de rendu. Vanilla, no-build.
   Charge le premier radar disponible (data/radar.json puis demo), rend les moves. */
(function () {
  var RAMP = {
    blue:   { tint: "#E6F1FB", ink: "#0C447C", bar: "#378ADD" },
    teal:   { tint: "#E1F5EE", ink: "#0F6E56", bar: "#1D9E75" },
    purple: { tint: "#EEEDFE", ink: "#3C3489", bar: "#7F77DD" },
    coral:  { tint: "#FAECE7", ink: "#993C1D", bar: "#D85A30" },
    amber:  { tint: "#FAEEDA", ink: "#854F0B", bar: "#BA7517" },
    gray:   { tint: "#F1EFE8", ink: "#444441", bar: "#888780" }
  };

  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }

  function loadRadar() {
    var sources = (window.VEILLE_SOURCES || ["data/radar.demo.json"]).slice();
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

  function renderStep(s, idx, last, bar) {
    var paste = s.paste
      ? '<div class="paste" data-copy="' + esc(s.paste) + '">' + esc(s.paste) +
        '<span class="copy-hint"><i class="ti ti-copy"></i></span></div>'
      : "";
    return '<div class="step">' +
      '<div class="step-rail"><div class="step-num" style="background:' + bar + '">' + (idx + 1) + '</div>' +
      (last ? "" : '<div class="step-line"></div>') + '</div>' +
      '<div class="step-body">' +
        '<div class="step-t">' + esc(s.t) + '</div>' +
        (s.how ? '<div class="step-how">' + esc(s.how) + '</div>' : "") +
        paste +
        (s.done ? '<div class="done"><i class="ti ti-circle-check"></i> Done when: ' + esc(s.done) + '</div>' : "") +
      '</div></div>';
  }

  function renderMove(m) {
    var t = RAMP[m.ramp] || RAMP.gray;
    var steps = (m.steps || []).map(function (s, i) {
      return renderStep(s, i, i === m.steps.length - 1, t.bar);
    }).join("");
    var rankChip = m.rank === "star"
      ? '<span class="chip" style="color:' + t.ink + ';background:' + t.tint + '">★ Move of the day</span>'
      : '<span class="chip" style="color:' + t.ink + ';background:' + t.tint + '">' + esc(m.rank) + '</span>';
    var cross = m.cross
      ? '<div class="cross"><i class="ti ti-link"></i> <b>Cross-project:</b> ' + esc(m.cross) + '</div>'
      : "";
    return '<article class="move' + (m.rank === "star" ? " star" : "") + '" style="border-left-color:' + t.bar + '">' +
      '<div class="move-top">' +
        '<div class="move-icon" style="background:' + t.tint + '"><i class="ti ' + esc(m.icone || "ti-bolt") + '" style="color:' + t.ink + '"></i></div>' +
        rankChip +
        '<span class="chip" style="color:' + t.ink + '">' + esc(m.projet) + '</span>' +
        '<span class="move-meta">' + esc(m.meta || "") + '</span>' +
      '</div>' +
      '<h2 class="move-title">' + esc(m.title) + '</h2>' +
      (m.intro ? '<p class="move-intro">' + esc(m.intro) + '</p>' : "") +
      steps +
      '<div class="cards2">' +
        '<div class="minicard"><div class="lbl" style="color:' + RAMP.teal.ink + '">↗ Unlocks</div><div class="val">' + esc(m.unlocks || "") + '</div></div>' +
        '<div class="minicard"><div class="lbl" style="color:' + RAMP.coral.ink + '">👁 Rivals miss</div><div class="val">' + esc(m.miss || "") + '</div></div>' +
      '</div>' + cross +
    '</article>';
  }

  function wireCopy() {
    document.querySelectorAll(".paste").forEach(function (el) {
      el.addEventListener("click", function () {
        var txt = el.getAttribute("data-copy") || "";
        if (navigator.clipboard) navigator.clipboard.writeText(txt).catch(function(){});
        var hint = el.querySelector(".copy-hint");
        if (hint) { hint.innerHTML = '<i class="ti ti-check"></i>'; setTimeout(function(){ hint.innerHTML = '<i class="ti ti-copy"></i>'; }, 1200); }
      });
    });
  }

  function render(data) {
    document.getElementById("date").textContent = data.date || "";
    document.getElementById("headline").textContent = data.headline || "";
    var isDemo = data.stats && data.stats.demo;
    var st = data.stats || {};
    document.getElementById("stats").innerHTML =
      '<span><b>' + (st.fresh != null ? st.fresh : "—") + '</b> fresh</span>' +
      '<span><b>' + (st.cut != null ? st.cut : "—") + '</b> cut as noise</span>' +
      (isDemo ? '<span class="demo-badge">demo data</span>' : "");

    var moves = data.moves || [];
    var main = document.getElementById("moves");
    if (!moves.length) {
      main.innerHTML = '<div class="empty"><i class="ti ti-coffee"></i><p>Nothing new today. Quiet day = good news.</p></div>';
    } else {
      main.innerHTML = moves.map(renderMove).join("");
      wireCopy();
    }
    if (data.skill_up) {
      document.getElementById("skill").hidden = false;
      document.getElementById("skill-text").textContent = data.skill_up;
    }
    document.getElementById("foot").textContent =
      "Generated by your watch system · " + (data.__source === "data/radar.demo.json" ? "showing demo until first real run" : "live");
  }

  function fail() {
    document.getElementById("headline").textContent = "";
    document.getElementById("moves").innerHTML =
      '<div class="empty"><i class="ti ti-cloud-off"></i><p>No radar yet. It generates each morning.</p></div>';
  }

  loadRadar().then(render).catch(fail);
})();
