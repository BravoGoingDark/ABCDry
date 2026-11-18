{% load i18n %}// Farmer app service worker (served by dashboard.views.farmer_views.farmer_service_worker).
//
// Goal: the app opens in the field without a connection and shows the last
// saved plan, tasks and weather.
//   - static files (map library, icons, styles): cache first, refreshed in the background
//   - farmer pages and farm data (GET /farmer/..., GET /assistant/chat/): network first,
//     the last saved copy when offline
//   - changes (POST / PATCH / DELETE) always need the network: never queued, never faked
// Saved farm data belongs to one signed-in farmer: it is deleted at logout and
// when another user signs in on the same phone.
const VERSION = '{{ version }}';
const SHELL = 'farmer-shell-' + VERSION;
const DATA = 'farmer-data';
const META = 'farmer-meta';
const ASSETS = [{% for url in assets %}'{{ url|escapejs }}'{% if not forloop.last %}, {% endif %}{% endfor %}];
const OFFLINE_HTML = `<!doctype html><html lang="{{ LANGUAGE_CODE|default:'en' }}" dir="{% if LANGUAGE_BIDI %}rtl{% else %}ltr{% endif %}"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><meta name="theme-color" content="#012d1d">
<title>APWRS</title><style>body{margin:0;min-height:100vh;display:grid;place-items:center;font-family:system-ui,sans-serif;
background:#f9f9ff;color:#012d1d;text-align:center;padding:24px}h1{font-size:20px}p{color:#41484d;max-width:320px}
button{margin-top:12px;padding:12px 20px;border:0;border-radius:12px;background:#012d1d;color:#fff;font-size:16px}</style></head>
<body><div><h1>{% filter escapejs %}{% trans "You are offline" %}{% endfilter %}</h1>
<p>{% filter escapejs %}{% trans "Open the app once with a connection: it will then keep your farm’s last data for the field." %}{% endfilter %}</p>
<button onclick="location.reload()">{% filter escapejs %}{% trans "Try again" %}{% endfilter %}</button></div></body></html>`;

self.addEventListener('install', event => {
  event.waitUntil(caches.open(SHELL)
    .then(cache => Promise.all(ASSETS.map(url => cache.add(url).catch(() => null))))
    .then(() => self.skipWaiting()));
});

self.addEventListener('activate', event => {
  event.waitUntil(caches.keys()
    .then(keys => Promise.all(keys.filter(k => k.startsWith('farmer-shell-') && k !== SHELL).map(k => caches.delete(k))))
    .then(() => self.clients.claim()));
});

async function networkFirst(request) {
  const cache = await caches.open(DATA);
  try {
    const response = await fetch(request);
    if (response.ok) cache.put(request, response.clone());
    return response;
  } catch (err) {
    const saved = await cache.match(request, { ignoreSearch: request.mode === 'navigate' });
    if (saved) return saved;
    if (request.mode === 'navigate') {
      return new Response(OFFLINE_HTML, { headers: { 'Content-Type': 'text/html; charset=utf-8' } });
    }
    throw err;
  }
}

async function cacheFirst(request) {
  const cache = await caches.open(SHELL);
  const saved = await cache.match(request);
  const fresh = fetch(request).then(response => {
    if (response.ok || response.type === 'opaque') cache.put(request, response.clone());
    return response;
  }).catch(() => saved);
  return saved || fresh;
}

self.addEventListener('fetch', event => {
  const request = event.request;
  if (request.method !== 'GET') return;                 // changes always go to the network
  const url = new URL(request.url);
  if (url.origin === self.location.origin) {
    if (url.pathname === '/farmer/sw.js') return;
    if (url.pathname.startsWith('/static/')) return event.respondWith(cacheFirst(request));
    if (url.pathname.startsWith('/farmer/') || url.pathname === '/assistant/chat/') {
      return event.respondWith(networkFirst(request));
    }
    return;
  }
  if (url.hostname === 'fonts.googleapis.com' || url.hostname === 'fonts.gstatic.com') {
    event.respondWith(cacheFirst(request));
  }
});

// The page says who is signed in, and when the farmer logs out.
self.addEventListener('message', event => {
  const msg = event.data || {};
  if (msg.type === 'logout') {
    event.waitUntil(caches.delete(DATA));
  } else if (msg.type === 'user') {
    event.waitUntil((async () => {
      const meta = await caches.open(META);
      const saved = await meta.match('/__farmer_user__');
      const previous = saved ? await saved.text() : null;
      if (previous !== null && previous !== String(msg.id)) await caches.delete(DATA);
      await meta.put('/__farmer_user__', new Response(String(msg.id)));
    })());
  }
});
