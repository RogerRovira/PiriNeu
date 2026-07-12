# Plan — Previsió de Neu al Pirineu Català

Core loop: user opens a resort's page → sees the 48h new-snow and snow-line
forecast with its confidence label → decides whether and where to go.

## Milestone 1: Data safety + collect-forward
Protects irreplaceable data — everything else can be rebuilt from it.
- [x] Raw-payload archiving wrapper: persist every raw JSON/GeoTIFF/GeoJSON
      compressed and dated BEFORE parsing — done when: every ingest run
      archives its payloads and SQLite is demonstrably rebuildable
      (`archive.py` + `rebuild_db.py`; parity covered by tests)
- [ ] Scheduling aligned to source rhythms (Meteocat ~14:00 local daily;
      AEMET 00/06/12/18 UTC + lag; Open-Meteo hourly) + failure alerting
      — done when: a silent failure raises an alert.
      Deployment is GitHub Actions (ADR-0002): `.github/workflows/ingest.yml`
      runs hourly, gates each leg by UTC hour, commits raw archive + SQLite
      + HTTP cache to the `datastore` branch (auto-bootstrapped), and the
      08 UTC healthcheck makes silent failures loud. Done once the PR
      merges to main and `METEOCAT_API_KEY` (+ optional `ALERT_WEBHOOK_URL`)
      are set as repo Actions secrets.
- [ ] Start collect-forward daily ingestion of available legs — done when:
      data accumulates daily regardless of the Meteocat historics outcome
      (all three legs ready; starts accumulating with the first scheduled
      Actions runs after merge)

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
- [x] Refine Meteocat parsers against real payload shapes
      (2026-07-12: franja windows, variablesValors string valors, per-cota
      pics). Zone mapping REDONE from scratch the same day: the endpoint
      uses its own 7-zone scheme and provides NO geometry, so zonal rows
      are now stored for ALL zones under `zona_<id>` pseudo-stations and
      the resort→zone assignment is pure config
      (`config.METEOCAT_ZONE_FOR_STATION`), revisable without re-ingest.
      Ingest alerts on zone rename/renumber drift.
- [ ] Confirm the resort→zone assignment on winter data
      (`verify_meteocat_zones.py`: ranks zones by how well their
      `zonal.cota` tracks each anchor peak's isozero — no API calls).
      baqueira→1 and boi_taull→5 are well supported; la_molina→6 is LOW
      confidence (zones 4/8 plausible). Also re-verify the winter-only
      fields (acumulacioNeu/cota valors) and their units then.
- [x] AEMET ingest leg (`aemet_ingest.py`, 2026-07-12): fetches the
      latest-run tar.gz once per cycle (skips an already-ingested run),
      archives the tar, decodes per-resort pixels RGBA→bin via each file's
      `ESCALA` GDAL tag (values are BINS, e.g. precip 0.5–1 mm →
      midpoint; open top bin and transparent zero → lower edge), nearest
      `ang_viento` GeoJSON point for wind direction. 11 variables/resort:
      temperature, wind speed/direction, precip 1/3/6 h, cloud cover, and
      neutral f207/f228 until a winter run confirms their semantics.
      Wired into rebuild_db.py; cron.example slot at 03/09/15/21 UTC.
- [ ] Normalization + elevation-semantics layer (canonical unit, windows,
      bucket mapping, base/mid/top per resort) — resolves open questions 4–5
      (`normalize.py` has the SWE-mm unit, 24/48 h windows and provisional
      elevation bands; Meteocat zonal categorical codes — cel, intensitat,
      probabilitat, tempesta, visibilitat — flow into SQLite as numeric
      codes awaiting the bucket map; AEMET precip bins are liquid mm =
      SWE mm by definition, but the snow/ratio question now hinges on
      what f207 turns out to be)

## Milestone 3: v1 complete — IN PROGRESS (green-lit 2026-07-12; the
winter-blocked M2 verifications remain open in parallel)
All acceptance checks in the project brief pass.
- [x] Regime-weighted consensus (N flows → AROME; S/E flows → AEMET+Meteocat)
      per forecast block, all 3 resorts (`consensus.py`, 2026-07-12):
      two calendar-day blocks, hand-tuned prior weights, per-leg inputs
      stored beside every blend so the priors can be verified and re-tuned.
      Caveats: the Meteocat AMOUNT leg abstains until acumulacioNeu units
      are confirmed (winter), and the AEMET snow gate (precip where pixel
      temp ≤ +1 °C) is provisional until f207 is confirmed.
- [x] Confidence matrix with hand-tuned initial thresholds (`consensus.py`:
      leg count sets the ceiling — 3→Alta, 2→Mitjana, ≤1→Baixa — and
      amount/cota disagreement demotes). Validating derived isozero vs
      Meteocat (~100–200 m on storm days) needs winter data — the stored
      `leg.*.cota_m` rows accumulate exactly that comparison.
- [ ] XEMA nowcast correction (mind Meteocat quota — polling multiplies
      calls) — blocked on XEMA station selection (open question below);
      last remaining v1 feature.
- [x] Read-only dashboard with snow, cota, confidence and attributions
      (`dashboard.py`, static HTML per ADR-0003, deployed to GitHub Pages
      by the ingest workflow). Live once Pages is enabled in repo settings
      (Source: "GitHub Actions").

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
- Meteocat zone for la_molina: 6 (Prepirineu or.) vs 4 (Pirineu or.) vs 8
  (Vessant sud Pirineu or.) — the API has no zone geometry and meteo.cat /
  apidocs / SMC-adjacent sites are unreachable from the dev environment
  (WAF). All zones are stored, so this costs nothing while open; resolve
  with `verify_meteocat_zones.py` on winter data, or by checking the zone
  map at meteo.cat/prediccio/pirineu from a browser.
- XEMA station selection per resort + gauge undercatch handling (20–50%)
- Semantic normalization spec (SWE mm proposal, windows, bucket mapping,
  snow ratio)
- Elevation semantics (canonical base/mid/top per resort)
- Staleness/degraded-mode policy (2 of 3 legs, stale legs)
- ~~Deployment target: VPS vs Raspberry Pi~~ RE-RESOLVED 2026-07-12:
  GitHub Actions + `datastore` branch (ADR-0002) — supersedes the earlier
  Raspberry Pi choice, which was blocked on hardware while unrecoverable
  forecast data went uncollected. `cron.example` stays for local/manual use.
- Verification metrics before calibration: MAE on 24h accumulation,
  hit/false-alarm on snow days, cota error in meters
- Risk: consensus weights are prior-based and unverified — the run_time vs
  valid_time schema exists so the system can measure and correct itself

## Maintenance reminders
- CLAUDE.md: add a Gotcha when an agent repeats a mistake.
- README: update Features when a milestone lands.
- docs/adr/: new ADR for any hard-to-reverse decision.
- CHANGELOG: start filling at first release.
