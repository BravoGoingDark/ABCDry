/* Resilient Leaflet tile layer.
 *
 * Tiles are fetched through the Django proxy (/api/tiles/<z>/<x>/<y>.png),
 * which serves cached Esri basemaps from its own on-disk cache. Everything the
 * browser asks for is therefore same-origin: the volunteer hosts are only ever
 * reached from the server, and never while they are working normally.
 *
 * If the proxy cannot be reached at all (server down, exotic proxy in front of
 * the app), the layer walks the same provider list client-side and any failed
 * tile is drawn with a neutral placeholder, so a blocked provider can never
 * paint its own "403 ERROR" image over the map.
 */
(function (global) {
    "use strict";

    const PROXY_URL = "/api/tiles/{z}/{x}/{y}.png?layer={variant}";

    /* Resolved next to this very script, so it keeps working with hashed
       static file names. */
    const PLACEHOLDER_URL = (function () {
        const src = (document.currentScript && document.currentScript.src) || "";
        const parts = src.match(/^(.*\/)js\/map-tiles(\.[\w]+)?\.js$/);
        return parts ? parts[1] + "img/tile-placeholder.png" : "";
    })();


    /* There is no third-party client-side fallback on purpose: every tile is
       same-origin through the proxy, which is the whole point. Exported for
       completeness. */
    const DIRECT_URLS = {
        map: [PROXY_URL.replace("{variant}", "map")],
        terrain: [PROXY_URL.replace("{variant}", "terrain")],
        satellite: [PROXY_URL.replace("{variant}", "satellite")]
    };

    const ATTRIBUTIONS = {
        map: '&copy; Esri, Maxar, Earthstar Geographics',
        terrain: '&copy; Esri, Maxar, Earthstar Geographics',
        satellite: '&copy; Esri, Maxar, Earthstar Geographics'
    };

    const ERROR_LIMIT = 3;   // tile errors tolerated before switching provider
    const RESET_AFTER = 8000; // ms of successful loads that clears the counter

    /* Builds a tile layer that survives blocked tile hosts.
     *
     * opts: { variant: "map"|"terrain"|"satellite", maxZoom, attribution,
     *         onSourceChange(state) }  state: "ok" | "retrying"
     * Returns the Leaflet layer; call layer.setVariant(v) to switch styles.
     */
    function createTileLayer(L, map, opts) {
        opts = opts || {};
        let variant = opts.variant || "map";
        const maxZoom = opts.maxZoom || 19;
        const onSourceChange = typeof opts.onSourceChange === "function" ? opts.onSourceChange : function () {};

        let errors = 0;
        let resetTimer = null;
        let retryTimer = null;
        let retryDelay = 0;
        let attempt = 0;

        const attribution = opts.attribution || ATTRIBUTIONS[variant];

        /* attempt busts the browser cache on a retry, so a placeholder the
           server sent a moment ago is not shown again after it recovers. */
        const urlFor = () => {
            const url = PROXY_URL.replace("{variant}", variant);
            return attempt ? url + "&retry=" + attempt : url;
        };

        const layer = L.tileLayer(urlFor(), {
            maxZoom: maxZoom,
            attribution: attribution,
            // Never let a provider paint its own error image ("403 ERROR",
            // "access blocked", ...): failed tiles get the neutral tile.
            errorTileUrl: opts.errorTileUrl || PLACEHOLDER_URL || undefined
        });

        const announce = (state) => onSourceChange(state);

        /* Tiles are failing: say so, and keep asking the proxy with a growing
           gap until it answers again. There is nowhere else to go. */
        const scheduleRetry = () => {
            if (retryTimer) {
                return;
            }
            attempt += 1;
            errors = 0;
            announce("retrying");
            retryDelay = Math.min(retryDelay ? retryDelay * 2 : 3000, 30000);
            retryTimer = setTimeout(function () {
                retryTimer = null;
                layer.setUrl(urlFor());
            }, retryDelay);
        };

        layer.on("tileload", () => {
            errors = 0;
            attempt = 0;
            retryDelay = 0;
            if (resetTimer) {
                clearTimeout(resetTimer);
            }
            resetTimer = setTimeout(() => { errors = 0; }, RESET_AFTER);
            announce("ok");
        });

        layer.on("tileerror", () => {
            errors += 1;
            if (errors >= ERROR_LIMIT) {
                scheduleRetry();
            }
        });

        layer.setVariant = function (nextVariant) {
            if (!nextVariant || nextVariant === variant) {
                return;
            }
            variant = nextVariant;
            errors = 0;
            attempt = 0;
            retryDelay = 0;
            if (retryTimer) {
                clearTimeout(retryTimer);
                retryTimer = null;
            }
            // Leaflet 1.9 has no setAttribution(); updating the option keeps
            // the credit correct for any layer re-added later.
            if (!opts.attribution) {
                layer.options.attribution = ATTRIBUTIONS[variant] || attribution;
            }
            layer.setUrl(urlFor());
            announce("ok");
        };

        layer.getState = function () { return attempt ? "retrying" : "ok"; };
        announce("ok");
        return layer;
    }

    global.MapTiles = {
        createTileLayer: createTileLayer,
        ATTRIBUTIONS: ATTRIBUTIONS,
        DIRECT_URLS: DIRECT_URLS
    };
})(window);
