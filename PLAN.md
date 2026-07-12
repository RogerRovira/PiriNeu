# Plan — Previsió de Neu al Pirineu Català

Core loop: user opens a resort's page → sees the 48h new-snow and snow-line
forecast with its confidence label → decides whether and where to go.

## Milestone 1: Data safety + collect-forward
Protects irreplaceable data — everything else can be rebuilt from it.
- [x] Raw-payload archiving wrapper: persist every raw JSON/GeoTIFF/GeoJSON
      compressed and dated BEFORE parsing — done when: every ingest run
      archives its payloads and SQLite is demonstrably rebuildable
      (`archive.py` + `rebuild_db.py`; parity covered by tests)
- [ ] Cron scheduling aligned to source rhythms (Meteocat ~14:00 local
      daily; AEMET 00/06/12/18 UTC + lag; Open-Meteo hourly) + failure
      alerting — done when: a silent failure raises an alert
      (code ready: `cron.example` + `healthcheck.py`; done once installed
      on the deploy machine — deployment target still an open question)
- [ ] Start collect-forward daily ingestion of available legs — done when:
      data accumulates daily regardless of the Meteocat historics outcome
      (Open-Meteo leg ready to run; starts accumulating once cron is live)

## Milestone 2: Full three-leg ingestion + normalization
- [x] Run `verify_meteocat_historics.py` when credentials arrive; record the
      archived/recomputed/404 outcome — resolves open question 1.
      RESULT 2026-07-12: **no historics** (outcome C, via HTTP 400 rather
      than 404). Zone and pic endpoints serve ONLY a rolling 3-day window
      — the 400 body says it outright: "Els dies disponibles són:
      12-07-2026, 13-07-2026 i 14-07-2026". Every past date (yesterday,
      -7d, -30d, -365d, 2017) fails for both endpoint families;
      `dataPublicacio` on the served days is same-day (~08:42Z). No
      bootstrap archive → collect-forward only, XEMA daily endpoints as
      ground truth. Report: `verification_report.json`.
- [x] Replace placeholder coordinates with canonical pics-metadades coords
      — done in `config.py` 2026-07-12 (anchor peaks Cap de Vaquèira,
      Pica de Cerví, La Tosa d'Alp). Metadades carries NO elevation field,
      so `elevation_m` is the Open-Meteo elevation API (90 m DEM) value at
      the canonical points: 2458 / 2710 / 2526 m.
- [x] AEMET reconnaissance (publication lag, retention, CRS, nodata) —
      resolves open question 2; findings recorded under "Open questions"
      below and in `data/aemet_recon_report.json`. Headline: the GeoTIFFs
      are colormapped RGBA images, values only recoverable as legend bins.
- [ ] Refine Meteocat parsers against real payload shapes
      (done 2026-07-12: franja windows, variablesValors, zone scheme fix,
      per-cota pics) — re-verify the winter-only fields (acumulacioNeu,
      cota with valor; la_molina zone id) on the first snowfall payload
- [ ] AEMET ingest leg: GeoTIFF pixel extraction + wind GeoJSON → SQLite.
      Now shaped by the recon: decode pixel RGBA → bin via the embedded
      `ESCALA` GDAL tag per file (values are BINS, e.g. precip 0.5–1 mm,
      not continuous); nearest `ang_viento` GeoJSON point for direction;
      fetch each run within its ~6 h cycle (no retention).
- [ ] Normalization + elevation-semantics layer (canonical unit, windows,
      bucket mapping, base/mid/top per resort) — resolves open questions 4–5
      (`normalize.py` has the SWE-mm unit, 24/48 h windows and provisional
      elevation bands; Meteocat zonal categorical codes — cel, intensitat,
      probabilitat, tempesta, visibilitat — now flow into SQLite as numeric
      codes awaiting the bucket map; AEMET snow ratio still open)

## Milestone 3: v1 complete
All acceptance checks in the project brief pass.
- [ ] Regime-weighted consensus (N flows → AROME; S/E flows → AEMET+Meteocat)
      per forecast block, all 3 resorts
- [ ] Confidence matrix with hand-tuned initial thresholds; validate derived
      isozero vs Meteocat (~100–200 m on storm days), absorb systematic bias
- [ ] XEMA nowcast correction (mind Meteocat quota — polling multiplies calls)
- [ ] Read-only dashboard with snow, cota, confidence and attributions
      <!-- TODO: decide dashboard tech (static vs micro-framework) first -->

## Backlog (explicitly not v1)
- 72/96h window with `arpege_europe` + ensembles — spread-based confidence
  works better at longer ranges
- ECMWF as consensus member — only once the window expands
- Port Ainé (4th resort) — simplifies launch; revisit later
- Snow-persistence proxies (wind-transport flag, freeze-thaw, degree-day
  melt) — pragmatic path only
- 10-day "outlook" — likely never

## Open questions
- ~~Meteocat archived forecasts?~~ RESOLVED 2026-07-12: none — rolling
  3-day window (today..D+2), past dates HTTP 400. Collect-forward only;
  XEMA (historical) is the verification ground truth. See Milestone 2.
- ~~AEMET operational unknowns (lag, retention, CRS, nodata)~~ RESOLVED
  2026-07-12 (12 UTC run, `aemet_recon.py`, `data/aemet_recon_report.json`):
  - Format: the entry point serves one tar.gz (`application/tar+gzip`,
    ~22 MB for PB) with 440 files: 48 hourly steps (run+1h..run+48h) ×
    6 GeoTIFF fields + 2 GeoJSONs, plus 3h/6h precip aggregates. Fields:
    11=temperature, 32=wind speed, 61=precip (1HH/3HH/6HH), 71=cloud
    cover, plus local codes 207 (range 0.001–0.2, likely snow in m) and
    228 (0–140, likely gust km/h) — both have CAMPO mislabeled "press";
    confirm on a winter run. Wind direction arrives as GeoJSON points
    (`ang_viento`), pressure as GeoJSON isobar lines (`pres_Pa`).
  - Lag: PB bundle for the 12 UTC run was built 14:44 UTC → **~2¾ h**
    (Canarias ~2 h); no Last-Modified header, gzip mtime is the signal.
  - Retention: **latest run only** — no date/run parameters discovered at
    the entry point, so each 00/06/12/18 run must be fetched within its
    6 h cycle (collect-forward; a missed cycle is unrecoverable).
  - CRS: EPSG:4326 as documented (PB grid 640×400 at 0.025°, bounds
    -11.0125..4.9875 E, 34.4875..44.4875 N) — all three resorts inside.
  - Nodata: none declared. The rasters are **RGBA uint8 colormapped
    images, not data grids**: numeric values are recoverable only as the
    legend bins in each file's `ESCALA` GDAL tag (RGBA → value range);
    the zero bin renders transparent (alpha 0). Consensus inputs from
    AEMET are therefore binned, not continuous. Mandatory attribution
    ships in the `USO` tag.
- XEMA station selection per resort + gauge undercatch handling (20–50%)
- Semantic normalization spec (SWE mm proposal, windows, bucket mapping,
  snow ratio)
- Elevation semantics (canonical base/mid/top per resort)
- Staleness/degraded-mode policy (2 of 3 legs, stale legs)
- ~~Deployment target: VPS vs Raspberry Pi~~ RESOLVED 2026-07-12:
  Raspberry Pi, on hold until the hardware arrives — then install
  cron.example and off-machine backups on day 1
- Verification metrics before calibration: MAE on 24h accumulation,
  hit/false-alarm on snow days, cota error in meters
- Risk: consensus weights are prior-based and unverified — the run_time vs
  valid_time schema exists so the system can measure and correct itself

## Maintenance reminders
- CLAUDE.md: add a Gotcha when an agent repeats a mistake.
- README: update Features when a milestone lands.
- docs/adr/: new ADR for any hard-to-reverse decision.
- CHANGELOG: start filling at first release.
