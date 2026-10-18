/* Service worker: gjør appen rask å starte og brukbar uten nett (siste data vises).
   - app-filene: hentes fra hurtigbuffer, oppdateres i bakgrunnen
   - data.json:  hentes fra nett først, faller tilbake til siste lagrede versjon */
const CACHE = "aksjeradar-v6";
const SHELL = ["./", "./index.html", "./app.css", "./app.js", "./manifest.webmanifest",
  "./icons/icon-192.png", "./icons/icon-512.png", "./icons/apple-touch-icon.png"];

self.addEventListener("install", e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(SHELL)).catch(() => {}));
  self.skipWaiting();
});

self.addEventListener("activate", e => {
  e.waitUntil(caches.keys().then(keys => Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k)))));
  self.clients.claim();
});

self.addEventListener("fetch", e => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET" || url.origin !== location.origin) return;

  if (url.pathname.endsWith("/data.json") || url.pathname.endsWith("/autotrader.json") || url.pathname.endsWith("/intraday.json") || url.pathname.includes("/stocks/")) {
    const key = url.origin + url.pathname;
    e.respondWith(
      fetch(e.request).then(res => {
        if (res.ok) { const copy = res.clone(); caches.open(CACHE).then(c => c.put(key, copy)); }
        return res;
      }).catch(() => caches.match(key))
    );
    return;
  }

  e.respondWith(
    caches.match(e.request).then(cached => {
      const network = fetch(e.request).then(res => {
        if (res.ok) { const copy = res.clone(); caches.open(CACHE).then(c => c.put(e.request, copy)); }
        return res;
      }).catch(() => cached);
      return cached || network;
    })
  );
});
