/* A.A.News service worker: offline support + push notifications */
const CACHE = 'aa-news-v1';
const PRECACHE = ['/offline', '/static/icons/icon-192.png', '/static/icons/badge-96.png'];

self.addEventListener('install', (event) => {
  event.waitUntil(caches.open(CACHE).then((c) => c.addAll(PRECACHE)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

// Only public, read-only pages are cached. Admin, login, cron and push routes are never touched.
const NEWS_DATA = /^\/(get_news|get_categories|category\/)/;

self.addEventListener('fetch', (event) => {
  const req = event.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);
  if (url.origin !== location.origin) return;

  // Page visits: network first, fall back to the offline page
  if (req.mode === 'navigate') {
    if (url.pathname !== '/') return;
    event.respondWith(
      fetch(req)
        .then((res) => { const copy = res.clone(); caches.open(CACHE).then((c) => c.put('/', copy)); return res; })
        .catch(() => caches.match('/').then((r) => r || caches.match('/offline')))
    );
    return;
  }

  // News data: network first, last copy when offline
  if (NEWS_DATA.test(url.pathname)) {
    event.respondWith(
      fetch(req)
        .then((res) => { const copy = res.clone(); caches.open(CACHE).then((c) => c.put(req, copy)); return res; })
        .catch(() => caches.match(req))
    );
    return;
  }

  // Icons and static files: cache first
  if (url.pathname.startsWith('/static/')) {
    event.respondWith(
      caches.match(req).then((hit) => hit || fetch(req).then((res) => {
        const copy = res.clone(); caches.open(CACHE).then((c) => c.put(req, copy)); return res;
      }))
    );
  }
});

// ---- Push notifications ----
self.addEventListener('push', (event) => {
  let data = {};
  try { data = event.data ? event.data.json() : {}; } catch (e) { data = { body: event.data && event.data.text() }; }
  const title = data.title || 'A.A.News';
  event.waitUntil(self.registration.showNotification(title, {
    body: data.body || '',
    icon: '/static/icons/icon-192.png',
    badge: '/static/icons/badge-96.png',
    image: data.image || undefined,
    tag: data.tag || 'breaking-news',
    renotify: true,
    data: { url: data.url || '/' },
  }));
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const target = (event.notification.data && event.notification.data.url) || '/';
  event.waitUntil(
    clients.matchAll({ type: 'window', includeUncontrolled: true }).then((list) => {
      const sameSite = new URL(target, location.origin).origin === location.origin;
      if (sameSite) {
        for (const c of list) {
          if ('focus' in c) { c.navigate(target); return c.focus(); }
        }
      }
      // Original article (another website): open it in a new tab/window
      return clients.openWindow(target);
    })
  );
});
