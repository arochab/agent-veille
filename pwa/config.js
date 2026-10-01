/* Public portfolio mode is explicit and isolated from private sources. */
(function () {
  window.VEILLE_DEMO = location.hostname.endsWith('.github.io') || new URLSearchParams(location.search).get('demo') === '1';
  window.VEILLE_SOURCES = window.VEILLE_DEMO ? ['data/radar.demo.json'] : ['data/radar.json', 'data/radar.demo.json'];
  window.SUIVI_SOURCES = window.VEILLE_DEMO ? [] : ['data/go_suivi.json'];
  window.PROJETS_SOURCES = window.VEILLE_DEMO ? [] : ['data/projets.json'];
})();
