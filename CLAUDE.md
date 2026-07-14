# CLAUDE.md

Non-commercial 48h snow and snow-line (cota de neu) forecast for three
Catalan Pyrenees resorts (Baqueira Beret, Boí Taüll, La Molina): a
wind-regime-weighted consensus of AROME (Open-Meteo), AEMET and Meteocat,
corrected with XEMA observations, with Alta/Mitjana/Baixa confidence labels.

## Commands
- Setup: `pip install -r requirements.txt`
- Ingest Open-Meteo leg: `python openmeteo_ingest.py`
- Ingest Meteocat leg: `python meteocat_ingest.py` (requires `METEOCAT_API_KEY`;
  3 calls/day — 2 zone dates + ONE rotating anchor; `METEOCAT_ALL_ANCHORS=1`
  fetches all 10 anchors, `METEOCAT_PICS_TOMORROW=1` adds tomorrow's pic)
- XEMA reconnaissance (pre-nowcast): `python xema_recon.py` (requires
  `METEOCAT_API_KEY`; ~15 calls of the XEMA plan on first run)
- Ingest XEMA observations: `python xema_ingest.py` (requires
  `METEOCAT_API_KEY`; 6 calls/cycle + morning backfill, gated by
  decide_legs at >8h staleness — XEMA plan: 750 calls/month)
- Rebuild SQLite from the raw archive: `python rebuild_db.py [--db PATH]`
- Silent-failure watchdog: `python healthcheck.py` (alerts and exits 1 on stale data)
- Test the alert webhook: `python alerting.py "message"` (uses `ALERT_WEBHOOK_URL`)
- Ingest AEMET leg: `python aemet_ingest.py` (latest Harmonie run only;
  re-runs of the same run are skipped)
- Verify Meteocat historics: `python verify_meteocat_historics.py` (requires `METEOCAT_API_KEY`)
- Verify resort→zone assignment against accumulated data (no API calls):
  `python verify_meteocat_zones.py` (needs winter payloads to conclude)
- AEMET server reconnaissance: `python aemet_recon.py` (optionally
  `AEMET_DOWNLOAD_URL=<url captured from the viewer>`; rasterio enables
  raster inspection)
- Build the consensus (writes source='consensus' rows): `python consensus.py`
- Generate the static dashboard: `python dashboard.py [--out DIR]`
- Tests: `pytest`

## Stack
Python 3 · SQLite long format `(station, run_time_utc, valid_time_utc,
variable, value)` with idempotent upserts · rasterio for AEMET rasters ·
GitHub Actions scheduled ingestion committing to the `datastore` branch
(raw archive + SQLite + HTTP cache; AEMET rasters cropped to the Pyrenees
window with a decode-parity guard) · static HTML dashboard built in CI
and served by GitHub Pages. Rationale: `docs/adr/0001-initial-stack.md`,
`docs/adr/0002-github-actions-data-acquisition.md` and
`docs/adr/0003-static-dashboard-github-pages.md` — don't repeat them here.

## Non-goals — do NOT build these
- GRIB2 pipelines anywhere — GeoTIFF/GeoJSON/JSON cover everything.
- Full snowpack modeling (Crocus/SNOWPACK) — separate research project;
  proxies at most, in later phases.
- Ground snow-depth prediction — model `snow_depth` is unreliable in complex
  terrain; the consensus predicts NEW snowfall only.
- Open-Meteo `precipitation_probability` in the consensus — it comes from a
  27 km ensemble and contaminates the high-res chain; probability comes from
  Meteocat.
- Commercial features or monetization — source licensing (Open-Meteo CC-BY;
  AEMET and Meteocat attribution mandatory) and project intent.

## Conventions
- UTC everywhere in storage; local time only in the presentation layer.
- Secrets via env vars (e.g. `METEOCAT_API_KEY`) — never in code or docs.
- Archive every raw payload (compressed, dated) BEFORE parsing; SQLite is a
  rebuildable view, the raw archive is the source of truth.
- Respect API quotas: keep disk caches (including failed statuses) and call
  caps (`MAX_NEW_CALLS`) in place.
- Keep mandatory attributions (Open-Meteo CC-BY, AEMET, Meteocat) in every
  user-facing output.
- Prefer straightforward, well-documented libraries — this is a
  solo-maintained project.

## Gotchas (hard-won facts — do not "fix" these)
- Open-Meteo multi-location responses are a JSON array; element 0 has NO
  `location_id` key (elements 1+ do) → zip by position, never key on it.
- `freezing_level_height` on `meteofrance_seamless` returns null → the snow
  line is DERIVED by scanning 1000/925/850/700 hPa temperatures for the 0 °C
  crossing, interpolated with real `geopotential_height_*` values.
  Inversions → take the LOWEST crossing (conservative); whole column ≤ 0 °C
  → lowest level height with `capped=True`.
- Always pass explicit `&elevation=` per station to Open-Meteo (disables
  90 m DEM downscaling; keeps comparability with the AEMET pixel).
- Meteocat forecast endpoints take **slugs**, not hex codes — resolve via
  `/pronostic/v1/pirineu/pics/metadades` and `/refugis/metadades`. Pics
  metadades lat/lon are the CANONICAL coordinates for ALL sources.
- The Meteocat zonal precipitation endpoint returns ALL zones per call (no
  zone parameter exists) — one call serves every resort.
- `meteocat-openapi.yaml` has inconsistent parameter casing (snake_case vs
  camelCase). That mirrors the real API — preserve as-is.
- Canonical pics-metadades coords are in `config.py` (swapped 2026-07-12).
  Metadades has NO elevation field — `elevation_m` comes from the
  Open-Meteo elevation API at those exact points.
- Meteocat forecast endpoints serve ONLY a rolling 3-day window
  (today..D+2); anything else is HTTP 400. There is no forecast archive —
  never design anything that assumes past forecasts are refetchable.
- The zonal endpoint uses its OWN 7-zone scheme (ids 1,3–8; the payload's
  `nom` is authoritative), NOT the allaus/BPA zones — mapping ids from the
  BPA legend put Boí Taüll in the wrong zone once already. The API exposes
  NO zone geometry, so zonal rows are stored for ALL zones (`zona_<id>`
  pseudo-stations) and the resort→zone choice lives in
  `config.METEOCAT_ZONE_FOR_STATION` — change the config, never the
  parser, and run `verify_meteocat_zones.py` before trusting it.
- Meteocat quotas are per PLAN on the same key: **Predicció (pronostic
  endpoints) = 100 calls/month**, XEMA = 750/month. The original 5-call/day
  pronostic schedule would have exhausted Predicció around day 20 — hence
  the one-anchor-per-day rotation (`anchors_for_date`) and 30-day metadades
  cache. Never add a recurring pronostic call without redoing the monthly
  budget (nominal is ~92/100 including bounded failure retries).
- meteo.cat, apidocs.meteocat.gencat.cat and SMC-adjacent sites are
  unreachable from this dev environment (WAF blocks non-browser agents);
  only api.meteo.cat works. Don't burn time retrying them.
- Meteocat zonal values live in `variablesValors[].valor` as STRINGS
  (categorical codes and numbers alike); `periode` is metadata, and summer
  payloads simply omit `valor` for the snow fields — a missing valor is
  not an error.
- AEMET gridded data: use the download server's tar.gz, NOT the OpenData
  REST API (PNG only). The bundled GeoTIFFs ARE EPSG:4326 but they are
  RGBA colormapped images, not data grids — decode values via each file's
  `ESCALA` GDAL tag (bins; alpha 0 = zero bin), and don't trust `CAMPO`
  (codes 207/228 both say "press"). Latest run only — no retention.
- GitHub Actions cron is BEST-EFFORT: firings arrive late and are routinely
  dropped (observed 2026-07-13: 5 firings in 12 h against an hourly
  schedule). Never gate a leg on the exact firing hour — gate on datastore
  state (`decide_legs.py`), so a dropped firing only delays a leg until the
  next one that lands.
- (Add entries here whenever an agent makes the same mistake twice.)
