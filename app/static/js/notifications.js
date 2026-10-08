(() => {
  const bell = document.getElementById('notification-bell');
  if (!bell) return;
  let pending = false;
  async function refresh() {
    if (document.hidden || pending || !navigator.onLine) return;
    pending = true;
    try {
      const response = await fetch(bell.dataset.countUrl, {
        credentials: 'same-origin', cache: 'no-store', headers: {Accept: 'application/json'},
      });
      if (!response.ok || response.redirected) return;
      const {unread} = await response.json();
      if (!Number.isSafeInteger(unread) || unread < 0) return;
      bell.setAttribute('aria-label', `Notifications, ${unread} unread`);
      const badge = bell.querySelector('.notification-badge');
      badge.textContent = unread > 99 ? '99+' : String(unread);
      badge.hidden = unread === 0;
    } catch (_) {
      // Keep the last known count when the connection is interrupted.
    } finally {
      pending = false;
    }
  }
  window.setInterval(refresh, 60000);
  document.addEventListener('visibilitychange', refresh);
})();
