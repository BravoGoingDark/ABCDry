/* Gridded SPEI drought forecast map for the 29 Ichkeul cells.
 * Data: /api/drought-grid/ (built by `manage.py build_drought_grid`).
 * Only verified-skilful lead times can be selected; the rest are shown
 * disabled so users see where predictability ends. */
(function () {
    "use strict";
    const root = document.getElementById("drought-grid");
    if (!root) return;

    const LANG = (document.documentElement.lang || "en").slice(0, 2);
    const T = {
        en: {
            now: "Last observed", observed: "Observed (latest complete rainfall data)", thisMonth: "this month", lagNote: "CHIRPS rainfall is published 3–6 weeks after month end. * = past month not yet measured · ● = current month", noSkill: "No verified skill at this lead — use climatology",
            obsNote: "Observed water balance (CHIRPS rain − FAO-56 ET0). Not a forecast.",
            pDrought: "Probability of drought (SPEI ≤ −1)", interval: "80 % range",
            auc: "Drought detection (ROC AUC)", msss: "Skill vs climatology (MSSS)", pers: "Skill of “no change” (persistence)",
            hit: "Droughts caught (hit rate)", far: "False alarms", period: "Verified", months: "months",
            drivers: "What drives this forecast (SPEI units; negative = drier)", target: "Target month",
            issued: "Issued from data up to", behind: "months before today", generated: "computed",
            pastTarget: "past month, rainfall not yet published", none: "No forecast available yet.",
            build: "Run “python manage.py build_drought_grid” to build it.",
            cell: "Cell", wet: "wetter", dry: "drier", basinP: "of the basin area-weighted drought probability",
            skilful: "skilful", notSkilful: "no skill",
            scIntro: (n, a, b) => `Each row replays the weather of the ${n} recorded years (${a}–${b}) on top of the water balance observed so far, with evaporation adjusted to today’s warmer climate. The observed part is exact; only the future months vary.`,
            ridgeNote: "Drivers are from the companion linear model. Its own estimate:",
            scTarget: "Target", scKnown: "Already observed", scDry: "Dry case (1 in 10)", scMid: "Middle", scWet: "Wet case (1 in 10)",
            scChance: "Drought chance", scRain: "Rain needed to be out of drought", scNormal: "of normal", scNone: "none",
            scSkill: "Verified", scOf: "of", scNoScen: "Scenario outlook not available in this run.",
            scFoot: "Rain needed = basin rainfall over the remaining months of the window for SPEI > −1, assuming recent evaporation. Rows in grey did not pass the skill rule out of sample: read them as the climate range, not as a forecast.",
            cls: { extreme: "Extreme drought", severe: "Severe drought", moderate: "Moderate drought", mild: "Mild dryness",
                   normal: "Near normal", wet: "Moderately wet", very_wet: "Very wet" },
        },
        fr: {
            now: "Dernier observé", observed: "Observé (dernières données de pluie complètes)", thisMonth: "ce mois-ci", lagNote: "La pluie CHIRPS est publiée 3 à 6 semaines après la fin du mois. * = mois passé pas encore mesuré · ● = mois en cours", noSkill: "Aucune fiabilité vérifiée à cette échéance — utiliser la climatologie",
            obsNote: "Bilan hydrique observé (pluie CHIRPS − ET0 FAO-56). Ce n’est pas une prévision.",
            pDrought: "Probabilité de sécheresse (SPEI ≤ −1)", interval: "Intervalle 80 %",
            auc: "Détection des sécheresses (ROC AUC)", msss: "Gain vs climatologie (MSSS)", pers: "Gain de la persistance",
            hit: "Sécheresses détectées", far: "Fausses alertes", period: "Vérifié", months: "mois",
            drivers: "Facteurs de la prévision (unités SPEI ; négatif = plus sec)", target: "Mois cible",
            issued: "Émis à partir des données jusqu’à", behind: "mois avant aujourd’hui", generated: "calculé",
            pastTarget: "mois passé, pluie pas encore publiée", none: "Aucune prévision disponible.",
            build: "Lancer « python manage.py build_drought_grid » pour la construire.",
            cell: "Cellule", wet: "plus humide", dry: "plus sec", basinP: "probabilité moyenne de sécheresse du bassin",
            skilful: "fiable", notSkilful: "non fiable",
            scIntro: (n, a, b) => `Chaque ligne rejoue la météo des ${n} années enregistrées (${a}–${b}) à partir du bilan hydrique déjà observé, avec une évaporation ajustée au climat actuel plus chaud. La partie observée est exacte ; seuls les mois futurs varient.`,
            ridgeNote: "Les facteurs viennent du modèle linéaire associé. Son estimation :",
            scTarget: "Cible", scKnown: "Déjà observé", scDry: "Cas sec (1 sur 10)", scMid: "Médiane", scWet: "Cas humide (1 sur 10)",
            scChance: "Risque de sécheresse", scRain: "Pluie nécessaire pour sortir de la sécheresse", scNormal: "de la normale", scNone: "aucune",
            scSkill: "Vérifié", scOf: "sur", scNoScen: "Scénarios non disponibles pour cette exécution.",
            scFoot: "Pluie nécessaire = pluie du bassin sur les mois restants de la fenêtre pour SPEI > −1, avec l’évaporation récente. Les lignes grises n’ont pas passé le seuil de fiabilité hors échantillon : à lire comme la plage climatique, pas comme une prévision.",
            cls: { extreme: "Sécheresse extrême", severe: "Sécheresse sévère", moderate: "Sécheresse modérée", mild: "Légèrement sec",
                   normal: "Proche de la normale", wet: "Modérément humide", very_wet: "Très humide" },
        },
    };
    const t = T[LANG] || T.en;
    const DRIVER_FR = {
        memory_long: "Déficit hydrique accumulé (6–24 mois)", memory_short: "Bilan hydrique récent (1–3 mois)",
        rain: "Anomalie de pluie du dernier mois", heat: "Demande évaporative et température (ET0)",
        soil: "Humidité du sol (0–28 cm)", season: "Saison du mois cible",
    };

    const SPEI_BREAKS = [
        [-Infinity, -2, "#7f2704", "≤ −2"], [-2, -1.5, "#d94801", "−2 … −1.5"], [-1.5, -1, "#fd8d3c", "−1.5 … −1"],
        [-1, -0.5, "#fdd0a2", "−1 … −0.5"], [-0.5, 0.5, "#f2f2f2", "−0.5 … 0.5"], [0.5, 1, "#9ecae1", "0.5 … 1"],
        [1, 1.5, "#4292c6", "1 … 1.5"], [1.5, Infinity, "#08519c", "≥ 1.5"],
    ];
    const PROB_BREAKS = [
        [0, 0.1, "#fff5eb", "< 10 %"], [0.1, 0.25, "#fdd0a2", "10–25 %"], [0.25, 0.5, "#fd8d3c", "25–50 %"],
        [0.5, 0.75, "#d94801", "50–75 %"], [0.75, 1.01, "#7f2704", "> 75 %"],
    ];
    const txtColor = (v) => (v > -0.5 && v < 0.5 ? "#414844" : pick(SPEI_BREAKS, v));
    const pick = (breaks, v) => (breaks.find((b) => v > b[0] - 1e-9 && v < b[1]) || breaks[breaks.length - 1])[2];

    const $ = (id) => document.getElementById(id);
    const fmt = (v, d = 2) => (v === null || v === undefined || Number.isNaN(v) ? "—" : (v > 0 ? "+" : "") + Number(v).toFixed(d));
    const pct = (v) => (v === null || v === undefined ? "—" : Math.round(v * 100) + " %");
    const monthLabel = (iso, long) => new Date(iso + "T00:00:00").toLocaleDateString(LANG === "ar" ? "ar-TN" : LANG,
        { month: long ? "long" : "short", year: long ? "numeric" : "2-digit" });
    const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

    const state = { k: "6", h: 1, mode: "spei", cell: null };
    let data = null, map = null, cellLayer = null;
    const layersById = {};

    const skillOf = (k, h) => (data.skill || {})[`${k}_${h}`] || null;
    const skilful = (k, h) => h === 0 || !!(skillOf(k, h) || {}).skilful;
    const maxLead = (k) => Math.max(0, ...data.leads.filter((h) => skilful(k, h)));

    function cellValue(cid) {
        const c = data.cells[cid];
        if (!c) return null;
        if (state.h === 0) {
            const v = c.observed[`spei${state.k}`];
            return v === null ? null : { spei: v };
        }
        return ((c.forecast[state.k] || {})[String(state.h)]) || null;
    }

    function colorFor(v) {
        if (!v) return "#555";
        return state.mode === "prob" && state.h > 0 ? pick(PROB_BREAKS, v.p_drought) : pick(SPEI_BREAKS, v.spei);
    }

    function classOf(spei) {
        if (spei <= -2) return "extreme";
        if (spei <= -1.5) return "severe";
        if (spei <= -1) return "moderate";
        if (spei <= -0.5) return "mild";
        if (spei < 0.5) return "normal";
        if (spei < 1) return "wet";
        return "very_wet";
    }

    // ------------------------------------------------------------------ controls
    function renderControls() {
        $("dg-scales").innerHTML = Object.keys(data.scales).map((k) =>
            `<button type="button" class="dg-seg ${k === state.k ? "on" : ""}" data-k="${k}" title="${esc(data.scales[k].kind)}">${esc(data.scales[k].label)}</button>`
        ).join("");
        const nowMonth = new Date(); nowMonth.setDate(1);
        const leads = [0, ...data.leads].map((h) => {
            const iso = h === 0 ? data.issue_month : data.target_months[String(h)];
            const ok = skilful(state.k, h);
            const d = new Date(iso + "T00:00:00");
            const current = d.getFullYear() === nowMonth.getFullYear() && d.getMonth() === nowMonth.getMonth();
            const past = h > 0 && d < new Date(nowMonth.getFullYear(), nowMonth.getMonth(), 1);
            const title = h === 0 ? t.observed : (ok ? (past ? t.pastTarget : current ? t.thisMonth : t.skilful) : t.noSkill);
            return `<button type="button" class="dg-lead ${h === state.h ? "on" : ""}${current ? " dg-current" : ""}" data-h="${h}" ${ok ? "" : "disabled"} title="${esc(title)}">` +
                `${h === 0 ? t.now : "+" + h}<small>${esc(monthLabel(iso))}${past ? "*" : ""}${current ? " ●" : ""}</small></button>`;
        });
        $("dg-leads").innerHTML = leads.join("");
        root.querySelectorAll("#dg-modes .dg-seg").forEach((b) => {
            b.classList.toggle("on", b.dataset.mode === (state.h === 0 ? "spei" : state.mode));
            b.disabled = state.h === 0 && b.dataset.mode === "prob";
            b.style.opacity = b.disabled ? 0.45 : 1;
        });
        const sc = data.scales[state.k];
        $("dg-scale-meaning").innerHTML = `<b class="text-on-surface">${esc(sc.label)}</b> · ${esc(sc.kind)} — ${esc(sc.meaning)}`;
    }

    root.addEventListener("click", (e) => {
        const kb = e.target.closest("[data-k]"), hb = e.target.closest("[data-h]"), mb = e.target.closest("[data-mode]");
        if (kb) {
            state.k = kb.dataset.k;
            if (!skilful(state.k, state.h)) state.h = maxLead(state.k);
        } else if (hb && !hb.disabled) {
            state.h = Number(hb.dataset.h);
        } else if (mb && !mb.disabled) {
            state.mode = mb.dataset.mode;
        } else return;
        update();
    });

    // ------------------------------------------------------------------ panels
    function renderLegend() {
        const prob = state.mode === "prob" && state.h > 0;
        const breaks = prob ? PROB_BREAKS : SPEI_BREAKS;
        $("dg-legend").innerHTML = `<div class="font-bold mb-1">${prob ? esc(t.pDrought) : esc(data.scales[state.k].label)}</div>` +
            breaks.slice().reverse().map((b) => `<div class="flex items-center gap-1.5 leading-4"><span class="dg-swatch" style="background:${b[2]}"></span>${b[3]}</div>`).join("");
    }

    function renderBasin() {
        if (state.h === 0) {
            const hist = data.history[state.k] || [];
            const last = hist[hist.length - 1];
            $("dg-basin").innerHTML = last
                ? `<div class="flex items-baseline gap-2"><span class="font-headline font-extrabold text-3xl" style="color:${txtColor(last.spei)}">${fmt(last.spei)}</span>` +
                  `<span class="text-xs font-semibold text-on-surface">${esc(t.cls[classOf(last.spei)])}</span></div>` +
                  `<div class="text-[11px] text-on-surface-variant mt-1">${esc(t.observed)} · ${esc(monthLabel(data.issue_month, true))}</div>`
                : "—";
            return;
        }
        const b = data.basin[state.k][String(state.h)];
        $("dg-basin").innerHTML =
            `<div class="flex items-baseline gap-2 flex-wrap"><span class="font-headline font-extrabold text-3xl" style="color:${txtColor(b.spei)}">${fmt(b.spei)}</span>` +
            `<span class="text-xs font-semibold text-on-surface">${esc(t.cls[classOf(b.spei)])}</span></div>` +
            `<div class="text-[11px] text-on-surface-variant mt-1">${esc(t.target)}: <b>${esc(monthLabel(b.target_month, true))}</b></div>` +
            `<div class="mt-2 flex items-center gap-2"><div class="dg-bar-track flex-1"><div class="dg-bar" style="left:0;width:${Math.round(b.p_drought * 100)}%;background:${pick(PROB_BREAKS, b.p_drought)}"></div></div>` +
            `<span class="text-xs font-label font-bold">${pct(b.p_drought)}</span></div>` +
            `<div class="text-[10px] text-on-surface-variant mt-0.5">${esc(t.pDrought)}</div>`;
    }

    function renderSkill() {
        if (state.h === 0) {
            $("dg-skill").innerHTML = `<p class="text-xs text-on-surface-variant">${esc(t.obsNote)}</p>`;
            return;
        }
        const s = skillOf(state.k, state.h);
        if (!s) { $("dg-skill").innerHTML = "—"; return; }
        const row = (label, val, good) => `<div class="flex justify-between gap-2 py-0.5"><span class="text-on-surface-variant">${esc(label)}</span>` +
            `<span class="font-label font-bold ${good === undefined ? "" : good ? "text-emerald-700" : "text-red-700"}">${val}</span></div>`;
        $("dg-skill").innerHTML = `<div class="text-xs">` +
            row(t.auc, s.auc.toFixed(2), s.auc >= data.skill_rule.min_auc) +
            row(t.msss, s.msss.toFixed(2), s.msss >= data.skill_rule.min_msss) +
            row(t.pers, s.msss_persistence.toFixed(2)) +
            row(t.hit, pct(s.hit_rate)) +
            row(t.far, pct(s.false_alarm_ratio)) +
            `<div class="text-[10px] text-on-surface-variant mt-1.5">${esc(t.period)} ${esc(s.period)} · ${s.n_months} ${esc(t.months)} × 29 · RMSE ${s.rmse.toFixed(2)}</div></div>`;
    }

    function renderCell() {
        const cid = state.cell;
        if (!cid || !data.cells[cid]) return;
        const c = data.cells[cid];
        const head = `<div class="flex items-baseline justify-between"><span class="font-headline font-bold text-on-surface text-sm">${esc(t.cell)} ${esc(cid)}</span>` +
            `<span class="text-[10px] font-label">${c.km2 ? c.km2 + " km²" : ""} · ${c.lat.toFixed(2)}°N ${c.lon.toFixed(2)}°E</span></div>`;
        if (state.h === 0) {
            $("dg-cell").innerHTML = head + `<div class="grid grid-cols-5 gap-2 mt-2 text-center">` +
                ["1", "3", "6", "12", "24"].filter((k) => c.observed["spei" + k] !== undefined).map((k) => {
                    const v = c.observed["spei" + k];
                    return `<div class="rounded border border-outline-variant py-1.5"><div class="text-[9px] font-label">SPEI-${k}</div>` +
                        `<div class="font-label font-bold text-sm" style="color:${v === null ? "#999" : txtColor(v)}">${fmt(v)}</div></div>`;
                }).join("") + `</div><p class="text-[10px] mt-2">${esc(t.obsNote)}</p>`;
            return;
        }
        const f = (c.forecast[state.k] || {})[String(state.h)];
        if (!f) { $("dg-cell").innerHTML = head + "—"; return; }
        const maxAbs = Math.max(0.5, ...f.drivers.map((d) => Math.abs(d.effect)));
        const drivers = f.drivers.map((d) => {
            const w = Math.round(Math.abs(d.effect) / maxAbs * 50);
            const left = d.effect < 0 ? 50 - w : 50;
            const label = LANG === "fr" ? (DRIVER_FR[d.key] || d.label) : d.label;
            return `<div class="mt-1.5"><div class="flex justify-between text-[10px] gap-2"><span class="truncate" title="${esc(label)}">${esc(label)}</span>` +
                `<span class="font-label font-bold ${d.effect < 0 ? "text-red-700" : "text-sky-700"}">${fmt(d.effect)}</span></div>` +
                `<div class="dg-bar-track"><div class="dg-bar-mid"></div><div class="dg-bar" style="left:${left}%;width:${w}%;background:${d.effect < 0 ? "#d94801" : "#4292c6"}"></div></div></div>`;
        }).join("");
        $("dg-cell").innerHTML = head +
            `<div class="flex items-baseline gap-2 mt-2"><span class="font-headline font-extrabold text-2xl" style="color:${txtColor(f.spei)}">${fmt(f.spei)}</span>` +
            `<span class="text-xs font-semibold text-on-surface">${esc(t.cls[f.class] || f.class)}</span></div>` +
            `<div class="text-[11px] mt-0.5">${esc(t.interval)}: <span class="font-label">${fmt(f.lo)} … ${fmt(f.hi)}</span> · ${esc(t.pDrought)}: <b class="font-label">${pct(f.p_drought)}</b></div>` +
            `<div class="text-[10px] font-label uppercase tracking-wider mt-3">${esc(t.drivers)}</div>` +
            (f.ridge ? `<div class="text-[10px] mt-0.5">${esc(t.ridgeNote)} <b class="font-label">${fmt(f.ridge.spei)}</b> · ${pct(f.ridge.p_drought)}</div>` : "") +
            drivers;
    }

    function renderLeadSkill() {
        const rule = data.skill_rule.min_auc;
        const y = (auc) => Math.max(0, Math.min(1, (auc - 0.5) / 0.5)) * 100;
        $("dg-leadskill").innerHTML = Object.keys(data.scales).map((k) => {
            const cols = data.leads.map((h) => {
                const s = skillOf(k, h);
                const auc = s ? s.auc : 0.5;
                const ok = s && s.skilful;
                return `<div class="dg-colbar" style="height:${y(auc)}%;background:${ok ? "#1b4332" : "#c1c8c2"}" title="+${h}: AUC ${auc.toFixed(2)}, MSSS ${s ? s.msss.toFixed(2) : "—"}"><span>${auc.toFixed(2)}</span></div>`;
            }).join("");
            return `<div class="dg-skillcol"><div class="flex justify-between items-baseline mb-4"><span class="text-xs font-bold text-on-surface">${esc(data.scales[k].label)}</span>` +
                `<span class="text-[10px] font-label">${esc(t.skilful)}: ≤ +${maxLead(k)} ${esc(t.months)}</span></div>` +
                `<div class="dg-col"><div class="dg-thr" style="bottom:${y(rule)}%"></div>${cols}</div>` +
                `<div class="flex gap-[6px] mt-1">${data.leads.map((h) => `<div class="flex-1 text-center text-[9px] font-label">+${h}</div>`).join("")}</div></div>`;
        }).join("");
    }

    function renderScenarios() {
        const el = $("dg-scenarios");
        if (!el) return;
        const sc = data.scenarios;
        if (!sc || !sc.basin || !sc.basin[state.k]) { el.textContent = t.scNoScen; return; }
        const cell = (v) => `<span class="font-label font-bold" style="color:${txtColor(v)}">${fmt(v)}</span>`;
        const rows = data.leads.map((h) => {
            const b = sc.basin[state.k][String(h)];
            if (!b) return "";
            const sk = (sc.skill || {})[`${state.k}_${h}`] || {};
            const rain = b.rain_needed_mm <= 0 ? t.scNone
                : `${b.rain_needed_mm} mm` + (b.rain_needed_pct === null ? "" : ` · ${b.rain_needed_pct} % ${esc(t.scNormal)}`);
            return `<tr class="border-t border-outline-variant" style="${sk.skilful ? "" : "opacity:.55"}">` +
                `<td class="py-1 pr-3 font-label">+${h} · ${esc(monthLabel(data.target_months[String(h)]))}</td>` +
                `<td class="py-1 pr-3 font-label">${b.observed_months} ${esc(t.scOf)} ${b.observed_months + b.future_months}</td>` +
                `<td class="py-1 pr-3">${cell(b.p10)} <span class="text-[10px]">(${b.driest_year})</span></td>` +
                `<td class="py-1 pr-3">${cell(b.p50)}</td>` +
                `<td class="py-1 pr-3">${cell(b.p90)} <span class="text-[10px]">(${b.wettest_year})</span></td>` +
                `<td class="py-1 pr-3 font-label font-bold" style="color:${pick(PROB_BREAKS, b.p_drought) === "#fff5eb" ? "#414844" : pick(PROB_BREAKS, b.p_drought)}">${pct(b.p_drought)}</td>` +
                `<td class="py-1 pr-3 font-label">${rain}</td>` +
                `<td class="py-1 font-label text-[10px]">${sk.auc === undefined || sk.auc === null ? "—" : "AUC " + sk.auc.toFixed(2)}</td></tr>`;
        }).join("");
        const th = (s) => `<th class="text-left font-label font-semibold text-[10px] uppercase tracking-wider py-1 pr-3">${esc(s)}</th>`;
        el.innerHTML = `<p class="mb-2">${esc(t.scIntro(sc.n_members, sc.member_years[0], sc.member_years[1]))}</p>` +
            `<table class="w-full whitespace-nowrap"><thead><tr>${[data.scales[state.k].label + " · " + t.scTarget, t.scKnown, t.scDry, t.scMid, t.scWet, t.scChance, t.scRain, t.scSkill].map(th).join("")}</tr></thead>` +
            `<tbody>${rows}</tbody></table><p class="text-[10px] mt-2">${esc(t.scFoot)}</p>`;
    }

    function renderMeta() {
        const behind = data.months_behind_today;
        $("dg-issue").innerHTML = `${esc(t.issued)} <b class="text-on-surface">${esc(monthLabel(data.issue_month, true))}</b>` +
            (behind > 0 ? ` (${behind} ${esc(t.behind)})` : "") +
            `<br><span class="text-[10px]">${esc(t.lagNote)}</span>` +
            `<br>${esc(data.model_version)} · ${esc(t.generated)} ${esc(new Date(data.generated_at).toLocaleDateString(LANG))}`;
        const s = data.sources;
        $("dg-method").innerHTML = [
            `<p><b>Index.</b> SPEI-k (Vicente-Serrano et al., 2010): climatic water balance D = P − ET0 summed over k months, fitted per cell and calendar month with a generalised-logistic distribution by L-moments on the ${esc(data.reference_period)} reference period, then converted to a standard normal score. SPEI ≤ −1 = moderate drought or worse (≈ 16 % of months in a stationary climate).</p>`,
            `<p><b>Data.</b> Rain: ${esc(s.precipitation)}. ET0: ${esc(s.et0)}. Soil moisture: ${esc(s.soil_moisture)}. One 0.1° cell = one ERA5-Land pixel.</p>`,
            (data.primary === "scenarios"
                ? `<p><b>Forecast.</b> The map shows the scenario ensemble: the median of all replayed years, the 10th–90th percentile range, and the share of years that end in drought. It verified at least as well as the linear model at every index and lead, and it cannot extrapolate beyond weather that has happened.</p>`
                : "") +
            `<p><b>${data.primary === "scenarios" ? "Drivers (companion linear model)" : "Model"}.</b> Ridge regression on standardised predictors (SPEI-1/3/6/12 now and 1–2 months back, plus SPEI-24 for the SPEI-24 models, rain / ET0 / temperature / soil-moisture anomalies, target season), one model per index and lead, pooled across the 29 cells. Gradient boosting was benchmarked and gave no extra out-of-sample skill. Its drought probability is a Gaussian predictive distribution with the verified out-of-sample error.</p>`,
            `<p><b>Scenarios.</b> The scenario table replays every recorded year after the last observed month and recomputes the index (ensemble method of Day, 1985). Each past year's evaporation is shifted to the mean of the last 10 years, because ET0 has risen. It is verified with the same out-of-sample rule as the forecast, using only years before each issue date.</p>`,
            `<p><b>Verification.</b> Expanding window, refit each year ${esc((skillOf("6", 1) || {}).period || "")}; a lead is offered only if ROC AUC ≥ ${data.skill_rule.min_auc} and MSSS ≥ ${data.skill_rule.min_msss}. Cells are strongly correlated, so the effective sample is the number of months, not months × 29.</p>`,
            `<p><b>Why skill stops where it does.</b> SPEI-k at lead h still contains k − h months that have already been observed. Once h ≥ k the forecast must predict future rain, and local predictors have essentially no skill for Mediterranean monthly rainfall. That is why SPEI-3 is useful to ~2 months, SPEI-6 to ~3–4, SPEI-12 to ~9 and SPEI-24 to 12. At the long scales the skill is mostly persistence of a deficit that already exists: it tells whether a drought will last, not when a new one will start. Forecasting further into unobserved rain would require dynamical seasonal forecasts (e.g. ECMWF SEAS5), whose rainfall skill over northern Tunisia is itself modest.</p>`,
            `<p><b>Limits.</b> Forecasts start from the last month with final CHIRPS rain (published ~3–6 weeks after month end), so the first lead can already be in the past (*). Summer SPEI-3 mostly reflects heat (ET0), because there is almost no rain to vary. Recent years lie below the 1981–2010 reference because of warming (ET0 ≈ +19 mm/decade), so dry classes appear more often than the nominal 16 %.</p>`,
        ].join("");
    }

    // ------------------------------------------------------------------ map
    function initMap(basin) {
        map = L.map("dg-map", { zoomControl: false, attributionControl: false, fadeAnimation: false, minZoom: 7, maxZoom: 14 });
        L.control.zoom({ position: "bottomright" }).addTo(map);
        const tiles = window.MapTiles
            ? window.MapTiles.createTileLayer(L, map, { variant: "satellite", maxZoom: 19 })
            : L.tileLayer("/api/tiles/{z}/{x}/{y}.png?layer=satellite", { maxZoom: 19 });
        tiles.addTo(map);
        const sections = basin.features.filter((f) => f.properties.kind === "section");
        const outline = basin.features.filter((f) => f.properties.kind === "outline");
        cellLayer = L.geoJSON({ type: "FeatureCollection", features: sections }, {
            style: () => ({ weight: 1, color: "#ffffff", opacity: 0.9, fillOpacity: 0.78 }),
            onEachFeature: (f, layer) => {
                const cid = f.properties.id;
                layersById[cid] = layer;
                layer.on("click", () => { state.cell = cid; update(); });
                layer.on("mouseover", () => layer.setStyle({ weight: 2.5 }));
                layer.on("mouseout", () => layer.setStyle({ weight: cid === state.cell ? 3 : 1 }));
            },
        }).addTo(map);
        const ol = L.geoJSON({ type: "FeatureCollection", features: outline }, {
            interactive: false, style: { color: "#0b1a22", weight: 3, fill: false },
        }).addTo(map);
        map.fitBounds(ol.getBounds(), { padding: [16, 16] });
        setTimeout(() => map.invalidateSize(), 200);
        window.addEventListener("resize", () => map.invalidateSize());
    }

    function paint() {
        Object.entries(layersById).forEach(([cid, layer]) => {
            const v = cellValue(cid);
            const sel = cid === state.cell;
            layer.setStyle({ fillColor: colorFor(v), weight: sel ? 3 : 1, color: sel ? "#012d1d" : "#ffffff" });
            const val = !v ? "—" : (state.mode === "prob" && state.h > 0 ? pct(v.p_drought) : "SPEI " + fmt(v.spei));
            layer.unbindTooltip();
            layer.bindTooltip(`<b>${esc(cid)}</b> · ${esc(val)}`, { sticky: true, className: "dg-tip" });
        });
    }

    function update() {
        renderControls(); renderLegend(); renderBasin(); renderSkill(); renderCell(); renderScenarios(); paint();
    }

    function start() {
        Promise.all([
            fetch(root.dataset.apiUrl, { credentials: "same-origin" }).then((r) => r.json().then((j) => ({ ok: r.ok, j }))),
            fetch(root.dataset.basinUrl).then((r) => r.json()),
        ]).then(([api, basin]) => {
            if (!api.ok || api.j.error) {
                $("dg-status").innerHTML = `${esc(t.none)}<br><span class="text-xs">${esc(t.build)}</span>`;
                return;
            }
            data = api.j;
            // Open on the current calendar month when that lead is verified-skilful.
            const today = new Date();
            const curLead = data.leads.find((h) => {
                const d = new Date(data.target_months[String(h)] + "T00:00:00");
                return d.getFullYear() === today.getFullYear() && d.getMonth() === today.getMonth();
            });
            state.h = curLead && skilful(state.k, curLead) ? curLead : Math.min(1, maxLead(state.k));
            initMap(basin);
            $("dg-status").remove();
            const worst = Object.keys(data.cells).sort((a, b) =>
                ((data.cells[a].forecast[state.k] || {})[String(state.h)] || {}).spei -
                ((data.cells[b].forecast[state.k] || {})[String(state.h)] || {}).spei)[0];
            state.cell = worst || null;
            renderMeta(); renderLeadSkill(); update();
        }).catch((err) => {
            console.error("Drought grid failed:", err);
            $("dg-status").textContent = t.none;
        });
    }

    if (window.L) start();
    else window.addEventListener("load", start);
})();
