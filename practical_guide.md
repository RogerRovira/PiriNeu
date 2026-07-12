# Practical guide

How to run, operate and poke at the pipeline day to day. Design rationale
lives in `docs/adr/`; open questions in `open_points.md`; milestones in
`PLAN.md`.

## One-time go-live (after any fresh clone of the repo on GitHub)

1. **Secrets** — repo Settings → Secrets and variables → Actions:
   - `METEOCAT_API_KEY` (required for the Meteocat leg)
   - `ALERT_WEBHOOK_URL` (optional; e.g. `https://ntfy.sh/<your-topic>`
     to get failures on your phone — alerts also land in the datastore's
     `logs/alerts.log` either way)
2. **GitHub Pages** — Settings → Pages → Source: **GitHub Actions**.
3. Optionally kick the first run by hand: Actions → `ingest` → Run
   workflow → legs: `openmeteo,meteocat,aemet`. This bootstraps the
   `datastore` branch and publishes the dashboard.

After that everything is scheduled: no servers, no cron, no hardware.

## What runs when (all UTC)

| When            | What                                    |
|-----------------|-----------------------------------------|
| every hour :10  | Open-Meteo/AROME leg (source is hourly) |
| 13:10 and 14:10 | Meteocat leg (publishes ~14:00 local; 2nd slot covers cron lag, the committed HTTP cache prevents double quota spend) |
| 03:10 / 09:10 / 15:10 / 21:10 | AEMET leg (00/06/12/18 runs + ~2h45m lag; re-fetch of the same run is skipped) |
| 08:10           | healthcheck (alerts if the newest DB row is older than 26 h) |
| every run       | consensus rebuild + dashboard deploy to Pages |

GitHub cron fires a few minutes late routinely; the hour gates tolerate it.

## Where things live

- **`main`** — code only. `data/` is gitignored locally.
- **`datastore` branch** — the actual data, committed by CI after every
  run: `raw/` (the archive — SOURCE OF TRUTH), `pirineu.sqlite`
  (rebuildable view), `cache/` (HTTP cache, protects quotas), `logs/`.
- **Dashboard** — GitHub Pages URL shown in the `deploy-dashboard` job
  (Settings → Pages). Static HTML, Catalan, rebuilt hourly.

## Running locally

```bash
pip install -r requirements.txt
export METEOCAT_API_KEY=...          # only for the Meteocat leg

python openmeteo_ingest.py           # each leg archives raw BEFORE parsing
python meteocat_ingest.py            # ~5 API calls/day, cache-guarded
python aemet_ingest.py               # ~22 MB download, latest run only
python consensus.py                  # writes source='consensus' rows
python dashboard.py                  # data/site/*.html — open in a browser
pytest                               # 45 tests
```

Data goes to `./data/` by default; set `PIRINEU_DATA_DIR` to point
anywhere else (this is how CI points at the datastore checkout). To work
against the real accumulated data locally:

```bash
git clone --branch datastore git@github.com:RogerRovira/PiriNeu.git /tmp/datastore
PIRINEU_DATA_DIR=/tmp/datastore python consensus.py
```

`python rebuild_db.py [--db PATH]` reproves that SQLite is disposable: it
reparses every archived payload. Run it after changing any parser — old
rows with obsolete variable names don't disappear on their own; delete
the sqlite and rebuild when parser output changes shape.

## Reading the database

Schema: one table `forecast_values (source, station, run_time_utc,
valid_time_utc, variable, value)` — long format, idempotent upserts.

| source     | stations                     | variables you'll care about |
|------------|------------------------------|------------------------------|
| openmeteo  | baqueira/boi_taull/la_molina | `snowfall`, `snowfall_sum`, `precipitation`, `temperature_2m`, `freezing_level_derived` (+`_capped`), `wind_*_700hPa` |
| meteocat   | resorts + `zona_1`…`zona_8`  | `pic.<var>.<cota>` (isozero, temperatura, vent per 1500/2000/2500/3000), `zonal.<var>.<span>h` (cota, acumulacioNeu, probabilitat… — categorical codes stored as numbers) |
| aemet      | resorts                      | `grid.temperature`, `grid.precip.1h/3h/6h`, `grid.wind_speed/_direction`, `grid.cloud_cover`, `grid.f207`/`grid.f228` (unconfirmed semantics) |
| consensus  | resorts                      | `snow_swe_mm`, `cota_m`, `confidence` (2/1/0 = Alta/Mitjana/Baixa), `regime` (0/1/2 = N/SE/mixt), `n_legs_snow`, `leg.<leg>.snow_swe_mm`, `leg.<leg>.cota_m` |

`valid_time_utc` is an ISO instant for hourly data, a date for daily
blocks. AEMET values are BIN midpoints (colormap decoding), not
continuous. Meteocat zonal rows are per-zone; the resort→zone join is
`config.METEOCAT_ZONE_FOR_STATION`.

## When something breaks

- **A red `ingest` run** — one leg failed; the others still ran and
  committed. Open the failing step's log. The same message went to the
  webhook + `logs/alerts.log`.
- **Meteocat HTTP 400** — you asked for a date outside the rolling
  today..D+2 window. That's the API, not a bug.
- **`aemet: run … already ingested, skipping`** — normal; the publication
  lag hasn't elapsed, same run still served.
- **`aemet_ingest: cropped bundle decoded differently`** — the crop
  parity guard fired; the FULL bundle was archived (nothing lost). Debug
  `crop_bundle()` before the datastore bloats.
- **`meteocat zone scheme drift`** — Meteocat renamed/renumbered zones;
  re-derive `EXPECTED_ZONE_NAMES` (meteocat_ingest.py) and re-check
  `METEOCAT_ZONE_FOR_STATION` before trusting zonal data.
- **healthcheck alert** — no fresh rows for >26 h: check the Actions tab
  first (suspended schedule? failing leg?), then the sources themselves.
- **Dashboard stale** — it only rebuilds when ingest runs; check the
  `deploy-dashboard` job and that Pages source is still "GitHub Actions".

## Tuning knobs (change config/constants, never parsers)

- Resort→zone: `config.METEOCAT_ZONE_FOR_STATION` (verify first:
  `python verify_meteocat_zones.py`).
- Consensus priors: `consensus.WEIGHTS`, confidence thresholds, the
  isozero→cota offset (`ISOZERO_TO_COTA_M`), staleness
  (`MAX_RUN_AGE_HOURS`), AEMET snow gate (`AEMET_SNOW_MAX_TEMP_C`).
- AEMET archive footprint: `aemet_ingest.CROP_BOUNDS` (the parity guard
  protects you from cropping the resorts out).
- Meteocat pics for tomorrow too: set `METEOCAT_PICS_TOMORROW=1`
  (+3 calls/day).

## First-snowfall checklist (see open_points.md for details)

1. `python verify_meteocat_zones.py` against the datastore → confirm (or
   fix) the la_molina zone.
2. Inspect a winter zonal payload → confirm `acumulacioNeu`/`cota` units
   → implement `normalize.meteocat_bucket_to_swe_mm` → the consensus
   Meteocat amount leg starts contributing and Alta becomes reachable.
3. Compare `grid.f207` with actual snowfall → rename/convert it and
   replace the temperature-gate in `consensus.aemet_snow_swe`.
4. Watch `leg.openmeteo.cota_m` vs `leg.meteocat.cota_m` on storm days →
   absorb the systematic bias into `ISOZERO_TO_COTA_M`.
