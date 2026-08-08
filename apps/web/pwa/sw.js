/*
 * Service worker — the part that makes this survive a bad network.
 *
 * Two different caching rules, because the two kinds of content fail
 * differently:
 *
 *   shell (html/css/icons)  cache-first  — never changes mid-session, and a
 *                                          spinner on the launch screen is the
 *                                          worst possible first impression
 *   audio (/api/ivr/audio)  cache-first  — content-hashed filenames, so a hit
 *                                          is always correct and never stale
 *
 * Everything else (the POSTs that actually answer a question) is left alone:
 * a cached eligibility answer would be worse than an honest failure, because
 * the rules and the person's situation both change.
 */

const VERSION = 'setu-v1';
const SHELL = [
  './',
  './index.html',
  './manifest.webmanifest',
  './icon-192.png',
  './icon-512.png',
];

self.addEventListener('install', event => {
  // addAll fails atomically: one missing file would leave no cache at all, so
  // add individually and tolerate misses.
  event.waitUntil(
    caches.open(VERSION)
      .then(cache => Promise.allSettled(SHELL.map(url => cache.add(url))))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys()
      .then(keys => Promise.all(keys.filter(k => k !== VERSION).map(k => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', event => {
  const { request } = event;
  if (request.method !== 'GET') return;             // never cache a POST answer

  const url = new URL(request.url);
  const isAudio = url.pathname.startsWith('/api/ivr/audio/');
  const isShell = url.origin === self.location.origin && !url.pathname.startsWith('/api/');

  if (!isAudio && !isShell) return;

  event.respondWith(
    caches.match(request).then(hit => {
      if (hit) return hit;
      return fetch(request).then(response => {
        if (response.ok) {
          const copy = response.clone();
          caches.open(VERSION).then(cache => cache.put(request, copy));
        }
        return response;
      }).catch(() => hit);                          // offline and uncached: let it fail
    })
  );
});
