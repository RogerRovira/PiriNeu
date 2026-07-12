# CLAUDE.md

Non-commercial 48h snow and snow-line (cota de neu) forecast for three
Catalan Pyrenees resorts (Baqueira Beret, Boí Taüll, La Molina): a
wind-regime-weighted consensus of AROME (Open-Meteo), AEMET and Meteocat,
corrected with XEMA observations, with Alta/Mitjana/Baixa confidence labels.

## Commands
- Setup: `pip install -r requirements.txt`
- Ingest Open-Meteo leg: `python openmeteo_ingest.py`
- Ingest Meteocat leg: `python meteocat_ingest.py` (requires `METEOCAT_API_KEY`;
  ~5 calls/day — quota-guarded; `METEOCAT_PICS_TOMORROW=1` adds 3)
- Rebuild SQLite from the raw archive: `python rebuild_db.py [--db PATH]`
- Silent-failure watchdog: `python healthcheck.py` (alerts and exits 1 on stale data)
- Test the alert webhook: `python alerting.py "message"` (uses `ALERT_WEBHOOK_URL`)
- Verify Meteocat historics: `python verify_meteocat_historics.py` (requires `METEOCAT_API_KEY`)
- AEMET server reconnaissance: `python aemet_recon.py` (optionally
  `AEMET_DOWNLOAD_URL=<url captured from the viewer>`; rasterio enables
  raster inspection)
- Tests: `pytest`

## Stack
Python 3 · SQLite long format `(station, run_time_utc, valid_time_utc,
variable, value)` with idempotent upserts · rasterio (+ pyproj if needed)
for AEMET rasters · cron scheduling · minimal read-only dashboard (tech
TBD). Rationale: `docs/adr/0001-initial-stack.md` — don't repeat it here.

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
  BPA legend put Boí Taüll in the wrong zone once already.
- Meteocat zonal values live in `variablesValors[].valor` as STRINGS
  (categorical codes and numbers alike); `periode` is metadata, and summer
  payloads simply omit `valor` for the snow fields — a missing valor is
  not an error.
- AEMET gridded data: use the download server's tar.gz, NOT the OpenData
  REST API (PNG only). The bundled GeoTIFFs ARE EPSG:4326 but they are
  RGBA colormapped images, not data grids — decode values via each file's
  `ESCALA` GDAL tag (bins; alpha 0 = zero bin), and don't trust `CAMPO`
  (codes 207/228 both say "press"). Latest run only — no retention.
- (Add entries here whenever an agent makes the same mistake twice.)
