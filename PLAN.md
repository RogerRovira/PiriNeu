# Plan — Previsió de Neu al Pirineu Català

Core loop: user opens a resort's page → sees the 48h new-snow and snow-line
forecast with its confidence label → decides whether and where to go.

## Milestone 1: Data safety + collect-forward
Protects irreplaceable data — everything else can be rebuilt from it.
- [ ] Raw-payload archiving wrapper: persist every raw JSON/GeoTIFF/GeoJSON
      compressed and dated BEFORE parsing — done when: every ingest run
      archives its payloads and SQLite is demonstrably rebuildable
- [ ] Cron scheduling aligned to source rhythms (Meteocat ~14:00 local
      daily; AEMET 00/06/12/18 UTC + lag; Open-Meteo hourly) + failure
      alerting — done when: a silent failure raises an alert
- [ ] Start collect-forward daily ingestion of available legs — done when:
      data accumulates daily regardless of the Meteocat historics outcome

## Milestone 2: Full three-leg ingestion + normalization
- [ ] Run `verify_meteocat_historics.py` when credentials arrive; record the
      archived/recomputed/404 outcome — resolves open question 1
- [ ] Replace placeholder coordinates in `openmeteo_ingest.py` with
      canonical pics-metadades coords
- [ ] AEMET reconnaissance script (publication lag, retention, CRS, nodata)
      — resolves open question 2
- [ ] AEMET ingest leg: GeoTIFF pixel extraction + wind GeoJSON → SQLite
- [ ] Normalization + elevation-semantics layer (canonical unit, windows,
      bucket mapping, base/mid/top per resort) — resolves open questions 4–5

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
- Meteocat archived forecasts? (blocked on credentials; decides bootstrap)
- AEMET operational unknowns (lag, retention, CRS, nodata)
- XEMA station selection per resort + gauge undercatch handling (20–50%)
- Semantic normalization spec (SWE mm proposal, windows, bucket mapping,
  snow ratio)
- Elevation semantics (canonical base/mid/top per resort)
- Staleness/degraded-mode policy (2 of 3 legs, stale legs)
- Deployment target: VPS vs Raspberry Pi (either fine; pick one, set cron +
  off-machine backups day 1)
- Verification metrics before calibration: MAE on 24h accumulation,
  hit/false-alarm on snow days, cota error in meters
- Risk: consensus weights are prior-based and unverified — the run_time vs
  valid_time schema exists so the system can measure and correct itself

## Maintenance reminders
- CLAUDE.md: add a Gotcha when an agent repeats a mistake.
- README: update Features when a milestone lands.
- docs/adr/: new ADR for any hard-to-reverse decision.
- CHANGELOG: start filling at first release.
