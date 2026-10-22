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

    // Leaflet is required for everything map related. If it is unavailable,
    // say so in the panel instead of leaving a silent blank rectangle.
    if (typeof window.L === "undefined") {
        const container = document.getElementById("country-map");
        if (container) {
            container.innerHTML =
                '<div class="flex h-full w-full items-center justify-center p-6 text-center text-sm text-on-surface-variant">' +
                (tr("map_unavailable") || "Map could not be loaded. Please reload the page.") +
                "</div>";
        }
        return;
    }

    const tunisiaView = regionConfig.tunisia || { center: [37.13, 9.67], zoom: 8 };
    const map = L.map("country-map", { scrollWheelZoom: true, zoomControl: true }).setView(tunisiaView.center, tunisiaView.zoom);
    if (!map.getPane("stationPane")) {
        map.createPane("stationPane");
        map.getPane("stationPane").style.zIndex = "650";
    }
    // Tiles go through the Django proxy (/api/tiles/<z>/<x>/<y>.png), which
    // serves cached Esri basemaps from disk. map-tiles.js keeps asking the
    // proxy until it answers again, and both branches below are same-origin so
    // the browser never requests a third-party tile host.
    const tileLayer = window.MapTiles
        ? window.MapTiles.createTileLayer(L, map, {
              variant: "map",
              maxZoom: 19,
              onSourceChange: (state) => {
                  const notice = document.getElementById("map-tile-warning");
                  if (!notice) {
                      return;
                  }
                  if (state === "retrying") {
                      notice.classList.remove("hidden");
                  } else {
                      notice.classList.add("hidden");
                  }
              }
          })
        : L.tileLayer("/api/tiles/{z}/{x}/{y}.png?layer=map", {
              maxZoom: 19,
              attribution: '&copy; Esri, Maxar, Earthstar Geographics'
          });

    tileLayer.addTo(map);

    // Re-measure once layout settles (Tailwind CDN/web fonts load asynchronously)
    // and on window resize, so tiles always cover the container.
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
        const initialRegion = getSelectedRegionKey();
        updateMapForRegion(initialRegion);
        updateLakeOptions(initialRegion);
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

    // ── Sensor Network ────────────────────────────────────────────────
    const sensorLayer = new L.FeatureGroup();
    map.addLayer(sensorLayer);
    window._dashboardMap = map; // expose for inline script

    const TYPE_COLORS = {
        aws: "#0ea5e9",
        soil: "#22c55e",
        water: "#a855f7",
        custom: "#f59e0b",
    };

    const TYPE_LABELS = {
        aws: "Weather Station",
        soil: "Soil Moisture",
        water: "Water Level",
        custom: "Custom",
    };

    const TYPE_ICONS = {
        aws: "sensors",
        soil: "grass",
        water: "water_drop",
        custom: "sensors",
    };

    const getSensorColor = (type) => TYPE_COLORS[type] || TYPE_COLORS.custom;
    const getSensorIcon = (type) => TYPE_ICONS[type] || "sensors";

    const addSensorPin = (sensor) => {
        const color = getSensorColor(sensor.sensor_type);
        const iconName = getSensorIcon(sensor.sensor_type);
        const typeLabel = TYPE_LABELS[sensor.sensor_type] || sensor.sensor_type;
        const lat = Number(sensor.latitude);
        const lon = Number(sensor.longitude);
        if (isNaN(lat) || isNaN(lon)) return;
        const latlng = L.latLng(lat, lon);

        // Coverage circle
        const radiusKm = Number(sensor.coverage_radius_km) || 10;
        const circle = L.circle(latlng, {
            radius: radiusKm * 1000,
            color: color,
            weight: 1.5,
            opacity: 0.45,
            fillColor: color,
            fillOpacity: 0.08,
            className: "sensor-circle",
        });
        sensorLayer.addLayer(circle);

        // Station-style icon matching analysis
        const iconHtml = `
            <div class="station-marker-container">
                <span class="station-radar-ripple" style="border-color:${color};"></span>
                <div class="station-marker-badge" style="background:${color};" title="${sensor.name || typeLabel}">
                    <span class="material-symbols-outlined" style="font-size:13px; line-height:1;">${iconName}</span>
                </div>
            </div>
        `;

        const sensorIcon = L.divIcon({
            html: iconHtml,
            className: "custom-station-icon",
            iconSize: [26, 26],
            iconAnchor: [13, 13],
            popupAnchor: [0, -15],
        });

        const popupHtml = `
            <div style="min-width:245px; font-family:Inter,sans-serif; color:#0f172a;" class="p-1.5">
                <div class="flex items-center justify-between pb-2 mb-2 border-b border-slate-200">
                    <div>
                        <div class="text-[10px] uppercase font-bold tracking-wider text-slate-500 flex items-center gap-1">
                            <span class="w-1.5 h-1.5 rounded-full" style="background:${color}"></span>
                            ${typeLabel}
                        </div>
                        <div class="font-bold text-sm text-slate-900">${sensor.name}</div>
                    </div>
                    <span class="px-2 py-0.5 rounded text-[11px] font-bold" style="background:${color}22; color:${color};">
                        Active
                    </span>
                </div>
                <div class="space-y-1.5 text-xs">
                    <div class="flex justify-between py-0.5 border-b border-slate-100">
                        <span class="text-slate-500 font-medium">📍 Coordinates:</span>
                        <span class="font-mono font-bold text-slate-800">${lat.toFixed(4)}°N, ${lon.toFixed(4)}°E</span>
                    </div>
                    <div class="flex justify-between py-0.5 border-b border-slate-100">
                        <span class="text-slate-500 font-medium">📡 Coverage Radius:</span>
                        <span class="font-mono font-bold text-slate-800">${radiusKm} km</span>
                    </div>
                    ${sensor.region_name ? `
                    <div class="flex justify-between py-0.5 border-b border-slate-100">
                        <span class="text-slate-500 font-medium">🗺️ Region:</span>
                        <span class="font-bold text-slate-800">${sensor.region_name}</span>
                    </div>` : ''}
                    ${sensor.description ? `
                    <div class="pt-1 text-[11px] text-slate-600 italic">
                        "${sensor.description}"
                    </div>` : ''}
                </div>
            </div>
        `;

        const tooltipHtml = `
            <div style="font-family:Inter,sans-serif;">
                <div style="display:flex; align-items:center; gap:5px; margin-bottom:2px;">
                    <span style="display:inline-block; width:6px; height:6px; border-radius:50%; background:${color};"></span>
                    <b style="font-size:11px; color:#f8fafc;">${sensor.name}</b>
                </div>
                <div style="font-family:monospace; font-size:10px; color:#94a3b8;">${lat.toFixed(4)}°N, ${lon.toFixed(4)}°E</div>
                <div style="font-size:10px; margin-top:2px; font-weight:600; color:${color};">${typeLabel} &bull; ${radiusKm} km</div>
            </div>
        `;

        const marker = L.marker(latlng, { icon: sensorIcon, pane: "stationPane" })
            .bindTooltip(tooltipHtml, {
                direction: "top",
                offset: [0, -15],
                className: "station-tooltip-smooth",
                opacity: 0.95
            })
            .bindPopup(popupHtml, { maxWidth: 300 });

        sensorLayer.addLayer(marker);
    };

    const updateSensorCounts = (sensors) => {
        let counts = { aws: 0, soil: 0, water: 0, custom: 0 };
        sensors.forEach(function(s) {
            if (counts[s.sensor_type] !== undefined) counts[s.sensor_type]++;
        });
        const setText = (id, val) => {
            const el = document.getElementById(id);
            if (el) el.textContent = val;
        };
        setText("sensor-count-aws", counts.aws);
        setText("sensor-count-soil", counts.soil);
        setText("sensor-count-water", counts.water);
        setText("sensor-count-custom", counts.custom);
        const total = counts.aws + counts.soil + counts.water + counts.custom;
        const badge = document.getElementById("sensor-count-badge");
        if (badge) badge.textContent = total;
    };

    const fetchSensors = async () => {
        try {
            const resp = await fetch("/api/sensors/");
            if (!resp.ok) return;
            const data = await resp.json();
            window._sensorData = data.sensors || [];
            sensorLayer.clearLayers();
            window._sensorData.forEach(addSensorPin);
            updateSensorCounts(window._sensorData);
            // Re-render sensor list if open
            if (window._sensorListOpen && typeof renderSensorList === 'function') {
                renderSensorList(window._sensorData);
            }
        } catch (e) {
            // non-critical
        }
    };

    // Handle "Pick from Map" — fill coordinates and reopen modal
    map.on("click", (e) => {
        if (window._sensorPickCallback) {
            window._sensorPickCallback = false;
            map.getContainer().style.cursor = "";
            openSensorModal(e.latlng.lat, e.latlng.lng);
        }
    });

    // Expose to global scope so inline script can call these
    window.addSensorPinToMap = (sensor) => {
        addSensorPin(sensor);
    };
    window.refreshSensorList = () => {
        fetchSensors();
    };

    // Load existing sensors on init
    fetchSensors();

    // ── Station-originated Heatmap on country-map ──
    const stationsJson = readJsonScript("stations-json", window._dashboardStations || []);
    const defaultStations = [
        {
            label: "Station Humide Inférieure",
            lat: 37.1265,
            lon: 9.6842,
            temp_c: 24.2,
            rain_mm: 18.5,
            humidity: 68,
            spei: -0.42,
            risk_score: 48,
            date: "2024-10-15"
        },
        {
            label: "Station Sub-Humide",
            lat: 37.1680,
            lon: 9.6420,
            temp_c: 26.8,
            rain_mm: 8.2,
            humidity: 54,
            spei: -1.15,
            risk_score: 72,
            date: "2024-10-15"
        }
    ];
    const stations = (stationsJson && stationsJson.length) ? stationsJson : defaultStations;
    let heatLayer = null;
    const stationHeatmapGroup = L.featureGroup();

    const renderStationHeatmap = () => {
        if (!stations || !stations.length) {
            return;
        }

        // Generate heatmap if leaflet-heat is present
        if (typeof L.heatLayer !== "undefined") {
            const heatPoints = [];
            stations.forEach((st) => {
                const stRisk = (st.risk_score !== undefined && st.risk_score !== null) ? st.risk_score : 55;
                const coreIntensity = Math.max(0.20, Math.min(1.0, stRisk / 100));

                const rings = [
                    { r: 0.000, count: 1, mult: 1.0 },
                    { r: 0.007, count: 6, mult: 0.95 },
                    { r: 0.015, count: 10, mult: 0.88 },
                    { r: 0.026, count: 14, mult: 0.78 },
                    { r: 0.040, count: 18, mult: 0.65 },
                    { r: 0.058, count: 22, mult: 0.50 },
                    { r: 0.078, count: 26, mult: 0.35 },
                    { r: 0.105, count: 30, mult: 0.22 },
                    { r: 0.135, count: 32, mult: 0.12 },
                ];

                rings.forEach((ring) => {
                    if (ring.r === 0) {
                        heatPoints.push([st.lat, st.lon, coreIntensity]);
                    } else {
                        for (let i = 0; i < ring.count; i++) {
                            const angle = (i / ring.count) * Math.PI * 2;
                            const pLat = st.lat + Math.sin(angle) * ring.r * 0.82;
                            const pLon = st.lon + Math.cos(angle) * ring.r;
                            heatPoints.push([pLat, pLon, Math.max(0.04, coreIntensity * ring.mult)]);
                        }
                    }
                });
            });

            if (stations.length >= 2) {
                const s1 = stations[0];
                const s2 = stations[1];
                const r1 = (s1.risk_score || 55) / 100;
                const r2 = (s2.risk_score || 55) / 100;

                const minLat = Math.min(s1.lat, s2.lat) - 0.08;
                const maxLat = Math.max(s1.lat, s2.lat) + 0.08;
                const minLon = Math.min(s1.lon, s2.lon) - 0.08;
                const maxLon = Math.max(s1.lon, s2.lon) + 0.08;

                const gridSteps = 26;
                const latDelta = (maxLat - minLat) / gridSteps;
                const lonDelta = (maxLon - minLon) / gridSteps;

                for (let i = 0; i <= gridSteps; i++) {
                    const gLat = minLat + i * latDelta;
                    for (let j = 0; j <= gridSteps; j++) {
                        const gLon = minLon + j * lonDelta;
                        const d1 = Math.hypot((gLat - s1.lat) * 1.15, gLon - s1.lon);
                        const d2 = Math.hypot((gLat - s2.lat) * 1.15, gLon - s2.lon);

                        const w1 = 1 / (Math.pow(d1, 2) + 0.0008);
                        const w2 = 1 / (Math.pow(d2, 2) + 0.0008);
                        const interpRisk = (w1 * r1 + w2 * r2) / (w1 + w2);

                        const minDist = Math.min(d1, d2);
                        if (minDist < 0.22) {
                            const falloff = Math.exp(-Math.pow(minDist / 0.12, 2));
                            const val = interpRisk * (0.35 + 0.65 * falloff);
                            heatPoints.push([gLat, gLon, Math.max(0.05, Math.min(1.0, val))]);
                        }
                    }
                }
            }

            if (heatLayer) {
                map.removeLayer(heatLayer);
            }

            heatLayer = L.heatLayer(heatPoints, {
                radius: 52,
                blur: 38,
                maxZoom: 14,
                minOpacity: 0.25,
                gradient: {
                    0.00: "#10b981",
                    0.25: "#10b981",
                    0.26: "#eab308",
                    0.50: "#eab308",
                    0.51: "#f97316",
                    0.75: "#f97316",
                    0.76: "#ef4444",
                    1.00: "#991b1b",
                },
            });
            heatLayer.addTo(map);
        }

        stationHeatmapGroup.clearLayers();
        stations.forEach((st) => {
            const riskVal = (st.risk_score !== undefined && st.risk_score !== null) ? st.risk_score : 55;
            let badgeColor = "#10b981";
            let badgeBg = "rgba(16, 185, 129, 0.2)";
            if (riskVal >= 75) { badgeColor = "#ef4444"; badgeBg = "rgba(239, 68, 68, 0.25)"; }
            else if (riskVal >= 50) { badgeColor = "#f97316"; badgeBg = "rgba(249, 115, 22, 0.25)"; }
            else if (riskVal >= 25) { badgeColor = "#eab308"; badgeBg = "rgba(234, 179, 8, 0.25)"; }

            const iconHtml = `
                <div class="station-marker-container">
                    <span class="station-radar-ripple" style="border-color:${badgeColor};"></span>
                    <div class="station-marker-badge" style="background:${badgeColor};" title="${st.label}">
                        <span class="material-symbols-outlined" style="font-size:13px; line-height:1;">sensors</span>
                    </div>
                </div>
            `;
            const stIcon = L.divIcon({
                html: iconHtml,
                className: "custom-station-icon",
                iconSize: [26, 26],
                iconAnchor: [13, 13],
                popupAnchor: [0, -15],
            });

            const popupContent = `
                <div style="min-width:245px; font-family:Inter,sans-serif; color:#0f172a;" class="p-1.5">
                    <div class="flex items-center justify-between pb-2 mb-2 border-b border-slate-200">
                        <div>
                            <div class="text-[10px] uppercase font-bold tracking-wider text-slate-500 flex items-center gap-1">
                                <span class="w-1.5 h-1.5 rounded-full" style="background:${badgeColor}"></span>
                                Database Station Origin
                            </div>
                            <div class="font-bold text-sm text-slate-900">${st.label}</div>
                        </div>
                        <span class="px-2 py-0.5 rounded text-[11px] font-bold" style="background:${badgeBg}; color:${badgeColor};">
                            Risk ${riskVal}
                        </span>
                    </div>
                    <div class="space-y-1.5 text-xs">
                        <div class="flex justify-between py-0.5 border-b border-slate-100">
                            <span class="text-slate-500 font-medium">📍 Coordinates:</span>
                            <span class="font-mono font-bold text-slate-800">${Number(st.lat).toFixed(4)}°N, ${Number(st.lon).toFixed(4)}°E</span>
                        </div>
                        ${st.rain_mm !== null && st.rain_mm !== undefined ? `
                        <div class="flex justify-between py-0.5">
                            <span class="text-slate-500 font-medium">🌧️ Precipitation:</span>
                            <span class="font-mono font-bold text-slate-800">${Number(st.rain_mm).toFixed(1)} mm</span>
                        </div>` : ''}
                        ${st.temp_c !== null && st.temp_c !== undefined ? `
                        <div class="flex justify-between py-0.5">
                            <span class="text-slate-500 font-medium">🌡️ Temperature:</span>
                            <span class="font-mono font-bold text-slate-800">${Number(st.temp_c).toFixed(1)} °C</span>
                        </div>` : ''}
                        ${st.humidity !== null && st.humidity !== undefined ? `
                        <div class="flex justify-between py-0.5">
                            <span class="text-slate-500 font-medium">💧 Humidity:</span>
                            <span class="font-mono font-bold text-slate-800">${st.humidity}%</span>
                        </div>` : ''}
                        ${st.spei !== null && st.spei !== undefined ? `
                        <div class="flex justify-between py-0.5">
                            <span class="text-slate-500 font-medium">📊 SPEI-3:</span>
                            <span class="font-mono font-bold text-slate-800">${Number(st.spei).toFixed(2)}</span>
                        </div>` : ''}
                        ${st.date ? `
                        <div class="flex justify-between pt-1 border-t border-slate-100 text-[10px] text-slate-400">
                            <span>Database Reading:</span>
                            <span class="font-mono">${st.date}</span>
                        </div>` : ''}
                    </div>
                </div>
            `;

            const tooltipHtml = `
                <div style="font-family:Inter,sans-serif;">
                    <div style="display:flex; align-items:center; gap:5px; margin-bottom:2px;">
                        <span style="display:inline-block; width:6px; height:6px; border-radius:50%; background:${badgeColor};"></span>
                        <b style="font-size:11px; color:#f8fafc;">${st.label}</b>
                    </div>
                    <div style="font-family:monospace; font-size:10px; color:#94a3b8;">${Number(st.lat).toFixed(4)}°N, ${Number(st.lon).toFixed(4)}°E</div>
                    <div style="font-size:10px; margin-top:2px; font-weight:600; color:${badgeColor};">Heat Origin &bull; Risk: ${riskVal}</div>
                </div>
            `;

            const marker = L.marker([st.lat, st.lon], { icon: stIcon, pane: "stationPane" })
                .bindTooltip(tooltipHtml, {
                    direction: "top",
                    offset: [0, -15],
                    className: "station-tooltip-smooth",
                    opacity: 0.95
                })
                .bindPopup(popupContent, { maxWidth: 300 });
            stationHeatmapGroup.addLayer(marker);
        });

        if (stations.length >= 2) {
            const baseline = L.polyline([[stations[0].lat, stations[0].lon], [stations[1].lat, stations[1].lon]], {
                color: "#0284c7",
                weight: 2,
                dashArray: "6, 8",
                opacity: 0.85,
                pane: "stationPane"
            }).bindTooltip("Monitoring Baseline · Heat Origin", { direction: "center" });
            stationHeatmapGroup.addLayer(baseline);
        }
        stationHeatmapGroup.addTo(map);
    };

    renderStationHeatmap();

    const heatToggle = document.getElementById("toggle-water-heatmap");
    if (heatToggle) {
        heatToggle.addEventListener("change", (e) => {
            if (e.target.checked) {
                if (heatLayer) map.addLayer(heatLayer);
                map.addLayer(stationHeatmapGroup);
            } else {
                if (heatLayer) map.removeLayer(heatLayer);
                map.removeLayer(stationHeatmapGroup);
            }
        });
    }

    activateSelectMode();
    scheduleLiveMetricsRefresh();
});
