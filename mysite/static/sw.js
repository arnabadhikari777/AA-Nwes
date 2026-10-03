/* A.A.News service worker. Bump VERSION to force clients to refresh caches. */
const VERSION = 'v2';
const STATIC = 'aa-static-' + VERSION, PAGES = 'aa-pages-' + VERSION;
const PRECACHE = ['/offline', '/static/css/style.css', '/static/js/app.js', '/static/icons/icon-192.png', '/static/icons/icon-512.png'];
const NEVER = [/^\/admin/, /^\/login/, /^\/logout/, /^\/add_news/, /^\/api\//, /^\/fragment\//, /^\/search/, /^\/saved/, /^\/history/, /^\/sw\.js/];

self.addEventListener('install', e => {
  e.waitUntil(caches.open(STATIC).then(c => c.addAll(PRECACHE.map(u => new Request(u, {cache: 'reload'})))));
});
self.addEventListener('message', e => { if (e.data === 'SKIP_WAITING') self.skipWaiting(); });
self.addEventListener('activate', e => {
  e.waitUntil(caches.keys().then(keys => Promise.all(keys.filter(k => ![STATIC, PAGES].includes(k)).map(k => caches.delete(k))))
    .then(() => self.clients.claim()));
});

async function trim(name, max) {
  const c = await caches.open(name), keys = await c.keys();
  if (keys.length > max) { await c.delete(keys[0]); return trim(name, max); }
}

self.addEventListener('fetch', e => {
  const req = e.request, url = new URL(req.url);
  if (req.method !== 'GET' || url.origin !== location.origin) return;       // never touch cross-origin / POST
  if (NEVER.some(r => r.test(url.pathname))) return;                        // private / dynamic: network only
  if (req.headers.get('range')) return;

  // Static assets: stale-while-revalidate
  if (url.pathname.startsWith('/static/') && !url.pathname.startsWith('/static/uploads/')) {
    e.respondWith(caches.open(STATIC).then(async c => {
      const hit = await c.match(req, {ignoreSearch: true});
      const net = fetch(req).then(r => { if (r.ok) c.put(req, r.clone()); return r; }).catch(() => hit);
      return hit || net;
    }));
    return;
  }
  // Pages: network first; fall back to the last copy we saw (max 30 pages), then the offline page.
  if (req.mode === 'navigate' || (req.headers.get('accept') || '').includes('text/html')) {
    e.respondWith(fetch(req).then(r => {
      const cc = r.headers.get('Cache-Control') || '';
      if (r.ok && r.status === 200 && !cc.includes('no-store')) {
        const copy = r.clone();
        caches.open(PAGES).then(c => c.put(req, copy).then(() => trim(PAGES, 30)));
      }
      return r;
    }).catch(async () => (await caches.match(req)) || (await caches.match('/offline'))));
  }
});
