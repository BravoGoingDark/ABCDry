document.addEventListener("DOMContentLoaded", () => {
    const cards = document.querySelectorAll(".dashboard-card");
    const submitButton = document.querySelector("button[type='submit']");
    const regionSelector = document.getElementById("region-selector");
    const lakeSelector = document.getElementById("lake-selector");
    const mapInfo = document.getElementById("map-info");
    const drawToolBtn = document.getElementById("draw-tool-btn");
    const measureToolBtn = document.getElementById("measure-tool-btn");
    const selectToolBtn = document.getElementById("select-tool-btn");
    const pingToolBtn = document.getElementById("ping-tool-btn");
    const clearDrawingsBtn = document.getElementById("clear-drawings-btn");
    const clearRulerBtn = document.getElementById("clear-ruler-btn");
    const liveWindSpeedEl = document.getElementById("live-wind-speed");
    const liveWindGustEl = document.getElementById("live-wind-gust");
    const liveWindDirectionEl = document.getElementById("live-wind-direction");
    const liveRainfallEl = document.getElementById("live-rainfall");
    const liveRainfallDeltaEl = document.getElementById("live-rainfall-delta");
    const liveTempEl = document.getElementById("live-temperature");
    const liveHumidityEl = document.getElementById("live-humidity");

    const readJsonScript = (id, fallback) => {
        const el = document.getElementById(id);
        if (!el) {
            return fallback;
        }
        try {
            return JSON.parse(el.textContent);
        } catch (e) {
            return fallback;
        }
    };

    const i18nMap = readJsonScript("dashboard-i18n-json", {});
    const regionConfig = readJsonScript("region-map-json", {});
    const lakesByRegion = readJsonScript("lakes-by-region-json", {});
    // Turf.js is optional: without it the map and its tile layer still work;
    // only polygon area statistics are unavailable (see Draw.CREATED below).
    const hasTurf = typeof window.turf !== "undefined";

    const tr = (key, reps = {}) => {
        let s = i18nMap[key] || "";
        if (!s) {
            return "";
        }
        Object.keys(reps).forEach((k) => {
            const token = `__${String(k).toUpperCase()}__`;
            s = s.split(token).join(String(reps[k]));
        });
        return s;
    };

    // Satellite map of the Ichkeul catchment with the study shapefile borders.
    // Free navigation: wheel/pinch/double-click zoom, drag to pan, +/- control.
    const mapContainer = document.getElementById("country-map");
    if (!mapContainer) return;

    const tunisiaView = regionConfig.tunisia || { center: [37.13, 9.67], zoom: 8 };
    const ichkeulView = { center: [37.06, 9.48], zoom: 9 };
    const map = L.map("country-map", {
        center: ichkeulView.center,
        zoom: ichkeulView.zoom,
        minZoom: 5,
        maxZoom: 18,
        zoomControl: false,
        attributionControl: false,
        // Leaflet fades tiles in with requestAnimationFrame. When the window is
        // occluded or backgrounded that never runs and every tile stays at
        // opacity:0 — the map looks blank although the tiles downloaded fine.
        fadeAnimation: false,
    });

    // Expose map instance for other pages (e.g. admin farms overlay)
    window._dashboardMap = map;

    L.control.zoom({ position: "bottomright" }).addTo(map);

    // Satellite tile layer (ESRI World Imagery) via same-origin Django proxy
    const tileLayer = window.MapTiles
        ? window.MapTiles.createTileLayer(L, map, {
              variant: "satellite",
              maxZoom: 19,
          })
        : L.tileLayer("/api/tiles/{z}/{x}/{y}.png?layer=satellite", {
              maxZoom: 19,
              attribution: '',
          });

    tileLayer.addTo(map);

    // Ichkeul catchment: outline + 29 sections from the study shapefile
    const basinUrl = mapContainer.dataset.basinUrl;
    if (basinUrl) {
        fetch(basinUrl)
            .then((response) => {
                if (!response.ok) throw new Error("HTTP " + response.status);
                return response.json();
            })
            .then((data) => {
                const outline = { type: "FeatureCollection", features: data.features.filter((f) => f.properties.kind === "outline") };
                const sections = { type: "FeatureCollection", features: data.features.filter((f) => f.properties.kind === "section") };
                L.geoJSON(sections, {
                    interactive: false,
                    style: { color: "#ffffff", weight: 0.8, opacity: 0.6, fill: false }
                }).addTo(map);
                L.geoJSON(outline, {
                    interactive: false,
                    style: { color: "#0b1a22", weight: 5, opacity: 0.75, fillColor: "#ffffff", fillOpacity: 0.05 }
                }).addTo(map);
                const outlineLayer = L.geoJSON(outline, {
                    interactive: false,
                    style: { color: "#ffffff", weight: 2, fill: false }
                }).addTo(map);
                // Pages that draw their own overlay (e.g. the admin farmer lands
                // page) opt out with data-auto-fit="false" so this background fit
                // does not override their view.
                if (mapContainer.dataset.autoFit !== "false") {
                    map.fitBounds(outlineLayer.getBounds(), { padding: [36, 36] });
                }
            })
            .catch((error) => console.error("Ichkeul basin outline failed to load:", error));
    }

    // Re-measure once layout settles
    window.addEventListener("load", () => map.invalidateSize());
    window.addEventListener("resize", () => map.invalidateSize());
    window.setTimeout(() => map.invalidateSize(), 300);

    const drawnItems = new L.FeatureGroup();
    map.addLayer(drawnItems);
    let activeMode = "select";
    let measurePoints = [];
    let measureLine = null;
    let measureMarkers = [];
    let pingMarker = null;
    let pingHalo = null;
    let currentLiveCoords = tunisiaView.center;
    let liveMetricsTimer = null;

    const drawPolygonTool = new L.Draw.Polygon(map, {
        shapeOptions: {
            color: "#00677d",
            weight: 2,
        },
        showArea: true,
    });

    const setMapInfo = (text) => {
        if (mapInfo) {
            mapInfo.textContent = text;
        }
    };

    const setActiveToolButton = (activeBtn) => {
        [drawToolBtn, measureToolBtn, selectToolBtn, pingToolBtn].forEach((btn) => {
            if (!btn) {
                return;
            }
            btn.classList.remove("bg-surface-container", "text-primary");
            if (btn === activeBtn) {
                btn.classList.add("bg-surface-container", "text-primary");
            }
        });
    };

    const getSelectedRegionKey = () => {
        if (!regionSelector) {
            return "tunisia";
        }
        const selectedText = regionSelector.options[regionSelector.selectedIndex]?.textContent || "";
        const lower = selectedText.toLowerCase();
        if (lower.includes("morocco")) {
            return "morocco";
        }
        if (lower.includes("algeria")) {
            return "algeria";
        }
        return "tunisia";
    };

    const updateMapForRegion = (regionKey) => {
        const config = regionConfig[regionKey];
        if (!config) {
            return;
        }
        map.flyTo(config.center, config.zoom, { duration: 1.1 });
        setMapInfo(tr("map_centered_on", { PLACE: config.label }));
    };
    const refreshLiveMetrics = async (lat, lon) => {
        try {
            const response = await fetch(
                `/api/live-metrics/?lat=${encodeURIComponent(lat)}&lon=${encodeURIComponent(lon)}`
            );
            if (!response.ok) {
                return null;
            }
            const data = await response.json();
            if (liveWindSpeedEl) liveWindSpeedEl.textContent = data.wind_speed_kmh ?? "--";
            if (liveWindGustEl) liveWindGustEl.textContent = data.wind_gust_kmh ?? "--";
            if (liveWindDirectionEl) liveWindDirectionEl.textContent = data.wind_direction ?? "--";
            if (liveRainfallEl) liveRainfallEl.textContent = data.rainfall_mm ?? "--";
            if (liveRainfallDeltaEl) liveRainfallDeltaEl.textContent = data.rainfall_delta_percent ?? "0";
            if (liveTempEl) liveTempEl.textContent = data.temperature_c ?? "--";
            if (liveHumidityEl) liveHumidityEl.textContent = data.humidity_percent ?? "--";
            return data;
        } catch (error) {
            // Keep existing values if live API is temporarily unreachable.
            return null;
        }
    };

    const scheduleLiveMetricsRefresh = () => {
        if (liveMetricsTimer) {
            window.clearInterval(liveMetricsTimer);
        }
        refreshLiveMetrics(currentLiveCoords[0], currentLiveCoords[1]);
        liveMetricsTimer = window.setInterval(() => {
            refreshLiveMetrics(currentLiveCoords[0], currentLiveCoords[1]);
        }, 60000);
    };
    const updateLakeOptions = (regionKey) => {
        if (!lakeSelector) {
            return;
        }
        const lakes = lakesByRegion[regionKey] || [];
        lakeSelector.innerHTML = "";
        lakes.forEach((lake) => {
            const option = document.createElement("option");
            option.value = lake.key;
            option.textContent = lake.label;
            lakeSelector.appendChild(option);
        });
    };
    const flyToSelectedLake = (regionKey) => {
        if (!lakeSelector) {
            return;
        }
        const lakes = lakesByRegion[regionKey] || [];
        const selected = lakes.find((lake) => lake.key === lakeSelector.value);
        if (!selected) {
            return;
        }
        currentLiveCoords = selected.center;
        map.flyTo(selected.center, selected.zoom, { duration: 1.1 });
        setMapInfo(tr("map_centered_on", { PLACE: selected.label }));
        scheduleLiveMetricsRefresh();
    };

    const clearMeasure = () => {
        measurePoints = [];
        if (measureLine) {
            map.removeLayer(measureLine);
            measureLine = null;
        }
        measureMarkers.forEach((marker) => map.removeLayer(marker));
        measureMarkers = [];
    };

    const clearDrawings = () => {
        drawnItems.clearLayers();
        setMapInfo(tr("drawings_cleared"));
    };

    const activateSelectMode = () => {
        activeMode = "select";
        drawPolygonTool.disable();
        clearMeasure();
        setActiveToolButton(selectToolBtn);
        map.getContainer().style.cursor = "";
        setMapInfo(tr("select_mode"));
    };

    const activateDrawMode = () => {
        activeMode = "draw";
        clearMeasure();
        setActiveToolButton(drawToolBtn);
        setMapInfo(tr("draw_mode"));
        drawPolygonTool.enable();
    };

    const activateMeasureMode = () => {
        activeMode = "measure";
        drawPolygonTool.disable();
        clearMeasure();
        setActiveToolButton(measureToolBtn);
        setMapInfo(tr("measure_mode"));
    };

    const activatePingMode = () => {
        activeMode = "ping";
        drawPolygonTool.disable();
        clearMeasure();
        setActiveToolButton(pingToolBtn);
        setMapInfo(tr("ping_mode"));
    };

    cards.forEach((card) => {
        card.addEventListener("mouseenter", () => {
            card.style.transform = "translateY(-3px)";
        });
        card.addEventListener("mouseleave", () => {
            card.style.transform = "translateY(0)";
        });
    });

    const simForm = document.getElementById("simulation-form");
    const runSimulationHeaderBtn = document.getElementById("run-simulation-header-btn");
    const yearSelector = document.getElementById("year-selector");
    const hiddenRegionInput = document.getElementById("id_hidden_region");
    const hiddenYearInput = document.getElementById("id_hidden_year");

    const syncSelectorsToHiddenInputs = () => {
        if (hiddenRegionInput && regionSelector) {
            hiddenRegionInput.value = regionSelector.value;
        }
        if (hiddenYearInput && yearSelector) {
            hiddenYearInput.value = yearSelector.value;
        }
    };

    if (simForm) {
        simForm.addEventListener("submit", () => {
            syncSelectorsToHiddenInputs();
        });
    }

    if (runSimulationHeaderBtn) {
        runSimulationHeaderBtn.addEventListener("click", () => {
            syncSelectorsToHiddenInputs();
            if (simForm) {
                simForm.submit();
            }
        });
    }

    if (submitButton) {
        submitButton.addEventListener("click", () => {
            submitButton.classList.add("opacity-80");
            setTimeout(() => submitButton.classList.remove("opacity-80"), 180);
        });
    }

    if (regionSelector) {
        // The navbar on other pages links here with ?region=<pk>&lake=<key>.
        const urlParams = new URLSearchParams(window.location.search);
        const requestedRegion = urlParams.get("region");
        if (requestedRegion && Array.from(regionSelector.options).some((o) => o.value === requestedRegion)) {
            regionSelector.value = requestedRegion;
        }
        const initialRegion = getSelectedRegionKey();
        updateMapForRegion(initialRegion);
        updateLakeOptions(initialRegion);
        const requestedLake = urlParams.get("lake");
        if (lakeSelector && requestedLake && Array.from(lakeSelector.options).some((o) => o.value === requestedLake)) {
            lakeSelector.value = requestedLake;
        }
        flyToSelectedLake(initialRegion);
        regionSelector.addEventListener("change", () => {
            const selectedRegion = getSelectedRegionKey();
            updateMapForRegion(selectedRegion);
            updateLakeOptions(selectedRegion);
            flyToSelectedLake(selectedRegion);
        });
    }
    if (lakeSelector) {
        lakeSelector.addEventListener("change", () => {
            flyToSelectedLake(getSelectedRegionKey());
        });
    }

    if (drawToolBtn) {
        drawToolBtn.addEventListener("click", activateDrawMode);
    }
    if (measureToolBtn) {
        measureToolBtn.addEventListener("click", activateMeasureMode);
    }
    if (selectToolBtn) {
        selectToolBtn.addEventListener("click", activateSelectMode);
    }
    if (pingToolBtn) {
        pingToolBtn.addEventListener("click", activatePingMode);
    }
    if (clearDrawingsBtn) {
        clearDrawingsBtn.addEventListener("click", clearDrawings);
    }
    if (clearRulerBtn) {
        clearRulerBtn.addEventListener("click", () => {
            clearMeasure();
            setMapInfo(tr("ruler_cleared"));
        });
    }

    map.on(L.Draw.Event.CREATED, (event) => {
        const layer = event.layer;
        drawnItems.addLayer(layer);

        if (!hasTurf) {
            if (typeof layer.getBounds === "function") {
                const center = layer.getBounds().getCenter();
                const info = tr("polygon_center", { LAT: center.lat.toFixed(5), LNG: center.lng.toFixed(5) });
                layer.bindPopup(info, { className: "abcbasin-popup", closeButton: true }).openPopup();
                layer.on("click", () => {
                    if (activeMode === "select") {
                        layer.openPopup();
                        setMapInfo(info);
                    }
                });
                setMapInfo(info);
            }
            activateSelectMode();
            return;
        }
        const geoJson = layer.toGeoJSON();
        const areaSqMeters = turf.area(geoJson);
        const areaHectares = areaSqMeters / 10000;
        const areaKm2 = areaSqMeters / 1000000;
        const perimeterKm = turf.length(geoJson, { units: "kilometers" });
        const perimeterM = perimeterKm * 1000;
        const centroid = turf.centroid(geoJson).geometry.coordinates;
        const centerLat = centroid[1];
        const centerLng = centroid[0];
        const info = tr("polygon_line", {
            M2: areaSqMeters.toFixed(2),
            HA: areaHectares.toFixed(2),
            KM2: areaKm2.toFixed(3),
            PM: perimeterM.toFixed(2),
            LAT: centerLat.toFixed(5),
            LNG: centerLng.toFixed(5),
        });
        layer.bindPopup(info, {
            className: "abcbasin-popup",
            closeButton: true,
            autoPanPadding: [24, 24],
        }).openPopup();
        layer.on("click", () => {
            if (activeMode === "select") {
                layer.openPopup();
                setMapInfo(info);
            }
        });
        setMapInfo(info);
        activateSelectMode();
    });

    map.on("click", async (event) => {
        if (activeMode === "ping") {
            if (pingMarker) {
                map.removeLayer(pingMarker);
            }
            if (pingHalo) {
                map.removeLayer(pingHalo);
            }
            pingHalo = L.circleMarker(event.latlng, {
                radius: 16,
                color: "#0ea5e9",
                weight: 2,
                opacity: 0.55,
                fillColor: "#38bdf8",
                fillOpacity: 0.2,
            }).addTo(map);
            pingMarker = L.circleMarker(event.latlng, {
                radius: 8,
                color: "#ffffff",
                weight: 2,
                fillColor: "#0ea5e9",
                fillOpacity: 1,
            }).addTo(map);
            currentLiveCoords = [event.latlng.lat, event.latlng.lng];
            const data = await refreshLiveMetrics(event.latlng.lat, event.latlng.lng);
            if (data) {
                const info = tr("ping_line", {
                    LAT: event.latlng.lat.toFixed(5),
                    LNG: event.latlng.lng.toFixed(5),
                    WS: data.wind_speed_kmh,
                    T: data.temperature_c,
                    H: data.humidity_percent,
                    R: data.rainfall_mm,
                });
                setMapInfo(info);
            } else {
                setMapInfo(tr("ping_no_live"));
            }
            scheduleLiveMetricsRefresh();
            // Also resolve region and update charts for this location
            resolveRegionAndUpdateCharts(event.latlng.lat, event.latlng.lng);
            return;
        }

        if (activeMode !== "measure") {
            return;
        }
        measurePoints.push(event.latlng);

        if (measurePoints.length === 1) {
            const firstMarker = L.circleMarker(measurePoints[0], {
                radius: 6,
                color: "#ba1a1a",
                fillColor: "#ef4444",
                fillOpacity: 0.9,
                weight: 2,
            }).addTo(map);
            measureMarkers.push(firstMarker);
            setMapInfo(tr("first_point_done"));
            return;
        }

        if (measurePoints.length === 2) {
            if (measureLine) {
                map.removeLayer(measureLine);
            }
            measureLine = L.polyline(measurePoints, { color: "#ba1a1a", weight: 3 }).addTo(map);
            const secondMarker = L.circleMarker(measurePoints[1], {
                radius: 6,
                color: "#ba1a1a",
                fillColor: "#ef4444",
                fillOpacity: 0.9,
                weight: 2,
            }).addTo(map);
            measureMarkers.push(secondMarker);
            const distanceMeters = map.distance(measurePoints[0], measurePoints[1]);
            const distanceKm = distanceMeters / 1000;
            setMapInfo(tr("distance_line", { M: distanceMeters.toFixed(2), KM: distanceKm.toFixed(3) }));
            measurePoints = [];
        }
    });

    // ── Chart data update ─────────────────────────────────────────────
    const fallbackChartData = {
        chart_months: ['Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec', 'Jan', 'Feb', 'Mar', 'Apr', 'May'],
        climate_points_rainfall: '25,112 49,96 74,86 99,71 124,54 149,68 174,82 199,75 224,60 249,72 274,88 295,93',
        climate_points_temp: '25,89 49,82 74,70 99,64 124,58 149,54 174,60 199,65 224,72 249,77 274,83 295,88',
        climate_points_spi: '25,55 49,60 74,68 99,76 124,84 149,90 174,77 199,67 224,64 249,70 274,84 295,80',
        climate_points_ndvi: '25,102 49,98 74,90 99,82 124,70 149,64 174,58 199,61 224,66 249,72 274,78 295,82',
        drought_points_spi: '25,78 49,72 74,67 99,58 124,48 149,52 174,60 199,63 224,58 249,70 274,74 295,69',
        drought_points_spei: '25,81 49,75 74,70 99,62 124,54 149,60 174,63 199,56 224,62 249,68 274,76 295,73',
        ndvi_points: '25,98 49,93 74,84 99,74 124,59 149,48 174,43 199,46 224,54 249,60 274,68 295,74',
        climate_labels: [100, 66, 33, 0],
        drought_labels: [3, 1.5, -1.5, -3],
        ndvi_labels: [1, 0.75, 0.25, 0],
    };

    const fetchChartData = async (regionId, yearId) => {
        // The overview no longer shows the climate/drought/NDVI charts; skip
        // the request on pages that have none of their targets.
        if (!document.getElementById("climate-months") && !document.getElementById("drought-months") && !document.getElementById("ndvi-months")) {
            return;
        }
        try {
            let url = `/api/chart-data/?region_id=${encodeURIComponent(regionId)}`;
            if (yearId) url += `&year_id=${encodeURIComponent(yearId)}`;
            const response = await fetch(url);
            if (!response.ok) return;
            const data = await response.json();
            const safeData = data && typeof data === 'object' ? data : {};
            const resolved = {
                ...fallbackChartData,
                ...safeData,
                chart_months: safeData.chart_months && safeData.chart_months.length ? safeData.chart_months : fallbackChartData.chart_months,
                climate_labels: safeData.climate_labels && safeData.climate_labels.length ? safeData.climate_labels : fallbackChartData.climate_labels,
                drought_labels: safeData.drought_labels && safeData.drought_labels.length ? safeData.drought_labels : fallbackChartData.drought_labels,
                ndvi_labels: safeData.ndvi_labels && safeData.ndvi_labels.length ? safeData.ndvi_labels : fallbackChartData.ndvi_labels,
            };

            const fallbackPointsById = {
                'chart-climate-rainfall': fallbackChartData.climate_points_rainfall,
                'chart-climate-temp': fallbackChartData.climate_points_temp,
                'chart-climate-spi': fallbackChartData.climate_points_spi,
                'chart-climate-ndvi': fallbackChartData.climate_points_ndvi,
                'chart-drought-spi': fallbackChartData.drought_points_spi,
                'chart-drought-spei': fallbackChartData.drought_points_spei,
                'chart-ndvi': fallbackChartData.ndvi_points,
            };
            const setPoints = (id, pts) => {
                const el = document.getElementById(id);
                if (el) {
                    const value = pts && String(pts).trim() ? String(pts) : fallbackPointsById[id] || '';
                    el.setAttribute('points', value || '');
                }
            };
            setPoints('chart-climate-rainfall', resolved.climate_points_rainfall);
            setPoints('chart-climate-temp', resolved.climate_points_temp);
            setPoints('chart-climate-spi', resolved.climate_points_spi);
            setPoints('chart-climate-ndvi', resolved.climate_points_ndvi);
            setPoints('chart-drought-spi', resolved.drought_points_spi);
            setPoints('chart-drought-spei', resolved.drought_points_spei);
            setPoints('chart-ndvi', resolved.ndvi_points);

            const setLabels = (prefix, labels) => {
                for (let i = 0; i < 4; i++) {
                    const el = document.getElementById(prefix + '-y' + i);
                    if (el) {
                        const suffix = prefix === 'climate' ? '%' : '';
                        const value = Array.isArray(labels) && labels[i] !== undefined ? labels[i] : fallbackChartData[prefix + '_labels'][i];
                        const fmt = prefix === 'climate' ? Number(value).toFixed(0) : Number(value).toFixed(1);
                        el.textContent = fmt + suffix;
                    }
                }
            };
            setLabels('climate', resolved.climate_labels);
            setLabels('drought', resolved.drought_labels);
            setLabels('ndvi', resolved.ndvi_labels);

            const setMonths = (id, months) => {
                const el = document.getElementById(id);
                if (el) el.innerHTML = months.map(function(m) { return '<span>' + m + '</span>'; }).join('');
            };
            setMonths('climate-months', resolved.chart_months);
            setMonths('drought-months', resolved.chart_months);
            setMonths('ndvi-months', resolved.chart_months);
        } catch (e) {
            // chart update is non-critical
        }
    };

    const resolveRegionAndUpdateCharts = async (lat, lon) => {
        try {
            const resp = await fetch(`/api/resolve-region/?lat=${encodeURIComponent(lat)}&lon=${encodeURIComponent(lon)}`);
            if (!resp.ok) return;
            const region = await resp.json();
            if (region.region_id && regionSelector) {
                // Update the region selector to match
                for (let i = 0; i < regionSelector.options.length; i++) {
                    if (regionSelector.options[i].value == region.region_id) {
                        regionSelector.selectedIndex = i;
                        break;
                    }
                }
                // Update charts
                await fetchChartData(region.region_id, yearSelector ? yearSelector.value : null);
            }
        } catch (e) {
            // non-critical
        }
    };

    const getYearId = () => yearSelector ? yearSelector.value : null;

    // Region selector change → update charts
    if (regionSelector) {
        regionSelector.addEventListener('change', async function() {
            const val = regionSelector.value;
            if (val) await fetchChartData(val, getYearId());
        });
    }

    // Year selector change → update charts
    if (yearSelector) {
        yearSelector.addEventListener('change', async function() {
            const regionVal = regionSelector ? regionSelector.value : null;
            if (regionVal) await fetchChartData(regionVal, yearSelector.value);
        });
    }

    // Initial chart load: get region + year from the currently selected options
    (function initCharts() {
        if (regionSelector && regionSelector.value) {
            fetchChartData(regionSelector.value, getYearId());
        }
    })();

    activateSelectMode();
    scheduleLiveMetricsRefresh();
});
