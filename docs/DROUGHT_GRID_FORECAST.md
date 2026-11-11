# Gridded drought forecast — Ichkeul basin (29 cells)

What it predicts, how far ahead, how accurately, and what drives it.
Code: `dashboard/prediction_engine/drought_grid.py` · command: `python manage.py build_drought_grid` ·
API: `/api/drought-grid/` · UI: *Forcast* page (`/analysis/spei-outlook/`), section "Drought Forecast Map".

## 1. Target variable

**SPEI-k** (Standardised Precipitation-Evapotranspiration Index; Vicente-Serrano et al., 2010), computed for
each of the 29 grid sections, which are exactly the 0.1° ERA5-Land pixels covering the catchment.

* Climatic water balance per month: `D = P − ET0` (mm).
* `D` is summed over the last *k* months, k = 3, 6, 12, 24. SPEI-1 is only used as a predictor.
* For each cell and calendar month, a generalised-logistic (3-parameter log-logistic) distribution is fitted to
  the WMO **1981–2010** reference period by **L-moments / unbiased PWMs** (Hosking 1997; the method used by the
  reference `SPEI` R package). The probability is then mapped to a standard normal score.
  * Maximum likelihood is deliberately **not** used. For a location-bounded distribution, ML drags the bound onto
    the sample minimum. Any month just beyond the record then reads SPEI −3.7. Summer 2026 is exactly such a
    month: the most negative Jul–Sep water balance since 1981, with ET0 13 % above normal. L-moments give −3.3
    instead of the −3.72 clip value.
* **Drought event**: SPEI ≤ −1, i.e. moderate drought or worse (McKee et al., 1993).

Choose the index by the question being asked:

| Index | Type | Use |
|---|---|---|
| SPEI-3 | agricultural | rainfed sowing and early growth, root-zone water |
| SPEI-6 | agricultural / hydrological | yield, soil reserves, stream flow |
| SPEI-12 | hydrological | dams, groundwater, inflow and salinity balance of Lake Ichkeul |
| SPEI-24 | long-term hydrological | multi-year drought, large dams, aquifer recharge |

## 2. Data (per cell, monthly, Jan 1981 → last complete CHIRPS month)

| Variable | Source |
|---|---|
| Precipitation | CHIRPS v2.0 daily, 0.05°, summed per month (`UCSB-CHG/CHIRPS/DAILY`) |
| ET0 | FAO-56 Penman-Monteith (`physical_helpers.fao56_et0`) from ERA5-Land daily Tmax, Tmin, dew point, 10 m wind and downward shortwave (`ECMWF/ERA5_LAND/DAILY_AGGR`) |
| Soil moisture | ERA5-Land volumetric soil water, layers 1–2 (0–28 cm) |

All variables are fetched through Google Earth Engine and stored in `GridCellClimate`; later runs only fetch new
months. Basin climatology for 1981–2025: P = 565 mm/yr, ET0 = 1073 mm/yr. Trends: ET0 +19 mm/decade,
P −6 mm/decade. The driest year was 2022 (392 mm).

**Why CHIRPS rather than ERA5-Land rain:** monthly ERA5-Land precipitation agrees with CHIRPS only at r = 0.76
in anomaly space. Using it to fill the newest month would gain one month of lead time, at an error the
verification cannot account for. Forecasts are therefore issued only from CHIRPS-complete months. CHIRPS final
data arrives about 3–6 weeks after month end, so lead +1 can already be a past month that is not yet observed
(shown with `*` in the UI).

## 3. Model

**Published forecast (model v3): the scenario ensemble of section 5b.** The map value is the ensemble median, the
80 % range is its 10th-90th percentiles, and the drought probability is the share of replayed years with
SPEI <= -1. `payload.skill` holds its verification. The ridge model below is kept as a companion: it supplies the
driver attribution, its estimate is stored beside each forecast (`ridge`), and its skill table is in
`payload.skill_ridge`. The switch is done by `promote_scenarios`; if history is too short for an ensemble the
ridge forecast is published as before.

### Companion linear model

* One **ridge regression** (α = 10, standardised predictors) per (index k, lead h), pooled across the 29 cells.
  Leads h = 1…12 months.
* **Predictors at issue month t:**
  * SPEI-1/3/6/12 at t, t−1 and t−2 (the SPEI-24 models also get SPEI-24 at t, t−1, t−2; the other models
    are unchanged by its addition);
  * standardised anomalies of P, ET0, T and soil moisture (plus soil moisture at t−1);
  * sin/cos of the target month;
  * cell latitude and longitude.
* **Drought probability**: `P(SPEI ≤ −1) = Φ((−1 − μ) / σ_kh)`, where σ_kh is the **out-of-sample** RMSE for that
  index and lead. The probability is calibrated to the verified error, not to the training fit. The UI also shows
  the 80 % range `μ ± 1.28 σ`.
* **Benchmarked alternatives:** gradient boosting (XGBoost), persistence, and damped persistence fitted by target
  month. XGBoost gave no extra out-of-sample skill at any index or lead. Ridge is kept because it is at least as
  accurate and its attribution is exact.

## 4. Verification protocol

* **Expanding window, 2011 → present.** The model is refit at the start of every year. A training row is allowed
  only if its *target* month precedes the first issue month of the test year (a purge of h months). No month used
  for scoring is ever seen in training.
* **Leakage check:** a unit test runs the full verification on white-noise weather (`DroughtGridTests`). It must
  find no skill at lead ≥ scale, and still find skill for SPEI-12 at +1.
* **Effective sample:** the 29 cells are strongly correlated (per-cell AUC ranges only from 0.79 to 0.85 for
  SPEI-6 at +3). The effective sample is therefore the 188 verified months, not 188 × 29.
* **Publication rule:** a lead time is offered on the map only if ROC AUC ≥ 0.75 **and** MSSS (mean-square skill
  score against climatology, SPEI = 0) ≥ 0.20. Other leads are shown disabled.

### Results of the companion ridge model (run issued 2026-09, verified 2011–2026)

The published (scenario) scores are in section 5b.

| Index | Lead | ROC AUC | MSSS vs clim. | MSSS persistence | Hit rate | False alarms | RMSE | Published |
|---|---|---|---|---|---|---|---|---|
| SPEI-3 | +1 | 0.93 | 0.75 | 0.52 | 65 % | 18 % | 0.60 | yes |
| SPEI-3 | +2 | 0.80 | 0.41 | −0.09 | 28 % | 26 % | 0.93 | yes |
| SPEI-3 | +3 | 0.60 | 0.04 | −0.65 | 0 % | — | 1.19 | no |
| SPEI-3 | +4…+12 | 0.56–0.68 | 0.06–0.17 | < −0.2 | ≈ 0 % | — | 1.11–1.18 | no |
| SPEI-6 | +1 | 0.94 | 0.81 | 0.69 | 72 % | 17 % | 0.51 | yes |
| SPEI-6 | +2 | 0.88 | 0.68 | 0.40 | 56 % | 24 % | 0.67 | yes |
| SPEI-6 | +3 | 0.81 | 0.49 | 0.13 | 43 % | 30 % | 0.84 | yes |
| SPEI-6 | +4 | 0.74 | 0.33 | −0.03 | 27 % | 30 % | 0.97 | no |
| SPEI-6 | +5 | 0.66 | 0.18 | −0.23 | 11 % | 33 % | 1.07 | no |
| SPEI-6 | +6…+12 | 0.57–0.61 | 0.07–0.17 | < 0 | ≈ 0 % | — | 1.09–1.14 | no |
| SPEI-12 | +1 | 0.98 | 0.91 | 0.92 | 86 % | 8 % | 0.33 | yes |
| SPEI-12 | +2 | 0.97 | 0.84 | 0.84 | 80 % | 8 % | 0.45 | yes |
| SPEI-12 | +3 | 0.96 | 0.76 | 0.75 | 72 % | 11 % | 0.54 | yes |
| SPEI-12 | +4 | 0.94 | 0.70 | 0.67 | 66 % | 14 % | 0.61 | yes |
| SPEI-12 | +5 | 0.91 | 0.63 | 0.60 | 55 % | 19 % | 0.69 | yes |
| SPEI-12 | +6 | 0.88 | 0.57 | 0.56 | 48 % | 22 % | 0.74 | yes |
| SPEI-12 | +7 | 0.84 | 0.54 | 0.52 | 42 % | 21 % | 0.77 | yes |
| SPEI-12 | +8 | 0.81 | 0.49 | 0.46 | 35 % | 19 % | 0.81 | yes |
| SPEI-12 | +9 | 0.76 | 0.42 | 0.40 | 29 % | 22 % | 0.87 | yes |
| SPEI-12 | +10 | 0.72 | 0.35 | 0.34 | 11 % | 44 % | 0.92 | no |
| SPEI-12 | +11 | 0.67 | 0.29 | 0.28 | 5 % | 45 % | 0.96 | no |
| SPEI-12 | +12 | 0.65 | 0.22 | 0.24 | 2 % | — | 1.01 | no |
| SPEI-24 | +1 | 0.99 | 0.97 | 0.97 | 91 % | 6 % | 0.21 | yes |
| SPEI-24 | +3 | 0.97 | 0.92 | 0.93 | 84 % | 8 % | 0.36 | yes |
| SPEI-24 | +6 | 0.93 | 0.85 | 0.86 | 74 % | 16 % | 0.49 | yes |
| SPEI-24 | +9 | 0.92 | 0.83 | 0.79 | 66 % | 18 % | 0.53 | yes |
| SPEI-24 | +12 | 0.90 | 0.78 | 0.74 | 59 % | 16 % | 0.61 | yes |

Hit rate and false alarms are for the deterministic rule "forecast mean ≤ −1". The mean forecast is pulled
toward 0 at long leads, so the probability is the better decision variable. Lowering the alert threshold (for
example p ≥ 0.4) raises the hit rate at the cost of more false alarms.

The table is recomputed and stored with every run, so the UI always shows the current numbers.

## 5. How far ahead — and why it stops there

SPEI-k at lead h still contains **k − h months that are already observed**. Almost all of the skill comes from
that overlap, plus the soil and long-scale memory that comes with it:

* **h < k:** part of the answer is known. Skill decays as the known share k − h shrinks.
* **h ≥ k:** the whole window lies in the future, so the model has to predict future rainfall. With local
  predictors that skill is essentially zero for Mediterranean monthly rain: SPEI-1 at +1 has AUC 0.68 and
  R² ≈ 0. The table shows the same thing, with SPEI-3 collapsing at +3 and SPEI-6 at +4/+5.

Practical horizons with demonstrated skill:

* **SPEI-3:** 2 months.
* **SPEI-6:** 3 months with the ridge model, 4 with the published scenario ensemble.
* **SPEI-12:** 9 months. Its skill is largely persistence of the long deficit; the model adds a few points
  of MSSS on top. Beyond +6 the mean forecast rarely crosses −1 (hit rate 29 % at +9), so use the probability.
* **SPEI-24:** 12 months (the longest lead tested), AUC 0.90.

Read the long-scale results with two cautions:

* **They forecast persistence, not onset.** At +12, half of the SPEI-24 window is already observed. The forecast
  says whether an existing multi-year deficit will still be there, not when a new drought will start. Persistence
  alone scores MSSS 0.74 at +12; the model adds 0.04.
* **The sample is small.** 2011–2026 holds about eight independent 24-month windows, and SPEI-24 was in drought
  41 % of that time. The scores are therefore less certain than the SPEI-3/6 ones, whatever the month count says.

Going further would require dynamical seasonal forecasts (ECMWF SEAS5 / C3S). Their precipitation skill over
northern Tunisia is itself modest, and the strongest signal is in winter. Adding them is only worthwhile if their
hindcasts are verified with the same protocol.

## 5b. Scenario outlook (historical-year resampling)

Code: `scenario_ensemble`, `verify_scenarios`, `scenarios` in `drought_grid.py`; stored under `payload.scenarios`;
shown as the scenario table under the map.

**Question it answers:** given the water balance observed so far, what would SPEI-k be if the coming months
repeated the weather of each recorded year? This is the Ensemble Streamflow Prediction idea (Day, 1985) applied to
SPEI.

* A member is 12 consecutive recorded months starting at the calendar month after the issue month (45 members
  for the 2026-09 run: 1981…2025). The same year is used for all 29 cells, so spatial patterns stay real.
* The observed part of each accumulation window is exact. Only the future months come from history.
* **Warming adjustment:** each member's ET0 is shifted so that the ensemble-mean ET0 of every calendar month
  equals the mean of the last 10 years. Rainfall is used as recorded.
* Outputs per index and lead: 10/25/50/75/90th percentiles, drought chance (share of members with SPEI ≤ −1),
  the driest and wettest analogue year, and the **rain needed to be out of drought**: basin rainfall over the
  remaining months of the window that gives SPEI > −1 with recent ET0, in mm and as % of the 1981–2010 normal.

**Verification** uses the same issue months as the ridge model (2011 → present). For each issue month only years
that ended before it are members, and the ET0 adjustment uses only earlier months. The distribution parameters
come from the 1981–2010 reference, as for the index itself.

| Index | Lead | Scenario AUC | Scenario MSSS | Ridge AUC | Ridge MSSS | 80 % range holds |
|---|---|---|---|---|---|---|
| SPEI-3 | +1 | 0.94 | 0.78 | 0.93 | 0.75 | 77 % |
| SPEI-3 | +2 | 0.83 | 0.51 | 0.80 | 0.41 | 76 % |
| SPEI-3 | +3…+12 | 0.70–0.71 | 0.20 | 0.56–0.68 | 0.04–0.17 | 73–74 % |
| SPEI-6 | +3 | 0.85 | 0.57 | 0.81 | 0.49 | 74 % |
| SPEI-6 | +4 | 0.80 | 0.45 | 0.74 | 0.33 | 74 % |
| SPEI-6 | +5 | 0.70 | 0.33 | 0.66 | 0.18 | 74 % |
| SPEI-12 | +6 | 0.91 | 0.68 | 0.88 | 0.57 | 77 % |
| SPEI-12 | +9 | 0.78 | 0.51 | 0.76 | 0.42 | 77 % |
| SPEI-12 | +10 | 0.74 | 0.42 | 0.72 | 0.35 | 75 % |
| SPEI-24 | +12 | 0.91 | 0.78 | 0.90 | 0.78 | 75 % |

Findings:

* The scenario ensemble is at least as good as the ridge model at every index and lead, and clearly better in
  mean-square terms. Under the publication rule it adds one lead: SPEI-6 at +4.
* Once the whole window is in the future (SPEI-3 at +3 and beyond) the scenarios keep MSSS ≈ 0.20 and AUC ≈ 0.70.
  That is not rainfall forecasting. It is the warming adjustment: today's climate is drier than the 1981–2010
  reference, and the ensemble knows it. AUC stays below the 0.75 rule, so these rows are shown greyed.
* The 80 % range contains the outcome about 75 % of the time: slightly too narrow, acceptable.
* The ridge model can extrapolate when its predictors are outside the training range (SPEI-12 for March 2027:
  ridge −2.05, scenario median −1.09 with a dry case of −1.88; SPEI-12 for December 2026: ridge −1.33, scenario
  median −0.03, where 9 of the 12 months are already observed and even the driest recorded autumn gives −0.78).
  The scenarios cannot, because they only replay weather that has happened. This is why the scenario ensemble
  is the published forecast since model v3.

## 6. What drives a forecast

Because the model is linear in standardised predictors, each forecast decomposes exactly into
`Σ coefficient × standardised value`, expressed in SPEI units relative to the mean state. The UI groups the terms
as follows:

| Driver group | Predictors |
|---|---|
| Long-term deficit already accumulated | SPEI-6 and SPEI-12, with lags |
| Recent water balance | SPEI-1 and SPEI-3, with lags |
| Last month rainfall anomaly | P anomaly |
| Evaporative demand / heat | ET0 and temperature anomalies |
| Soil moisture | 0–28 cm, now and 1 month back |
| Season of the target month | sin/cos |

Typical shares of attribution: SPEI-3 at +1 is dominated by SPEI-1 and SPEI-3. SPEI-6 at +3 is driven by
SPEI-3 now. SPEI-12 at +6 is driven by SPEI-6 now. Rain, heat and soil anomalies add little once the SPEI terms
are known, because they are largely already contained in them.

## 7. Known limits

* **Non-stationarity:** months with SPEI ≤ −1 made up 32 % of 2011–2026, against the nominal 16 %. The reason is
  that ET0 has risen relative to the 1981–2010 reference. "Drought" therefore means drier than the 1981–2010
  climate. This is the WMO convention, but it explains why dry classes dominate recent maps.
* **Summer SPEI-3 is mainly an ET0 (heat) signal,** because there is almost no rain to vary. Use SPEI-6 or
  SPEI-12, or restrict SPEI-3 decisions to Oct–May. In the dry season SPEI-3 at +2 has R² = 0.02, against
  0.38 in the wet season.
* **Resolution:** 0.1° cells (about 9 × 11 km). Field-scale differences in soil, irrigation and slope are not
  resolved.
* **Single reanalysis:** ET0 comes from ERA5-Land only. Reanalysis temperature and humidity biases cancel largely
  but not entirely in the standardisation.

## 8. Operations

* `python manage.py build_drought_grid` fetches new months (re-downloading the last 3 to pick up CHIRPS
  revisions), re-verifies, and publishes a `DroughtGridForecast` row. A full first run takes about 3 minutes.
* `--no-fetch` rebuilds from stored data. `--no-verify` reuses the previous skill table (fast, but the skill is
  then not refreshed).
* The command also runs inside the monthly Celery task `monthly_spei_forecast`.
* The command needs Earth Engine credentials (`GEE_CREDENTIALS_FILE`), as for `backfill_climate_monthly`.
* New static files (`drought_grid_map.js`, `drought_grid.css`) need `collectstatic` wherever
  `DEBUG=False` (manifest storage).
