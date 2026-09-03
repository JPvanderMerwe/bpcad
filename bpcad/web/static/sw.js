/*
 * Service worker: what makes this installable, and deliberately not much more.
 *
 * WHAT IS CACHED, AND WHAT MUST NEVER BE.
 *
 * The shell - the page, the stylesheet, the script, the icons - is cached so
 * the app opens instantly and survives a dropped wifi. Everything under /api/
 * goes straight to the network, always, with no fallback.
 *
 * That asymmetry is the whole design. A cached /api/parts is a library that
 * silently omits what you made this morning. A cached STL is somebody printing
 * yesterday's geometry off today's spec. A cached turntable frame is a picture
 * of a part that has since been refined. This app's entire claim is that the
 * numbers you are shown are the numbers that were measured, and a stale cache
 * breaks that claim quietly, which is the worst way for it to break.
 *
 * Renders are the one thing that would be safe to cache, because a built part's
 * geometry never changes - a refinement writes a NEW part. They are left
 * uncached anyway: the server already marks them immutable, so the browser's
 * own HTTP cache handles it correctly and a second layer here would only be
 * another place for them to go stale.
 */

const SHELL = 'bpcad-shell-v1';

const SHELL_FILES = [
  '/',
  '/static/app.css',
  '/static/app.js',
  '/static/manifest.webmanifest',
  '/static/icons/icon-192.png',
  '/static/icons/icon-512.png',
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(SHELL).then((cache) => cache.addAll(SHELL_FILES))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (event) => {
  // Drop every older shell. A service worker that accumulates versions serves
  // a mixture of two releases, which is harder to diagnose than either.
  event.waitUntil(
    caches.keys()
      .then((names) => Promise.all(
        names.filter((n) => n !== SHELL).map((n) => caches.delete(n))
      ))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url);

  // Never our business: other origins, and anything that is not a plain GET.
  if (url.origin !== self.location.origin || event.request.method !== 'GET') return;

  // THE API IS NEVER CACHED. Not even as a fallback - a part list or a
  // measurement served from cache is worse than an honest failure.
  if (url.pathname.startsWith('/api/')) return;

  // The shell: network first so an update is picked up the moment it exists,
  // cache second so the app still opens with no network at all.
  event.respondWith(
    fetch(event.request)
      .then((response) => {
        if (response && response.ok) {
          const copy = response.clone();
          caches.open(SHELL).then((cache) => cache.put(event.request, copy));
        }
        return response;
      })
      .catch(() => caches.match(event.request).then(
        (hit) => hit || caches.match('/')
      ))
  );
});
