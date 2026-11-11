/* Satellite view of the Ichkeul catchment for the public pages (landing, login).
 *
 * Tiles come through the Django proxy and the outline from static, so the page
 * stays same-origin. The container carries the GeoJSON URL in data-basin-url.
 * opts: { interactive: bool (zoom/drag, default true), padding: px }
 */
(function (global) {
    "use strict";

    function initBasinMap(el, opts) {
        opts = opts || {};
        if (!el || typeof global.L === "undefined") {
            return null;
        }
        const L = global.L;
        const interactive = opts.interactive !== false;
        const map = L.map(el, {
            center: [37.06, 9.55],
            zoom: 10,
            minZoom: 8,
            maxZoom: 15,
            scrollWheelZoom: false,
            zoomControl: false,
            attributionControl: false,
            dragging: interactive,
            doubleClickZoom: interactive,
            touchZoom: interactive,
            boxZoom: interactive,
            keyboard: interactive,
            // Occluded/background windows never advance Leaflet's rAF tile fade,
            // which leaves the basemap at opacity 0 (blank map).
            fadeAnimation: false
        });
        if (interactive) {
            L.control.zoom({ position: "bottomright" }).addTo(map);
        }

        const tiles = global.MapTiles
            ? global.MapTiles.createTileLayer(L, map, { variant: "satellite", maxZoom: 19 })
            : L.tileLayer("/api/tiles/{z}/{x}/{y}.png?layer=satellite", { maxZoom: 19 });
        tiles.addTo(map);

        fetch(el.dataset.basinUrl)
            .then((response) => {
                if (!response.ok) {
                    throw new Error("HTTP " + response.status);
                }
                return response.json();
            })
            .then((data) => {
                const byKind = (kind) => ({
                    type: "FeatureCollection",
                    features: data.features.filter((f) => f.properties.kind === kind)
                });
                L.geoJSON(byKind("section"), {
                    interactive: false,
                    style: { color: "#ffffff", weight: 0.8, opacity: 0.6, fill: false }
                }).addTo(map);
                L.geoJSON(byKind("outline"), {
                    interactive: false,
                    style: { color: "#0b1a22", weight: 5, opacity: 0.75, fillColor: "#ffffff", fillOpacity: 0.05 }
                }).addTo(map);
                const outline = L.geoJSON(byKind("outline"), {
                    interactive: false,
                    style: { color: "#ffffff", weight: 2, fill: false }
                }).addTo(map);
                map.fitBounds(outline.getBounds(), { padding: [opts.padding || 32, opts.padding || 32] });
            })
            .catch((error) => console.error("Ichkeul basin outline failed to load:", error));

        global.addEventListener("resize", () => map.invalidateSize());
        return map;
    }

    global.BasinMap = { init: initBasinMap };
})(window);
