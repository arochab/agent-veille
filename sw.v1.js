/* Service worker — Veille PWA.
   Network-first PARTOUT : app-shell ET données (data/radar*.json). En ligne, le
   radar est donc toujours frais ; hors-ligne UNIQUEMENT, on ressert la dernière
   version en cache (mieux qu'un écran cassé — la date affichée dit son âge).
   Purge tout cache != version courante à l'activation. Calqué sur Claude Eats Tokens. */
const CACHE = "veille-v4"; // v4 : Calibre + emojis-lexique + couleurs projet reactivees (retour client 2026-07-06)
const ASSETS = [
  "./", "./index.html",
  "./pwa/app.js", "./pwa/config.js", "./pwa/design-system.css",
  "./pwa/manifest.json", "./pwa/icon-192.png", "./pwa/icon-512.png",
  "./assets/the-wire-logo.png",
  // radar.demo.json est précaché : hors-ligne au premier lancement, la démo
  // s'affiche quand même (le fetch réseau reste prioritaire — jamais périmé en ligne).
  "./data/radar.demo.json"
];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(ASSETS)).then(() => self.skipWaiting()));
});
self.addEventListener("message", (e) => { if (e.data === "skipWaiting") self.skipWaiting(); });
self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

function isData(url) {
  return /data\/radar.*\.json/.test(url);
}

self.addEventListener("fetch", (e) => {
  const url = e.request.url;
  if (isData(url)) {
    // network-first : frais en ligne, repli cache hors-ligne uniquement
    e.respondWith(fetch(e.request).catch(() => caches.match(e.request)));
    return;
  }
  // app-shell : network-first, repli cache hors-ligne
  e.respondWith(
    fetch(e.request)
      .then((r) => {
        const copy = r.clone();
        caches.open(CACHE).then((c) => c.put(e.request, copy)).catch(() => {});
        return r;
      })
      .catch(() => caches.match(e.request).then((m) => m || caches.match("./index.html")))
  );
});
