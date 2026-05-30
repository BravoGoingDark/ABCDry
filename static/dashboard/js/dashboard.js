document.addEventListener("DOMContentLoaded", () => {
    if (typeof window.L === "undefined" || typeof window.turf === "undefined") {
        return;
    }

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

    const map = L.map("country-map").setView(regionConfig.tunisia.center, regionConfig.tunisia.zoom);
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
        maxZoom: 19,
        attribution: "&copy; OpenStreetMap contributors",
    }).addTo(map);

    const drawnItems = new L.FeatureGroup();
    map.addLayer(drawnItems);
    let activeMode = "select";
    let measurePoints = [];
    let measureLine = null;
    let measureMarkers = [];
    let pingMarker = null;
    let pingHalo = null;
    let currentLiveCoords = regionConfig.tunisia.center;
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

    activateSelectMode();
    scheduleLiveMetricsRefresh();
});
