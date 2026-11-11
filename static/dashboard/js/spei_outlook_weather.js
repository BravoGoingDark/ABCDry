/* Live 16-day temperature & rainfall forecast for the forecast page.
 *
 * Data comes from /api/weather-forecast/ (server-side proxy to Open-Meteo,
 * 30-minute cache). The initial payload is embedded by the template with
 * {{ weather|json_script:"weather-data" }} so the page renders immediately,
 * then the region selector refreshes it in place.
 */
var WEATHER = null;
(function () {
    var el = document.getElementById("weather-data");
    if (!el) return;
    try {
        WEATHER = JSON.parse(el.textContent);
    } catch (err) {
        WEATHER = null;
    }
})();

var currentTempMode = "max";
var precipChart = null;
var tempChart = null;

function num(value) {
    if (value === null || value === undefined || value === "") return null;
    var n = Number(value);
    return isFinite(n) ? n : null;
}

function fmt(value, digits) {
    var n = num(value);
    return n === null ? "\u2014" : n.toFixed(digits);
}

function hasValues(values) {
    return (values || []).some(function (value) { return num(value) !== null; });
}

function parseDay(iso) {
    if (!iso) return null;
    var parts = String(iso).split("-");
    if (parts.length !== 3) return null;
    return new Date(Number(parts[0]), Number(parts[1]) - 1, Number(parts[2]));
}

function shortDate(iso) {
    var d = parseDay(iso);
    if (!d) return String(iso || "");
    return d.toLocaleDateString(undefined, { day: "2-digit", month: "short" });
}

function weekday(iso) {
    var d = parseDay(iso);
    if (!d) return "";
    return d.toLocaleDateString(undefined, { weekday: "short" });
}

function setText(id, text) {
    var el = document.getElementById(id);
    if (el) el.textContent = text;
}

function showError(message) {
    var box = document.getElementById("weather-error");
    var text = document.getElementById("weather-error-text");
    if (text) text.textContent = message || "Live weather forecast is unavailable right now.";
    if (box) box.classList.remove("hidden");
}

function hideError() {
    var box = document.getElementById("weather-error");
    if (box) box.classList.add("hidden");
}

function clearWeatherViews() {
    if (precipChart) { precipChart.destroy(); precipChart = null; }
    if (tempChart) { tempChart.destroy(); tempChart = null; }
    var tbody = document.getElementById("precip-table-body");
    if (tbody) tbody.innerHTML = "";
    var heat = document.getElementById("temp-heatmap");
    if (heat) heat.innerHTML = "";
}

function renderWeather(payload) {
    WEATHER = payload || {};
    var days = WEATHER.days || [];
    var summary = WEATHER.summary || {};

    if (!days.length) {
        showError(WEATHER.error);
        setText("kpi-total-rain", "\u2014");
        setText("kpi-max-temp", "\u2014");
        setText("kpi-avg-temp", "\u2014");
        setText("kpi-avg-humidity", "\u2014");
        setText("weather-provenance", "No live forecast available");
        var strip = document.getElementById("daily-strip");
        if (strip) {
            strip.innerHTML =
                '<div id="daily-strip-empty" class="col-span-full rounded-xl border border-dashed border-outline-variant p-6 text-center text-xs text-on-surface-variant"></div>';
            var empty = document.getElementById("daily-strip-empty");
            if (empty) empty.textContent = WEATHER.error || "No forecast data";
        }
        clearWeatherViews();
        return;
    }

    hideError();
    var rain = num(summary.total_rain_mm);
    setText("kpi-total-rain", rain === null ? "\u2014" : rain.toFixed(1) + " mm");
    setText("kpi-max-temp", fmt(summary.max_temp_c, 1) + " \u00b0C");
    setText("kpi-avg-temp", fmt(summary.avg_temp_c, 1) + " \u00b0C");
    setText("kpi-avg-humidity", summary.avg_humidity === null || summary.avg_humidity === undefined
        ? "\u2014" : summary.avg_humidity + "%");

    var regionName = (WEATHER.region && WEATHER.region.name) || "\u2014";
    setText("rain-region-label", regionName);
    setText("temp-region-label", regionName);

    var provenance = [];
    if (WEATHER.model) provenance.push("Model: " + WEATHER.model);
    if (WEATHER.issued_at) {
        var issued = new Date(WEATHER.issued_at);
        if (!isNaN(issued.getTime())) {
            provenance.push("Updated " + issued.toLocaleString());
        }
    }
    if (summary.forecast_days) provenance.push(summary.forecast_days + "-day horizon");
    setText("weather-provenance", provenance.join(" \u00b7 "));

    buildDailyStrip(days);
    buildPrecipChart();
    buildPrecipTable();
    buildTempChart(currentTempMode);
    buildTempHeatmap();
}

/* ── 7-day cards ─────────────────────────────────────────────────────── */
function buildDailyStrip(days) {
    var week = days.slice(0, 7);
    var html = "";
    week.forEach(function (day, index) {
        var condition = day.condition || {
            label: "", icon: "cloud", color: "#6b7280", bg: "#f3f4f6"
        };
        var isToday = index === 0;
        var label = isToday ? "Today" : weekday(day.date);
        var precip = num(day.precip);
        var rainText = precip !== null && precip > 0
            ? '<span class="text-[10px] font-label text-blue-600 mt-0.5">\ud83d\udca7' + precip.toFixed(1) + "mm</span>"
            : '<span class="text-[10px] font-label text-on-surface-variant/50 mt-0.5">dry</span>';

        html +=
            '<div class="flex flex-col items-center rounded-xl p-3 text-center border transition-all ' +
            (isToday ? "border-secondary shadow-md" : "border-outline-variant/60 hover:border-secondary/50") +
            '" style="background:' + condition.bg + '">' +
            '<span class="text-[11px] font-label font-bold ' +
            (isToday ? "text-secondary" : "text-on-surface-variant") + '">' + label + "</span>" +
            '<span class="material-symbols-outlined text-3xl my-2" style="color:' + condition.color + '">' +
            condition.icon + "</span>" +
            '<span class="text-[10px] font-label text-on-surface-variant mb-1">' + condition.label + "</span>" +
            '<div class="flex flex-col gap-0.5 w-full">' +
            '<span class="text-sm font-headline font-bold text-red-600">' + fmt(day.tmax, 0) + "\u00b0</span>" +
            '<span class="text-xs font-label text-blue-500">' + fmt(day.tmin, 0) + "\u00b0</span>" +
            rainText +
            "</div></div>";
    });
    var strip = document.getElementById("daily-strip");
    if (strip) strip.innerHTML = html;
}

/* ── Rain chart ──────────────────────────────────────────────────────── */
function buildPrecipChart() {
    var ctx = document.getElementById("precipChart");
    if (!ctx || !WEATHER || !(WEATHER.days || []).length) return;
    if (precipChart) precipChart.destroy();

    var days = WEATHER.days;
    var climatology = WEATHER.climatology || {};
    var labels = days.map(function (day) { return shortDate(day.date); });
    var rain = days.map(function (day) { return num(day.precip); });
    var probability = days.map(function (day) { return num(day.precip_prob); });
    var normal = climatology.rain_mm || [];

    precipChart = new Chart(ctx.getContext("2d"), {
        data: {
            labels: labels,
            datasets: [
                {
                    type: "bar",
                    label: "Forecast Rain (mm)",
                    data: rain,
                    backgroundColor: "rgba(59,130,246,0.75)",
                    borderColor: "rgba(59,130,246,1)",
                    borderWidth: 1.5,
                    borderRadius: 4,
                    order: 2,
                    yAxisID: "y"
                },
                {
                    type: "line",
                    label: "Rain Probability (%)",
                    data: probability,
                    borderColor: "#38bdf8",
                    backgroundColor: "rgba(56,189,248,0.08)",
                    borderWidth: 1.5,
                    borderDash: [4, 3],
                    pointRadius: 0,
                    pointHoverRadius: 4,
                    tension: 0.35,
                    fill: false,
                    order: 1,
                    yAxisID: "y1"
                },
                {
                    type: "line",
                    label: "10-yr Daily Normal (mm)",
                    data: normal,
                    borderColor: "#f59e0b",
                    borderWidth: 2,
                    borderDash: [5, 3],
                    pointRadius: 2,
                    pointBackgroundColor: "#f59e0b",
                    fill: false,
                    tension: 0.35,
                    order: 0,
                    yAxisID: "y"
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: { mode: "index", intersect: false },
            plugins: {
                legend: { display: false },
                tooltip: {
                    callbacks: {
                        label: function (context) {
                            var unit = context.dataset.yAxisID === "y1" ? "%" : " mm";
                            return context.dataset.label + ": " + context.formattedValue + unit;
                        }
                    }
                }
            },
            scales: {
                x: {
                    grid: { display: false },
                    ticks: { font: { family: "JetBrains Mono", size: 10 } }
                },
                y: {
                    beginAtZero: true,
                    grid: { color: "rgba(0,0,0,0.05)" },
                    ticks: {
                        font: { family: "JetBrains Mono", size: 10 },
                        callback: function (value) { return value + " mm"; }
                    }
                },
                y1: {
                    beginAtZero: true,
                    max: 100,
                    position: "right",
                    grid: { drawOnChartArea: false },
                    ticks: {
                        font: { family: "JetBrains Mono", size: 10 },
                        callback: function (value) { return value + "%"; }
                    }
                }
            }
        }
    });
}

function buildPrecipTable() {
    var tbody = document.getElementById("precip-table-body");
    if (!tbody || !WEATHER) return;

    var days = WEATHER.days || [];
    var normal = (WEATHER.climatology || {}).rain_mm || [];
    var html = "";

    days.forEach(function (day, index) {
        var rain = num(day.precip);
        var norm = num(normal[index]);
        var anomaly = rain !== null && norm !== null ? +(rain - norm).toFixed(1) : null;
        var statusClass;
        var statusText;

        if (rain === null) {
            statusClass = "text-on-surface-variant";
            statusText = "\u2014";
        } else if (rain >= 1) {
            statusClass = "text-blue-600 font-bold";
            statusText = norm !== null && rain < norm ? "Below Avg" : "Wet";
        } else {
            statusClass = norm !== null && norm >= 1 ? "text-red-600 font-bold" : "text-on-surface-variant";
            statusText = norm !== null && norm >= 1 ? "Dry" : "No Rain";
        }

        var anomalyText = anomaly === null
            ? "\u2014"
            : (anomaly >= 0 ? "+" : "") + anomaly.toFixed(1);

        html +=
            '<tr class="hover:bg-surface-container-low/40">' +
            '<td class="p-2 text-left font-bold text-on-surface whitespace-nowrap">' + shortDate(day.date) + "</td>" +
            '<td class="p-2 font-mono">' + fmt(rain, 1) + "</td>" +
            '<td class="p-2 font-mono text-on-surface-variant">' +
            (day.precip_prob === null || day.precip_prob === undefined ? "\u2014" : day.precip_prob + "%") +
            "</td>" +
            '<td class="p-2 font-mono text-on-surface-variant">' + fmt(norm, 1) + "</td>" +
            '<td class="p-2 font-mono ' + (anomaly !== null && anomaly < 0 ? "text-red-500" : "text-blue-600") + '">' +
            anomalyText + "</td>" +
            '<td class="p-2"><span class="' + statusClass + ' text-[11px]">' + statusText + "</span></td>" +
            "</tr>";
    });

    tbody.innerHTML = html;
}

/* ── Temperature chart ───────────────────────────────────────────────── */
function buildTempChart(mode) {
    var ctx = document.getElementById("tempChart");
    if (!ctx || !WEATHER || !(WEATHER.days || []).length) return;
    if (tempChart) tempChart.destroy();

    var days = WEATHER.days;
    var climatology = WEATHER.climatology || {};
    var histMax = climatology.tmax_c || [];
    var histMin = climatology.tmin_c || [];
    var labels = days.map(function (day) { return shortDate(day.date); });
    var maxTemps = days.map(function (day) { return num(day.tmax); });
    var minTemps = days.map(function (day) { return num(day.tmin); });
    var avgTemps = days.map(function (day) { return num(day.tmean); });
    var normalAvg = days.map(function (_, index) {
        var hi = num(histMax[index]);
        var lo = num(histMin[index]);
        return hi !== null && lo !== null ? +((hi + lo) / 2).toFixed(1) : null;
    });

    tempChart = new Chart(ctx.getContext("2d"), {
        type: "line",
        data: {
            labels: labels,
            datasets: [
                {
                    label: "Max Temp (\u00b0C)",
                    data: maxTemps,
                    borderColor: "#ef4444",
                    backgroundColor: "rgba(239,68,68,0.08)",
                    fill: mode === "max",
                    tension: 0.4,
                    borderWidth: 2.5,
                    pointRadius: 3,
                    pointHoverRadius: 5,
                    pointBackgroundColor: "#ef4444",
                    hidden: mode === "min"
                },
                {
                    label: "Avg Temp (\u00b0C)",
                    data: avgTemps,
                    borderColor: "#f97316",
                    backgroundColor: "rgba(249,115,22,0.08)",
                    fill: mode === "avg",
                    tension: 0.4,
                    borderWidth: 2,
                    pointRadius: 2,
                    pointHoverRadius: 5,
                    pointBackgroundColor: "#f97316",
                    hidden: mode === "min" || mode === "max"
                },
                {
                    label: "Min Temp (\u00b0C)",
                    data: minTemps,
                    borderColor: "#38bdf8",
                    backgroundColor: "rgba(56,189,248,0.08)",
                    fill: mode === "min",
                    tension: 0.4,
                    borderWidth: 2,
                    pointRadius: 2,
                    pointHoverRadius: 5,
                    pointBackgroundColor: "#38bdf8",
                    hidden: mode === "max"
                },
                {
                    label: "Historical Avg (\u00b0C)",
                    data: normalAvg,
                    borderColor: "#9ca3af",
                    borderDash: [5, 3],
                    borderWidth: 1.5,
                    pointRadius: 0,
                    fill: false,
                    tension: 0.35
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: { mode: "index", intersect: false },
            plugins: {
                legend: { display: false },
                tooltip: {
                    callbacks: {
                        label: function (context) {
                            return context.dataset.label + ": " + context.formattedValue + "\u00b0C";
                        }
                    }
                }
            },
            scales: {
                x: {
                    grid: { display: false },
                    ticks: { font: { family: "JetBrains Mono", size: 10 } }
                },
                y: {
                    grid: { color: "rgba(0,0,0,0.05)" },
                    ticks: {
                        font: { family: "JetBrains Mono", size: 10 },
                        callback: function (value) { return value + "\u00b0C"; }
                    }
                }
            }
        }
    });
}

function setTempMode(mode) {
    currentTempMode = mode;
    ["max", "min", "avg"].forEach(function (name) {
        var button = document.getElementById("temp-" + name + "-btn");
        if (!button) return;
        button.className = name === mode
            ? "px-2.5 py-1 font-bold bg-primary text-on-primary transition-colors"
            : "px-2.5 py-1 font-bold bg-surface-container-low text-on-surface-variant hover:text-primary transition-colors";
    });
    buildTempChart(mode);
}

function buildTempHeatmap() {
    var container = document.getElementById("temp-heatmap");
    if (!container || !WEATHER) return;

    var html = "";
    (WEATHER.days || []).forEach(function (day) {
        var temperature = num(day.tmax);
        var background;
        var color;

        if (temperature === null) {
            background = "#f3f4f6"; color = "#6b7280";
        } else if (temperature < 18) {
            background = "#bae6fd"; color = "#0369a1";
        } else if (temperature < 26) {
            background = "#fef08a"; color = "#854d0e";
        } else if (temperature < 33) {
            background = "#fb923c"; color = "#ffffff";
        } else {
            background = "#dc2626"; color = "#ffffff";
        }

        html +=
            '<div class="rounded-lg p-2 text-center" style="background:' + background + ";color:" + color + '">' +
            '<div class="text-[9px] font-label font-bold">' + shortDate(day.date) + "</div>" +
            '<div class="text-sm font-headline font-extrabold">' +
            (temperature === null ? "\u2014" : Math.round(temperature) + "\u00b0") +
            "</div></div>";
    });

    container.innerHTML = html;
}

/* ── Region switch ───────────────────────────────────────────────────── */
function loadWeatherForecast() {
    var panel = document.getElementById("weather-panel");
    var select = document.getElementById("weather-region-select");
    if (!panel || !select || !select.value) return;

    var endpoint = panel.getAttribute("data-api-url") || "/api/weather-forecast/";
    var url = endpoint + "?days=16&region=" + encodeURIComponent(select.value);
    setText("weather-provenance", "Fetching live weather\u2026");

    fetch(url, { headers: { Accept: "application/json" } })
        .then(function (response) {
            return response.json().then(function (body) {
                return { ok: response.ok, body: body };
            });
        })
        .then(function (result) {
            renderWeather(result.body);
        })
        .catch(function () {
            renderWeather({
                error: "Could not reach the weather service. Please try again shortly.",
                days: []
            });
        });
}

/* ── Boot ────────────────────────────────────────────────────────────── */
document.addEventListener("DOMContentLoaded", function () {
    var days = (WEATHER && WEATHER.days) || [];
    if (WEATHER && (days.length || WEATHER.error)) {
        renderWeather(WEATHER);
    } else {
        loadWeatherForecast();
    }
});
