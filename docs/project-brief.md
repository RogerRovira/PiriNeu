---
schema: project-brief/v1
created: 2026-07-12
status: confirmed
project_name: previsio-neu-pirineu
---

# Project Brief: Previsió de Neu al Pirineu Català

## Pitch
A non-commercial web dashboard that forecasts 48-hour snowfall and snow line (cota de neu) for Baqueira Beret, Boí Taüll and La Molina by blending high-resolution local weather sources, with honest confidence labels.

## Description
A simple web page shows, for each of the three resorts, the expected new snow and snow line for the next 48 hours with a confidence label (Alta/Mitjana/Baixa) and mandatory source attribution. Under the hood, it builds a wind-regime-weighted consensus of AROME (via Open-Meteo), AEMET and Meteocat forecasts, corrected in near-real-time with XEMA station observations.

## Target user & problem
- **Who:** skiers and mountain users of the three Catalan Pyrenees resorts (starting with the author) planning trips 0–2 days ahead
- **Problem:** generalist snow sites run coarse global model chains with no local data assimilation, giving unreliable snow and snow-line forecasts in complex Pyrenean terrain
- **Today they:** cross-check snow-forecast.com, Meteocat and AEMET manually and guess between disagreeing sources

## Core loop
User opens a resort's page → sees the 48h new-snow and snow-line forecast with its confidence label → decides whether and where to go.

## Scope

### v1 features (3–5)
1. Three-leg ingestion (Open-Meteo/AROME, Meteocat zonal + pics/refugis, AEMET GeoTIFF/GeoJSON) into SQLite long format — done when: scheduled runs persist all three legs daily, with raw payloads archived before parsing
2. Regime-weighted 48h consensus (new snow + derived snow line, per resort) — done when: consensus values are computed per forecast block for all 3 resorts using the documented N-flow/S-flow weighting
3. Confidence labels from inter-model spread — done when: every forecast block carries Alta/Mitjana/Baixa from the documented matrix
4. XEMA nowcast correction — done when: next-hours forecast adjusts when observations diverge from all model legs
5. Read-only web dashboard — done when: each resort's page shows snow, cota, confidence and required attributions

### Later (not v1)
- 72/96h window with `arpege_europe` + ensembles — why deferred: AROME/Meteocat reach ~48h natively; spread-based confidence works better at longer ranges
- ECMWF as consensus member — why deferred: only relevant once the window expands
- Port Ainé (4th resort) — why deferred: simplifies launch; revisit later
- Snow-persistence proxies (wind-transport flag, freeze-thaw counts, degree-day melt) — why deferred: exploratory, pragmatic path only
- 10-day "outlook" — likely never: can't beat ECMWF/GFS convergence at that range

### Non-goals
- No GRIB2 pipelines anywhere — reason: GeoTIFF/GeoJSON/JSON cover everything
- No full snowpack modeling (Crocus/SNOWPACK) — reason: separate research project; proxies at most, in later phases
- No ground snow-depth prediction — reason: model `snow_depth` is unreliable in complex terrain; the consensus predicts NEW snowfall only
- No Open-Meteo `precipitation_probability` in the consensus — reason: it comes from a 27 km ensemble and contaminates the high-res chain; probability comes from Meteocat
- No commercial use or monetization — reason: source licensing (Open-Meteo CC-BY; AEMET and Meteocat attribution mandatory) and project intent

## Complexity flags
- **Heavy third-party data dependencies** (credentials, quotas, publication lags, undocumented quirks) — decision: accepted knowingly; mitigated by raw-payload archiving before parsing, disk caches, call caps (`MAX_NEW_CALLS`), and collect-forward from day 1
- **Web presentation layer** — decision: simplified to a read-only dashboard; no accounts, no auth, no user data

## Stack decision
- **Choice:** Python 3; SQLite in long format `(station, run_time_utc, valid_time_utc, variable, value)` with idempotent upserts; rasterio (+ pyproj if needed) for AEMET rasters; cron-scheduled ingest scripts; a minimal read-only web dashboard (static generation or micro-framework — exact approach TBD); UTC in storage, local time only in presentation; secrets via env vars
- **Context:** single technical maintainer fluent in Python; small single-writer data volume; all sources are REST/file downloads; system must be rebuildable from archived raw payloads
- **Alternatives considered:**
  - GRIB2-based toolchain — rejected because GeoTIFF/GeoJSON/JSON serve every need at far lower complexity
  - AEMET OpenData REST API for gridded data — rejected because it serves PNG images only
  - Native `freezing_level_height` from meteofrance_seamless — rejected because it returns null; snow line is derived from pressure-level temperature crossings instead
- **Consequences:** easier — zero-ops storage, idempotent re-runs, full rebuild from raw archive; harder — single-writer SQLite limits concurrency (acceptable at this scale); dashboard technology still open (TODO before Milestone 3)

## Working constraints
- **Knows:** Python; REST APIs; the meteorological domain (models, assimilation, verification)
- **New to:** Unknown — not stated in handoff
- **Team:** solo
- **Time budget:** Unknown — not stated in handoff
- **AI workflow:** AI-assisted development; specific tools not stated
- **Testing appetite:** verification-oriented (dedicated verification scripts, planned metrics); formal test habits Unknown
- **Git habits:** Unknown — not stated in handoff
- **Deploy target:** VPS or home Raspberry Pi — undecided (open question); cron + off-machine backups from day 1 either way

## Milestones (rough)
1. **Data safety + collect-forward:** raw-payload archiving wrapper, cron aligned to source rhythms, failure alerting; daily ingestion of available legs begins (protects irreplaceable data)
2. **Full three-leg ingestion + normalization:** Meteocat historics verified when credentials arrive; placeholder coordinates replaced with canonical pics-metadades coords; AEMET reconnaissance then ingest; unit and elevation-semantics normalization
3. **v1 complete:** regime-weighted consensus, hand-tuned confidence matrix, XEMA nowcast correction, dashboard live with attributions — all v1 acceptance checks pass

## Open questions & risks
- Does Meteocat serve archived past forecasts? (decides training bootstrap vs collect-forward; script ready, blocked on credentials)
- AEMET operational unknowns: publication lag, file retention, raster CRS, nodata handling
- XEMA station selection per resort (codes, variables, altitudes, gauge undercatch 20–50% in windy snowfall)
- Semantic normalization spec: canonical unit (SWE mm proposed), accumulation windows, Meteocat bucket mapping, AEMET mm→cm snow ratio
- Elevation semantics: canonical base/mid/top per resort mapped across sources
- Staleness/degraded-mode policy with 2 of 3 legs or stale legs
- Deployment target choice (VPS vs Raspberry Pi)
- Verification metrics to fix before calibration: MAE on 24h accumulation, hit/false-alarm on snow days, cota error in meters
- Risk: consensus weights are prior-based and unverified — schema (run_time vs valid_time) exists so the system can measure and correct itself

## Confirmation
- User confirmed this brief: yes, 2026-07-12
- Notable pushback during discovery: none; Phase 1 consumption surface clarified as a simple web dashboard
