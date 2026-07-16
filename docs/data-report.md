# Data report — what the predictions use today, and what could improve them

Status: written 2026-07-16 (pre-first-winter). Audience: project maintainer.
Scope: (1) a complete inventory of the data currently feeding the 48h
snow/cota consensus, (2) data already ingested or archived but not yet used,
(3) data available upstream but not fetched, and (4) extra computation or
frameworks that would raise skill without violating the project's non-goals
(no GRIB2, no snowpack modeling, no ground snow-depth prediction, no
Open-Meteo `precipitation_probability`, non-commercial only).

---

## 1. The pipeline at a glance

```
Open-Meteo (AROME/meteofrance_seamless) ─┐
AEMET Harmonie-AROME (download bundle)  ─┼─► SQLite long format ─► consensus.py ─► dashboard
Meteocat pronostic (zonal + pics)       ─┤   (station, run_time,     │
XEMA observations (6 stations)          ─┘    valid_time, var, val)  └─ confidence (Alta/Mitjana/Baixa)
```

Every raw payload is archived (compressed, dated) before parsing; SQLite is
a rebuildable view (`rebuild_db.py`). The consensus blends the latest fresh
run (< 30 h) of each forecast leg into two calendar-day blocks (D0, D1) per
resort, weighted by wind regime, and stores every per-leg input beside the
blend so the priors can be verified and re-tuned later.

Consensus outputs per (resort, day): `snow_swe_mm`, `cota_m`, `confidence`,
`regime`, `n_legs_snow`, plus `leg.<source>.snow_swe_mm` / `leg.<source>.cota_m`.

---

## 2. Part I — Data currently used by the predictions

### 2.1 Open-Meteo / AROME leg (`openmeteo_ingest.py`)

One multi-location call per hour, `models=meteofrance_seamless`,
`forecast_days=4`, explicit `&elevation=` per resort (disables 90 m DEM
downscaling, keeps comparability with the AEMET pixel). `run_time` = fetch
time (Open-Meteo does not expose the model run time).

| Variable (as stored) | Cadence | Used in consensus? | Role |
|---|---|---|---|
| `snowfall_sum` (daily, cm) | daily | **yes** | new-snow leg: cm × 10/7 → SWE mm (7:1 documented ratio) |
| `snowfall` (hourly, cm) | hourly | fallback | same, when the daily block is missing |
| `temperature_{1000,925,850,700}hPa` | hourly | **yes (derived)** | inputs to the derived isozero |
| `geopotential_height_{1000,925,850,700}hPa` | hourly | **yes (derived)** | real heights for the 0 °C interpolation |
| `freezing_level_derived` (derived at ingest) | hourly | **yes** | cota leg: mean over precip hours − 300 m |
| `freezing_level_capped` (derived flag) | hourly | no | stored, never read |
| `precipitation` (hourly, mm) | hourly | partially | only as the "wet hours" mask for the cota mean |
| `wind_direction_700hPa` | hourly | **yes** | regime classifier, 2nd priority |
| `wind_speed_700hPa` | hourly | no | — |
| `temperature_2m`, `relative_humidity_2m`, `wet_bulb_temperature_2m` | hourly | no | ingested, unused |
| `rain` (hourly) | hourly | no | ingested, unused |
| `wind_speed_10m`, `wind_direction_10m`, `wind_gusts_10m` | hourly | no | ingested, unused |
| `precipitation_sum` (daily) | daily | no | ingested, unused |

Notes baked into the leg:
- The native `freezing_level_height` is null on `meteofrance_seamless`, so
  the isozero is derived by scanning 1000→700 hPa for the 0 °C crossing;
  inversions take the LOWEST crossing (conservative); a whole-column-≤0 °C
  case caps at the lowest level height (`capped=True`).
- `derive_freezing_level` also computes `n_crossings` (inversion marker),
  but **only `capped` is persisted — `n_crossings` is thrown away** (see §3.6).

### 2.2 AEMET Harmonie-AROME leg (`aemet_ingest.py`)

One tar.gz per 00/06/12/18 UTC cycle (latest run only; ~2¾ h lag; a missed
cycle is unrecoverable). The GeoTIFFs are RGBA **colormapped images** —
values are recovered as legend **bins** via each file's `ESCALA` tag (bin
midpoint; lower edge for the open top bin and the transparent zero bin).
True model run time is derived from the bundle content.

| Variable | Used? | Role |
|---|---|---|
| `grid.precip.1h` (bins, liquid mm = SWE mm) | **yes** | new-snow leg: summed over hours where pixel temp ≤ +1.0 °C (provisional snow gate) |
| `grid.temperature` (bins, °C) | **yes** | the ≤ +1.0 °C gate above |
| `grid.wind_direction` (GeoJSON nearest point) | **yes** | regime classifier, last fallback |
| `grid.precip.3h` / `grid.precip.6h` | no | ingested, unused |
| `grid.wind_speed` | no | ingested, unused |
| `grid.cloud_cover` | no | ingested, unused |
| `grid.f207` (range 0.001–0.2 — likely snow in m) | no | neutral name until a winter run confirms semantics |
| `grid.f228` (range 0–140 — likely gust km/h) | no | same |

AEMET contributes **no cota** (no freezing-level product in the bundle) and
its amounts are quantized to legend bins — both facts matter for the
confidence matrix (§5.6).

### 2.3 Meteocat pronostic leg (`meteocat_ingest.py`)

Hard quota: Predicció plan = **100 calls/month**. Nominal schedule: 2 zonal
dates/day + ONE rotating pics anchor/day (primaries every 6 days,
secondaries every 14) ≈ 92 calls/month. Endpoints serve only a rolling
3-day window — no forecast archive exists, collect-forward only.

| Variable | Used? | Role |
|---|---|---|
| `zonal.cota.6h` (assigned zone) | **yes (winter)** | cota leg, first choice |
| `pic.isozero.totes` (resort's primary anchor) | **yes** | cota fallback: mean − 300 m |
| `pic.direccio_vent.3000` | **yes** | regime classifier, 1st priority |
| `zonal.acumulacioNeu.24h` | wired, **abstains** | new-snow leg — unit unconfirmed until winter (`meteocat_bucket_to_swe_mm` raises) |
| `zonal.probabilitat.*` (precip probability) | no | stored as numeric code; the project's designated probability source, not yet surfaced |
| `zonal.acumulacio.*`, `intensitat`, `tempesta`, `cel`, `visibilitat` | no | stored as numeric codes, no bucket map yet |
| `pic.iso-10.totes` (−10 °C level) | no | ingested on anchor days, unused |
| `pic.temperatura/humitat/velocitat_vent/direccio_vent.{1500,2000,2500,3000}` | mostly no | only `direccio_vent.3000` is read |
| Secondary-anchor pics (Marimanya, Airoto, Gerdar, Filià, Corronco, Puigllançada, Pere Carné) | no | winter-verification samples only |

Zonal rows are stored for ALL 7 zones (`zona_<id>` pseudo-stations); the
resort→zone choice is config (`METEOCAT_ZONE_FOR_STATION`), with
la_molina→6 still LOW confidence pending winter verification.

### 2.4 XEMA observations (`xema_ingest.py`)

6 stations (a HIGH + VALLEY pair per resort), semi-hourly readings, ~43 min
latency, ~3 cycles/day (gated at >8 h staleness; XEMA plan 750 calls/month).
`run_time == valid_time ==` the reading's own timestamp.

| Variable (XEMA code) | Stored | Used in predictions? |
|---|---|---|
| `obs.temperatura` (32) | yes | **not yet** — nowcast correction is the last open v1 item |
| `obs.humitat` (33) | yes | not yet |
| `obs.precipitacio` (35, gauge; 20–50 % undercatch in windy snowfall) | yes | not yet |
| `obs.gruix_neu` (38; Z1, Z2, YN, DP — ZD has no sensor) | yes | not yet (planned new-snow ground truth via deltas) |

**Today the XEMA leg influences nothing.** The consensus is currently pure
forecast blending; the designed correction (pair lapse rate → observed
freezing level, with Cerdanya cold-pool inversion detection at Das) is
specified in PLAN.md but unimplemented.

### 2.5 The consensus's own knobs (hand-tuned priors, all unverified)

| Constant | Value | Risk |
|---|---|---|
| Regime weights | N: 0.50/0.25/0.25 · S/E: 0.20/0.40/0.40 · mixed: ⅓ each | the core prior; no data yet to confirm it |
| Regime sectors | N = 315–45°, S/E = 90–225°, else mixed | boundary flows (e.g. NW 290°) land in "mixed" |
| `ISOZERO_TO_COTA_M` | 300 m fixed | real offset varies with precip intensity/humidity (~200–400 m) |
| `AEMET_SNOW_MAX_TEMP_C` | +1.0 °C on binned pixel temp | provisional until f207 is confirmed |
| Open-Meteo snow ratio | fixed 7:1 | crude; real ratios span ~5:1–15:1 with column temp |
| `MAX_RUN_AGE_HOURS` | 30 h | provisional staleness policy |
| Confidence matrix | leg count ceiling + spread demotions (2 mm / 35 % / 150 m / 300 m) | hand-tuned, unvalidated |

---

## 3. Part II — Already ingested/archived but UNUSED (zero-API-cost wins)

Ordered roughly by (impact ÷ effort). None of these cost a single upstream
call; several only need parsing/consensus changes plus `rebuild_db.py`.

### 3.1 XEMA nowcast correction (planned, biggest single win)
The data is flowing and idle. Implement the designed correction:
observed lapse rate from each high+valley pair → observed freezing level →
blend/nudge the forecast cota for the next hours; snow-depth deltas at
Z1/Z2/YN/DP as new-snow ground truth. Must detect valley inversions (Das
cold pool) and fall back to the high station + standard lapse rate.

### 3.2 Wet-bulb temperature for precipitation phase
`wet_bulb_temperature_2m` is ingested and unused. Rain/snow transition
tracks the **wet-bulb** ~0.5–1.0 °C far better than air temperature or a
fixed isozero−300 m. Cheap uses now:
- resort-level phase check: flag blocks where the consensus says snow but
  the resort-elevation wet-bulb says rain (confidence demotion);
- a station-level "snow at base/mid/top?" indicator for the dashboard.

### 3.3 Column-temperature snow ratio (replace the fixed 7:1)
The 1000–700 hPa temperatures are already stored. A Kuchera-style ratio
(from column max temperature) or even a simple 2 m/850 hPa-based ratio
would replace the fixed 7:1 in `normalize.py` at zero data cost, improving
SWE↔cm consistency between legs (AEMET bins are liquid mm; Open-Meteo
snowfall is cm — right now they are compared through a constant).

### 3.4 Pics fixed-level temperatures (1500/2000/2500/3000 m)
On anchor days Meteocat provides an independent temperature profile at
exactly the elevations that matter. Unused today. Uses:
- cross-validate the Open-Meteo derived isozero (the planned ±100–200 m
  storm-day comparison — the data for it is already accumulating);
- direct per-band (base/mid/top) phase assessment against
  `RESORT_ELEVATIONS_M`.

### 3.5 Meteocat `zonal.probabilitat` → the dashboard
The brief explicitly designates Meteocat as the probability source, and it
is already stored as a numeric code for all zones. Only needs the bucket
map in `normalize.py` and a dashboard field. (Categorical maps for `cel`,
`intensitat`, `tempesta` are the same one-time effort.)

### 3.6 Persist `n_crossings`; use `capped` and inversions in confidence
`derive_freezing_level` already detects inversions (`n_crossings > 1`) but
the value is discarded at ingest, and `freezing_level_capped` is stored but
never read. Inversion cases are precisely where cota forecasts bust —
storing `n_crossings` (one line in `openmeteo_ingest.py`) and demoting
confidence (or widening the cota band) when flagged is nearly free. This
also feeds the Das cold-pool detector in §3.1.

### 3.7 Lagged-run "poor man's ensemble" from the DB itself
The schema retains every run. Run-to-run jumpiness of a leg for the same
valid day is a classic skill/uncertainty signal, available with a single
SQL query — no new data. Use: a "trend/consistency" demotion or bonus in
the confidence matrix (e.g. if the last 3 Open-Meteo runs moved the D1
snowfall 20→5→18 mm, that block is not "Alta" no matter the leg agreement).

### 3.8 AEMET internal consistency + dormant fields
- `grid.precip.3h/6h` can validate the binned 1h decode (sums should
  bracket the aggregates given bin widths) — a cheap decode-sanity monitor.
- Winter action item already planned: confirm `f207` (likely snow depth/
  accumulation in m) and `f228` (likely gusts) on the first winter run —
  f207 would give AEMET a native snow field, retiring the +1 °C gate.
- `grid.wind_speed` + `grid.cloud_cover`: inputs for later persistence
  proxies (wind transport) and for the dashboard.

### 3.9 Re-parse richer XEMA payloads from the archive
The archived station-day payloads contain **every variable the station
measures**, but only codes 32/33/35/38 are parsed. Extending
`xema_ingest.VARIABLES` + one `rebuild_db.py` run backfills, with zero API
cost, everything already fetched since 2026-07-14. Candidates present in
the XEMA catalog (`xema_recon` captured them in
`variable_catalog_interesting` — confirm exact codes there):
- **wind speed/direction** at the high stations → gauge-undercatch
  correction factor (the open 20–50 % question) and a wind-transport flag
  later;
- station pressure → lapse-rate/inversion diagnostics;
- any radiation/ground-temp variables → future melt proxies (backlog).

---

## 4. Part III — Available upstream but NOT fetched

### 4.1 Open-Meteo (same free non-commercial API — highest leverage)

1. **Pressure-level relative humidity** (`relative_humidity_{1000,925,850,700}hPa`).
   Enables a **wet-bulb freezing level** instead of dry isozero − 300 m:
   compute Tw per level from T+RH, scan for the Tw ≈ 0.5 °C crossing with
   the same interpolation code. This directly replaces the crudest constant
   in the cota chain with physics, at the cost of a longer URL. The 300 m
   offset stays only as the Meteocat-isozero fallback.
2. **More pressure levels** (600, 500 hPa). The current top is 700 hPa
   (~3 000 m): warm SW flows can push the isozero above it, where today the
   scan silently fails (column all >0 °C → None) or extrapolates poorly.
   Two more levels close that hole and cost nothing.
3. **Previous Runs API** (`previous-runs-api.open-meteo.com`): serves what
   each model predicted 24/48/…h before valid time (`_previous_day1..7`
   suffixes), including Météo-France AROME, archived from ~Jan 2024.
   This is the **verification bootstrap the project lost when Meteocat
   turned out to have no forecast archive**: forecast-vs-forecast lag
   comparisons and (with XEMA obs) real skill-by-lead-time curves without
   waiting a full season of collect-forward.
4. **Historical Forecast API**: the same operational forecasts archived as
   a continuous series (models from ~2022–2024 depending on model,
   pressure-level variables included). Combined with XEMA's historical
   daily endpoints (already accessible under the 750/month plan), this
   allows **pre-tuning the regime weights and confidence thresholds on
   past winters before the first live one** — the single biggest de-risking
   of the "priors are unverified" item. One-off bulk pulls, cacheable,
   free for non-commercial use.
5. **Explicit model split**: `meteofrance_seamless` silently blends AROME
   (~1.5 km, ≤ ~2 days) and ARPEGE (coarser, beyond). Requesting
   `arome_france_hd,arome_france,arpege_europe` explicitly would (a) tell
   you which model actually produced each hour, (b) give a clean AROME-only
   leg for the 48h window and an ARPEGE leg ready for the backlog 72/96h
   extension. Slightly larger payloads, same call count.
6. **A fourth consensus leg for regime diversity**: ICON-EU and ECMWF IFS
   are served by the same API. The consensus's weakness is that all three
   current legs are AROME-family (Open-Meteo AROME, AEMET Harmonie-AROME,
   and Meteocat's products are AROME-informed) — correlated errors inflate
   "Alta" confidence. One truly independent model family (ICON or IFS025)
   as a low-weight fourth leg makes the spread-based confidence honest.
   Backlog-adjacent (the brief defers ECMWF), but the marginal cost is one
   more model name in a URL.
7. **Ensemble APIs** (AROME/ARPEGE EPS, IFS ENS): deferred by the brief to
   the 72/96h milestone — noted here as the designated path for
   probabilistic confidence, NOT `precipitation_probability` (non-goal).

### 4.2 AEMET OpenData REST API (separate free API key; distinct from the download server)

The project currently uses only the model-raster download server. The REST
API (free key, generous quotas) has products the bundle lacks:

1. **Mountain forecast, Pirineo Catalán** (`prediccion/especifica/montaña/…`,
   area `cat1`, elaborated by human forecasters): includes free-atmosphere
   **0 °C and −10 °C isotherm altitudes** and expected snow behavior —
   an independent, expert-corrected cota signal and a natural
   cross-check/tiebreaker for the S/E-regime blend. JSON/text, 2×/day.
2. **Municipal daily forecasts** (Naut Aran, Vall de Boí, Alp/La Molina):
   carry a **snow-line field (`cotaNieveProv`)** per period — a second
   direct cota product (verify exact field name on first fetch).
3. **AEMET conventional observations** (`observacion/convencional/…`):
   AEMET stations on the Spanish side (e.g. Vielha area) as redundancy for
   XEMA outages, and independent verification obs that don't spend the
   Meteocat quota.
4. **Nivológica** (avalanche/snow bulletin for the Catalan Pyrenees) —
   qualitative winter context for the dashboard (attribution required).

All JSON — no GRIB2, so the non-goal is respected.

### 4.3 Meteocat (quota-constrained — spend only after the budget math)

- **More XEMA stations** within the 750/month plan: the current 6-station,
  ~3-cycle/day schedule uses ~570 calls. Adding 1–2 stations (e.g. a
  Pallars high station between Baqueira and Boí such as Espot or Salòria —
  confirm codes via the cached `estacions/metadades`) costs ~95–190
  calls/month and buys spatial redundancy where the terrain gradient is
  steepest. Alternatively swap Das for Castellar de n'Hug (the documented
  alternate) if the cold pool proves fatal.
- **Quota upgrade**: Meteocat's plans are applied for, not bought — if a
  higher Predicció tier is ever granted, daily pics for all three primary
  anchors (isozero ×3/day instead of a 6-day rotation) is the first thing
  the rotation is currently sacrificing.
- **Lightning (XDDE) / radar products** exist on other plans; marginal for
  a 48h snow product — noted for completeness only.

### 4.4 Independent verification & context sources (new frameworks, small)

- **Copernicus HR Snow & Ice (FSC, 20 m, Sentinel-2)** and/or **MODIS
  MOD10A1 (daily, 500 m)**: satellite fractional snow cover. After each
  storm, the observed **regional snow-line elevation** (snow-cover fraction
  vs elevation using a DEM) verifies the forecast cota — the one consensus
  output that currently has NO planned ground truth (XEMA gives point snow
  depth, not a snow line). A once-daily download + a small raster/DEM
  histogram job; free, attribution required. This is verification, not
  snowpack modeling, so it stays inside the non-goals.
- **ERA5 / ERA5-Land reanalysis** (via Open-Meteo Historical Weather API or
  CDS): climatological priors — per-resort lapse-rate distributions,
  isozero–cota offset statistics by humidity/intensity, regime frequencies.
  One-off pulls to calibrate constants, not an operational dependency.
- **Avalanche bulletins**: Lauegi (Val d'Aran, open-source ALBINA stack,
  JSON/CAAML) and the ICGC/Meteocat BPA — qualitative "context" panel for
  the dashboard, clearly attributed. No prediction role.
- **Resort snow reports / webcams**: tempting ground truth but scraping has
  licensing problems — recommend AGAINST, consistent with project posture.

---

## 5. Part IV — Extra computation & frameworks on data already (or nearly) in hand

### 5.1 A verification module (`verify.py`) — the enabling investment
PLAN.md already names the metrics; the schema was designed for them. Compute,
per leg and per consensus, rolling: MAE on 24h SWE, hit/false-alarm/POD/FAR
on snow days (threshold e.g. ≥1 mm SWE), cota MAE in metres vs (a) XEMA
pair-derived freezing level, (b) satellite snow line if §4.4 lands. Publish
a small verification page on the dashboard ("honest labels" extends
naturally to "honest scores"). Everything below depends on this existing.

### 5.2 Data-driven weights (replace hand priors when n allows)
With `leg.*` inputs + verification pairs accumulating, re-fit:
- first: **inverse-MAE weights per regime** (closed form, robust at n≈dozens);
- later: regularized logistic/ridge regression for regime-conditional
  weights (scikit-learn or plain numpy — keep it inspectable);
- explicitly NOT deep learning: three resorts × two blocks × one winter is
  a few hundred samples; anything with more than ~10 parameters will
  overfit. The Historical Forecast API bootstrap (§4.1.4) multiplies the
  sample size by several winters and is the only way to fit anything
  non-trivial before 2027.

### 5.3 Kalman-filter (MOS-style) bias correction per station
A 1D Kalman filter per (resort, variable) on forecast−observation errors
(temperature at the high station, derived cota vs pair-derived freezing
level) is the classic post-processing step for exactly this data volume:
a handful of state variables, updates daily, needs no training set, adapts
through the season. Cheap to implement in numpy; huge literature; fits the
"straightforward, well-documented" convention.

### 5.4 Physics upgrades to the two crudest constants
- **Wet-bulb cota** (§4.1.1) replaces `ISOZERO_TO_COTA_M = 300`;
- **Kuchera-style snow ratio** (§3.3) replaces the fixed 7:1;
- **Bin-aware AEMET uncertainty**: AEMET amounts are bin midpoints — carry
  the bin half-width into the confidence spread test instead of treating
  binned values as exact (currently a 0.5–1 mm bin can fake "disagreement"
  or fake "agreement" depending on midpoints).

### 5.5 Regime classifier hardening
Today: circular mean of one direction series, three fixed sectors, single
source priority chain. Cheap upgrades: (a) require a minimum upper-wind
SPEED (already ingested: `wind_speed_700hPa`, `pic.velocitat_vent.3000`)
before trusting a direction — light-wind days are "mixed" by definition;
(b) precipitation-weighted circular mean (the regime during the storm hours
is what matters); (c) log the classified regime vs verification so sector
boundaries become tunable.

### 5.6 Confidence matrix v2
Inputs it should gain, all discussed above: inversion flag (§3.6),
run-to-run consistency (§3.7), AEMET bin widths (§5.4), leg independence
(don't count two AROME-family legs agreeing as strongly as two independent
families — relevant if §4.1.6 lands), and eventually calibrated mapping
(fraction of "Alta" blocks that verify should be measurably higher than
"Mitjana" — report it on the verification page).

### 5.7 Frameworks — deliberately boring
- pandas + numpy for verification/fitting (already implied by the stack);
- scikit-learn only when §5.2 graduates past inverse-MAE;
- `properscoring`/CRPS only if ensembles (backlog) land;
- rasterio (already a dependency) covers the satellite FSC job — with a
  ~30 m DEM tile (e.g. Copernicus GLO-30) cropped to `CROP_BOUNDS`;
- no new database, no workflow engine, no ML platform — GitHub Actions +
  SQLite remain sufficient at this data volume (ADR-0001/0002 hold).

---

## 6. Prioritized roadmap (impact × cost, quota-aware)

| # | Item | New data? | API cost | Effort | Season-gated? | Impact |
|---|---|---|---|---|---|---|
| 1 | XEMA nowcast correction (§3.1) | no | 0 | M | no | ★★★★★ — last v1 item, data already idle |
| 2 | Verification module (§5.1) | no | 0 | M | partly | ★★★★★ — enables everything else |
| 3 | Pressure-level RH → wet-bulb cota + levels 600/500 (§4.1.1–2) | yes (same call) | 0 | S | no | ★★★★ |
| 4 | Persist `n_crossings`; inversion + consistency in confidence (§3.6–3.7) | no | 0 | S | no | ★★★ |
| 5 | Kuchera snow ratio + AEMET bin-width handling (§3.3, §5.4) | no | 0 | S | no | ★★★ |
| 6 | Historical Forecast / Previous Runs bootstrap for weight pre-tuning (§4.1.3–4, §5.2) | yes (one-off) | 0 (free tier) | M | no | ★★★★ |
| 7 | Meteocat probability + categorical bucket maps to dashboard (§3.5) | no | 0 | S | winter to verify | ★★★ |
| 8 | XEMA extra variables re-parse (wind → undercatch) (§3.9) | no | 0 | S | no | ★★★ |
| 9 | AEMET REST leg: mountain forecast (iso-0) + municipal cota (§4.2) | yes | new free key | M | no | ★★★ |
| 10 | Winter confirmations: f207/f228, acumulacioNeu units, la_molina zone | no | 0 | S | **yes** | ★★★★ (unblocks legs) |
| 11 | Satellite snow-line verification (FSC/MODIS + DEM) (§4.4) | yes | free | L | winter | ★★★ |
| 12 | Kalman bias correction (§5.3) | no | 0 | M | needs obs season | ★★★ |
| 13 | Fourth independent leg (ICON-EU/IFS via Open-Meteo) (§4.1.6) | yes (same call family) | 0 | M | no | ★★ (confidence honesty) |
| 14 | Explicit AROME/ARPEGE model split (§4.1.5) | yes (same call) | 0 | S | no | ★★ (also preps 72/96h backlog) |

Standing constraints to respect while executing any of it: Meteocat
Predicció 100 calls/month (never add a recurring pronostic call without
redoing the budget), XEMA 750/month, archive-before-parse, UTC storage,
attribution in every user-facing output, and the documented non-goals.

## 7. External references

- Open-Meteo Previous Runs API: <https://open-meteo.com/en/docs/previous-runs-api>
  (announcement: <https://openmeteo.substack.com/p/weather-forecasts-from-previous-model-runs>)
- Open-Meteo Historical Forecast API: <https://open-meteo.com/en/docs/historical-forecast-api>
- Open-Meteo Météo-France models: <https://open-meteo.com/en/docs/meteofrance-api>
- AEMET OpenData (REST, free key): <https://opendata.aemet.es/> — mountain
  forecast Pirineo Catalán = area `cat1` (web product:
  <https://www.aemet.es/en/eltiempo/prediccion/montana?p=cat1>)
- Copernicus High-Resolution Snow & Ice (FSC): <https://land.copernicus.eu/en/products/snow>
- MODIS MOD10A1 snow cover: <https://nsidc.org/data/mod10a1>
- Lauegi Val d'Aran avalanche bulletin (ALBINA/CAAML): <https://lauegi.report>
