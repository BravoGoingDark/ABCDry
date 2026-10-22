"""Server-side map tile proxy.

The Leaflet maps used to call the public tile hosts straight from the browser.
Several networks, CDNs and corporate proxies answer those requests with
HTTP 403 ("access blocked"), which leaves the maps blank or full of provider
error tiles.

Serving tiles through Django fixes that because:

  * the request carries an identifying User-Agent, which every tile provider
    asks for and which most 403 rules look for,
  * a 403/5xx from the first provider falls through to the next one,
  * the browser only ever talks to our own origin, so client-side blocks on
    the tile hosts no longer matter,
  * every tile is written to an on-disk cache the first time it is seen, so
    the upstream providers see a tiny fraction of the requests a direct
    browser-to-provider setup would generate (this is also what keeps us
    inside the OSM/OpenTopoMap usage policies).

Two upstream facts drive the implementation:

  * the public hosts drop connections when a map load fires ~20 tiles at once
    (measured: 4/24 concurrent requests died with ConnectionError), so
    upstream fetches are serialised behind a small semaphore and retried,
  * if every provider still fails we answer with a neutral placeholder tile
    instead of an error, because an error response is what pushes the browser
    into requesting the blocked third-party URLs directly.

OpenStreetMap's own tile servers are volunteer funded and their usage policy
(https://operations.osmfoundation.org/policies/tiles/) forbids heavy or
"unintentionally heavy client" traffic, which is exactly what this proxy
looks like from their side — they answer with HTTP 403 "Access blocked"
tiles, so OSM and OpenTopoMap are deliberately last on the fallback list.
Esri's public basemaps (no key, attribution required, free for non-commercial
use) serve the maps. For a production deployment put a real contact address in
TILE_PROVIDER_CONTACT and point the TILE_PROVIDER_*_URL environment variables
at a keyed provider (MapTiler, Thunderforest, Stadia, Protomaps, ...) —
remember to add that provider's credit to the attribution strings in
static/dashboard/js/map-tiles.js.

Caching, in order of use: TILE_CACHE_DIR on disk (shared by every worker and
survives restarts), then Django's cache backend, then the browser cache. The
directory is the one thing worth cleaning up occasionally; point
TILE_CACHE_DIR somewhere with a few GB and delete it if it ever fills up.
"""

import errno
import logging
import os
import random
import threading
import time

import requests
from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.http import HttpResponse, HttpResponseNotFound
from django.views.decorators.http import require_GET

logger = logging.getLogger(__name__)

# Upstream providers per map variant, in fallback order. The first entry is
# the primary source; the rest are only tried when a provider fails.
#
# OpenStreetMap and OpenTopoMap are NOT in these chains on purpose: both are
# volunteer-run with hard usage policies that 403-block this app's traffic
# profile (a server proxying tiles for every user). Esri's public basemaps
# cover all three variants without a key.
_DEFAULT_PROVIDERS = {
    'map': [
        {
            'name': 'EsriStreet',
            'url': 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}',
        },
    ],
    'terrain': [
        {
            'name': 'EsriTopo',
            'url': 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Topo_Map/MapServer/tile/{z}/{y}/{x}',
        },
    ],
    'satellite': [
        {
            'name': 'EsriImagery',
            'url': 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
        },
        {
            'name': 'EsriShadedRelief',
            'url': 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Shaded_Relief/MapServer/tile/{z}/{y}/{x}',
        },
    ],
}


def _configured_provider(variant):
    """Optional keyed provider from the environment, e.g.
    TILE_PROVIDER_MAP_URL=https://api.maptiler.com/maps/streets/256/{z}/{x}/{y}.png?key=...{r}
    """
    url = os.getenv('TILE_PROVIDER_%s_URL' % variant.upper(), '').strip()
    if not url:
        return None
    return {
        'name': os.getenv('TILE_PROVIDER_%s_NAME' % variant.upper(), 'Configured'),
        'url': url,
    }


def _build_providers():
    providers = {}
    for variant, chain in _DEFAULT_PROVIDERS.items():
        configured = _configured_provider(variant)
        providers[variant] = ([configured] if configured else []) + chain
    return providers


TILE_PROVIDERS = _build_providers()

TILE_USER_AGENT = 'ABC-Dry-Basin/1.0 (agricultural drought monitoring dashboard; contact: %s)' % (
    os.getenv('TILE_PROVIDER_CONTACT', 'set-TILE_PROVIDER_CONTACT@example.org')
)
TILE_TIMEOUT = 6          # seconds per upstream attempt
TILE_RETRIES = 2          # extra attempts per provider (dropped connections)
TILE_RETRY_DELAY = 0.3    # base seconds between attempts
TILE_CACHE_SECONDS = 86400  # 1 day: basemap tiles are stable for a given z/x/y
TILE_FAILURE_CACHE_SECONDS = 5   # remember "everything failed" very briefly
TILE_PLACEHOLDER_CACHE_SECONDS = 5
MAX_ZOOM = 19
# A map load asks for ~20 tiles at once. Measured against the public hosts:
# 8 parallel requests is the sweet spot (4% failures, ~12s for 24 tiles),
# while 12+ starts losing 25% of them, so the fetchers stay queued behind this.
MAX_UPSTREAM_CONCURRENCY = max(1, int(os.getenv('TILE_UPSTREAM_CONCURRENCY', '8')))
_upstream_slots = threading.BoundedSemaphore(MAX_UPSTREAM_CONCURRENCY)

TILE_CACHE_DIR = os.path.abspath(
    os.getenv('TILE_CACHE_DIR') or os.path.join(getattr(settings, 'BASE_DIR', '.'), 'tilecache'))
TILE_CACHE_MAX_FILES = 300000  # soft cap: stop writing new files instead of filling the disk
_placeholder_bytes = None


class _ProviderBreaker:
    """Give a struggling provider a short breather.

    The public hosts do not fail fast when they start throttling, they stall,
    so every request would otherwise burn its full timeout. After a few failed
    fetches in a row the provider is skipped for a moment and the chain moves
    on to the next one instead of waiting on it.
    """

    def __init__(self, threshold=3, cooldown=45):
        self.threshold = threshold
        self.cooldown = cooldown
        self._lock = threading.Lock()
        self._state = {}

    def allows(self, name):
        with self._lock:
            entry = self._state.get(name)
            if not entry:
                return True
            if entry[1] > time.time():
                return False
            del self._state[name]  # cooldown over: clean slate
            return True

    def succeeded(self, name):
        with self._lock:
            self._state.pop(name, None)

    def failed(self, name):
        with self._lock:
            fails = self._state.get(name, (0, 0.0))[0] + 1
            if fails >= self.threshold:
                self._state[name] = (0, time.time() + self.cooldown)
                logger.warning('provider %s skipped for %ds after repeated failures',
                               name, self.cooldown)
            else:
                self._state[name] = (fails, 0.0)


_breaker = _ProviderBreaker()


def _tile_extent_ok(z, x, y):
    """Reject coordinates outside the tile pyramid instead of proxying them."""
    if not (0 <= z <= MAX_ZOOM):
        return False
    limit = 2 ** z
    return 0 <= x < limit and 0 <= y < limit


def _placeholder_tile():
    """Neutral 256x256 tile, so a provider outage never shows an error image."""
    global _placeholder_bytes
    if _placeholder_bytes is None:
        path = os.path.join(getattr(settings, 'BASE_DIR', '.'), 'static', 'dashboard',
                            'img', 'tile-placeholder.png')
        try:
            with open(path, 'rb') as handle:
                _placeholder_bytes = handle.read()
        except OSError:
            logger.warning('tile placeholder missing at %s', path)
            _placeholder_bytes = b''
    return _placeholder_bytes


def _disk_path(variant, provider_name, z, x, y, content_type):
    ext = 'jpg' if 'jpeg' in content_type else 'png'
    return os.path.join(TILE_CACHE_DIR, variant, provider_name, str(z), str(x), '%s.%s' % (y, ext))


def _disk_read(variant, provider_name, z, x, y):
    """Return (content_type, data) for a cached tile, or None."""
    for ext, content_type in (('jpg', 'image/jpeg'), ('png', 'image/png')):
        path = os.path.join(TILE_CACHE_DIR, variant, provider_name, str(z), str(x),
                            '%s.%s' % (y, ext))
        try:
            with open(path, 'rb') as handle:
                data = handle.read()
        except OSError as exc:
            if exc.errno not in (errno.ENOENT, errno.EACCES):
                logger.warning('tile cache read failed for %s: %s', path, exc)
            continue
        if data:
            return content_type, data
    return None


def _disk_write(variant, provider_name, z, x, y, content_type, data):
    """Best effort: a full or read-only disk must never break the map."""
    path = _disk_path(variant, provider_name, z, x, y, content_type)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        # Unique temp name + atomic replace: parallel workers never clash.
        tmp = '%s.%d.%d.tmp' % (path, os.getpid(), threading.get_ident())
        with open(tmp, 'wb') as handle:
            handle.write(data)
        os.replace(tmp, path)
    except OSError as exc:
        logger.warning('tile cache write failed for %s: %s', path, exc)


def _fetch_tile(url, provider_name, z, x, y):
    """GET one upstream tile, retrying on dropped connections and 5xx.

    Returns a (content_type, payload) tuple, or None when the provider cannot
    serve this tile. The semaphore plus the retry is what keeps a map load's
    burst of parallel requests from tripping the providers' connection limits.
    """
    for attempt in range(TILE_RETRIES + 1):
        try:
            with _upstream_slots:
                response = requests.get(
                    url,
                    headers={'User-Agent': TILE_USER_AGENT,
                             'Accept': 'image/png,image/jpeg,*/*'},
                    timeout=TILE_TIMEOUT,
                )
        except requests.RequestException as exc:
            logger.warning('tile %s/%s/%s via %s failed: %s', z, x, y, provider_name, exc)
            if attempt < TILE_RETRIES:
                time.sleep(TILE_RETRY_DELAY * (2 ** attempt) * (0.7 + random.random() * 0.6))
                continue
            return None

        content_type = (response.headers.get('Content-Type') or '').lower()
        if response.status_code == 200 and content_type.startswith('image/'):
            return content_type, response.content

        logger.warning('tile %s/%s/%s via %s answered HTTP %s',
                       z, x, y, provider_name, response.status_code)
        # 4xx means this provider will not serve the tile (missing, blocked or
        # out of coverage): retrying is pointless, move on to the next one.
        if response.status_code < 500 or attempt == TILE_RETRIES:
            return None
        time.sleep(TILE_RETRY_DELAY * (2 ** attempt))
    return None


@require_GET
@transaction.non_atomic_requests
def map_tile_proxy(request, z, x, y):
    """GET /api/tiles/<z>/<x>/<y>.png?layer=map|terrain|satellite

    non_atomic_requests matters here: this project runs with
    ATOMIC_REQUESTS=True, which opens a database connection for *every* view.
    A single map load asks for ~20 tiles in parallel, so without this the tile
    endpoint alone could exhaust the connection pool ("sorry, too many clients
    already") and answer 500 while the maps look broken. Tiles need no
    database at all.
    """
    variant = request.GET.get('layer', 'map')
    if variant not in TILE_PROVIDERS:
        variant = 'map'

    if not _tile_extent_ok(z, x, y):
        return HttpResponseNotFound('tile out of range')

    cache_key = 'maptile:%s:%d:%d:%d' % (variant, z, x, y)
    client_headers = {'Cache-Control': 'public, max-age=%d' % TILE_CACHE_SECONDS}

    # 1. on-disk cache: shared by every worker and every restart
    for provider in TILE_PROVIDERS[variant]:
        hit = _disk_read(variant, provider['name'], z, x, y)
        if hit is not None:
            return HttpResponse(hit[1], content_type=hit[0],
                                headers=dict(client_headers,
                                             **{'X-Tile-Provider': provider['name']}))

    # 2. Django cache backend
    cached = cache.get(cache_key)
    if cached is not None:
        if cached != 'fail':
            return HttpResponse(cached['data'], content_type=cached['type'],
                                headers=dict(client_headers,
                                             **{'X-Tile-Provider': cached['provider']}))
    else:
        # 3. upstream, provider by provider
        for provider in TILE_PROVIDERS[variant]:
            if not _breaker.allows(provider['name']):
                continue
            # r='' keeps retina placeholders ({r}) in configured URLs working.
            url = provider['url'].format(z=z, x=x, y=y, r='')
            result = _fetch_tile(url, provider['name'], z, x, y)
            if result is None:
                _breaker.failed(provider['name'])
                continue
            _breaker.succeeded(provider['name'])
            content_type, data = result
            cache.set(cache_key, {'data': data, 'type': content_type,
                                  'provider': provider['name']}, TILE_CACHE_SECONDS)
            _disk_write(variant, provider['name'], z, x, y, content_type, data)
            return HttpResponse(data, content_type=content_type,
                                headers=dict(client_headers,
                                             **{'X-Tile-Provider': provider['name']}))

        cache.set(cache_key, 'fail', TILE_FAILURE_CACHE_SECONDS)

    # Every provider failed. A neutral tile keeps the map usable; an error
    # response is what used to push the browser into requesting the blocked
    # third-party tile hosts directly (the "403 ERROR" tiles).
    data = _placeholder_tile()
    return HttpResponse(data, content_type='image/png',
                        headers={'Cache-Control': 'public, max-age=%d' % TILE_PLACEHOLDER_CACHE_SECONDS,
                                 'X-Tile-Provider': 'placeholder'})
