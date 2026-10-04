/* A.A.News PWA: service worker, install button, notification button */
(function () {
  const notifyBtn = document.getElementById('notify-btn');
  const installBtn = document.getElementById('install-btn');
  const isIOS = /iphone|ipad|ipod/i.test(navigator.userAgent);
  const isStandalone = window.matchMedia('(display-mode: standalone)').matches || navigator.standalone;

  function urlBase64ToUint8Array(base64String) {
    const padding = '='.repeat((4 - (base64String.length % 4)) % 4);
    const base64 = (base64String + padding).replace(/-/g, '+').replace(/_/g, '/');
    const raw = atob(base64);
    return Uint8Array.from([...raw].map((c) => c.charCodeAt(0)));
  }

  function setNotifyLabel(on) {
    if (!notifyBtn) return;
    notifyBtn.textContent = '🔔';
    notifyBtn.dataset.on = on ? '1' : '0';
    notifyBtn.title = on ? 'Alerts are ON - tap to turn off' : 'Get breaking news alerts';
  }

  if (!('serviceWorker' in navigator)) { if (notifyBtn) notifyBtn.style.display = 'none'; return; }

  let registration = null;
  navigator.serviceWorker.register('/sw.js').then(async (reg) => {
    registration = reg;
    if ('PushManager' in window && Notification.permission === 'granted') {
      const sub = await reg.pushManager.getSubscription();
      if (sub) {
        setNotifyLabel(true);
        // Quietly re-send so the server always has a fresh copy
        fetch('/push/subscribe', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(sub) }).catch(() => {});
      }
    }
  }).catch((e) => console.warn('SW registration failed', e));

  async function enableNotifications() {
    if (isIOS && !isStandalone) {
      alert('iPhone: first tap Share → "Add to Home Screen", then open A.A.News from the home screen and tap Alerts again.');
      return;
    }
    if (!('PushManager' in window)) { alert('Notifications are not supported on this browser.'); return; }
    const perm = await Notification.requestPermission();
    if (perm !== 'granted') { alert('Notifications were blocked. You can allow them from the browser/site settings.'); return; }
    const keyRes = await fetch('/push/public-key');
    const { key } = await keyRes.json();
    if (!key) { alert('Notifications are not available on the server yet.'); return; }
    const reg = registration || await navigator.serviceWorker.ready;
    const sub = await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: urlBase64ToUint8Array(key) });
    const res = await fetch('/push/subscribe', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(sub) });
    if (res.ok) setNotifyLabel(true); else alert('Could not save your subscription. Please try again.');
  }

  async function disableNotifications() {
    const reg = registration || await navigator.serviceWorker.ready;
    const sub = await reg.pushManager.getSubscription();
    if (sub) {
      await fetch('/push/unsubscribe', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ endpoint: sub.endpoint }) }).catch(() => {});
      await sub.unsubscribe();
    }
    setNotifyLabel(false);
  }

  if (notifyBtn) {
    notifyBtn.addEventListener('click', () => {
      (notifyBtn.dataset.on === '1' ? disableNotifications() : enableNotifications()).catch((e) => { console.error(e); alert('Something went wrong. Please try again.'); });
    });
  }

  // "Install app" button (Android/desktop Chrome/Edge)
  let deferredPrompt = null;
  window.addEventListener('beforeinstallprompt', (e) => {
    e.preventDefault();
    deferredPrompt = e;
    if (installBtn && !isStandalone) installBtn.style.display = '';
  });
  if (installBtn) {
    installBtn.addEventListener('click', async () => {
      if (!deferredPrompt) return;
      deferredPrompt.prompt();
      await deferredPrompt.userChoice;
      deferredPrompt = null;
      installBtn.style.display = 'none';
    });
  }
  window.addEventListener('appinstalled', () => { if (installBtn) installBtn.style.display = 'none'; });
})();
