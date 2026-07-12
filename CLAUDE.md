# CLAUDE.md

Non-commercial 48h snow and snow-line (cota de neu) forecast for three
Catalan Pyrenees resorts (Baqueira Beret, Boí Taüll, La Molina): a
wind-regime-weighted consensus of AROME (Open-Meteo), AEMET and Meteocat,
corrected with XEMA observations, with Alta/Mitjana/Baixa confidence labels.

## Commands
<!-- TODO: verify after scaffolding — no requirements.txt or test runner exists yet -->
- Setup: `pip install -r requirements.txt`
- Ingest Open-Meteo leg: `python openmeteo_ingest.py`
- Verify Meteocat historics: `python verify_meteocat_historics.py` (requires `METEOCAT_API_KEY`)
- Tests: TODO — none defined yet

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
- Coordinates/elevations in `openmeteo_ingest.py` are PLACEHOLDERS — replace
  with canonical pics-metadades coords once Meteocat credentials arrive.
- AEMET gridded data: use the download server's GeoTIFF/GeoJSON, NOT the
  OpenData REST API (PNG only). Don't assume the raster CRS is WGS84.
- (Add entries here whenever an agent makes the same mistake twice.)
