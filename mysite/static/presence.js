/* A.A.News live presence: tells the server "I'm here" every few seconds.
   <script src="/static/presence.js" defer>                   -> counted as a visitor
   <script src="/static/presence.js" data-role="admin" defer> -> counted as a dashboard viewer */
(function () {
  var s = document.currentScript;
  var role = (s && s.getAttribute('data-role')) || (location.pathname.indexOf('/admin') === 0 ? 'admin' : 'visitor');

  function rid() {
    try { if (crypto.randomUUID) return crypto.randomUUID().replace(/-/g, ''); } catch (e) {}
    return (Math.random().toString(36).slice(2) + Date.now().toString(36) + Math.random().toString(36).slice(2)).slice(0, 32);
  }
  function stored(store, key) {
    try { var v = store.getItem(key); if (!v) { v = rid(); store.setItem(key, v); } return v; } catch (e) { return rid(); }
  }
  var browser = stored(window.localStorage, 'aa_bid');   // one person (same browser, any number of tabs)
  var tab = stored(window.sessionStorage, 'aa_tid');     // this tab

  function send(url, data) {
    var body = JSON.stringify(data);
    try { if (navigator.sendBeacon && navigator.sendBeacon(url, new Blob([body], { type: 'application/json' }))) return; } catch (e) {}
    try { fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: body, keepalive: true }); } catch (e) {}
  }
  function ping() { send('/presence/ping', { tab: tab, browser: browser, role: role, page: location.pathname }); }
  function leave() { send('/presence/leave', { tab: tab }); }

  ping();
  setInterval(ping, 12000);
  document.addEventListener('visibilitychange', function () { if (!document.hidden) ping(); });
  window.addEventListener('pageshow', function (e) { if (e.persisted) ping(); });
  window.addEventListener('pagehide', leave);   // closing the tab / leaving the page => count drops at once
})();
