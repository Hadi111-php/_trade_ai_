const CACHE = 'scalp-lab-v6-direct-bybit';
const ASSETS = [
  './',
  './index.html',
  './styles.css',
  './manifest.webmanifest',
  './icon.svg',
  './src/js/main.js',
  './src/js/app.js',
  './src/js/core/config.js',
  './src/js/core/utils.js',
  './src/js/services/logger.js',
  './src/js/services/settings-store.js',
  './src/js/services/market-client.js',
  './src/js/services/strategy.js',
  './src/js/services/paper-broker.js',
  './src/js/services/real-broker.js',
  './src/js/services/performance-report.js',
  './src/js/ui/price-chart.js',
  './src/js/ui/view.js'
];

self.addEventListener('install', event => {
  event.waitUntil(caches.open(CACHE).then(cache => cache.addAll(ASSETS)));
  self.skipWaiting();
});

self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(keys => Promise.all(keys.filter(key => key !== CACHE).map(key => caches.delete(key))))
  );
  self.clients.claim();
});

self.addEventListener('fetch', event => {
  const url = new URL(event.request.url);
  if (event.request.method !== 'GET' || url.origin !== location.origin || url.pathname.startsWith('/api/')) return;

  // Network-first keeps module/UI updates visible during development while still
  // allowing the shell to open offline. Market APIs are intentionally never cached.
  event.respondWith(
    fetch(event.request)
      .then(response => {
        const copy = response.clone();
        caches.open(CACHE).then(cache => cache.put(event.request, copy));
        return response;
      })
      .catch(() => caches.match(event.request))
  );
});
