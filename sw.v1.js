/* Service worker v1 — Veille PWA.
   Network-first sur l'app-shell (toujours la dernière version), network-ONLY sur
   les données (data/radar*.json — jamais servir un radar périmé depuis le cache).
   Purge tout cache != version courante à l'activation. Calqué sur Claude Eats Tokens. */
const CACHE = "veille-v1";
const ASSETS = [
  "./", "./index.html",
  "./pwa/app.js", "./pwa/config.js", "./pwa/styles.css",
  "./pwa/manifest.json", "./pwa/icon-192.png", "./pwa/icon-512.png"
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
    // network-only : le radar doit toujours être frais
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
