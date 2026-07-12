# Previsió de Neu al Pirineu Català

A non-commercial web dashboard that forecasts 48-hour snowfall and snow line
(cota de neu) for Baqueira Beret, Boí Taüll and La Molina, with honest
confidence labels.

Each resort's page shows the expected new snow and snow line for the next 48
hours, labeled Alta/Mitjana/Baixa according to how much the underlying models
agree. The forecast blends three high-resolution local sources — AROME (via
Open-Meteo), AEMET and Meteocat — weighted by wind regime and corrected in
near-real-time with XEMA station observations. It's for skiers and mountain
users planning trips 0–2 days ahead who are tired of generalist snow sites
built on coarse global models.

## Status
Early development — v1 in progress. See [PLAN.md](PLAN.md).

## Quick start
```bash
pip install -r requirements.txt
python openmeteo_ingest.py     # Open-Meteo/AROME leg (archives raw first)
python meteocat_ingest.py      # Meteocat leg (needs METEOCAT_API_KEY)
python aemet_ingest.py         # AEMET Harmonie leg (latest run only)
python rebuild_db.py           # prove SQLite rebuilds from the raw archive
pytest                         # run the test suite
```
Scheduling and failure alerting: see [cron.example](cron.example).
Secrets (e.g. `METEOCAT_API_KEY`) live in env vars — never commit them.

## Features (v1)
- 48h new-snow and snow-line forecast per resort ✅ (regime-weighted
  consensus, `consensus.py`; priors documented and re-tunable)
- Confidence labels (Alta/Mitjana/Baixa) computed from inter-model spread ✅
- Nowcast correction from live XEMA observations (pending — last v1 item)
- Three independent ingestion legs with raw-payload archiving ✅
  (Open-Meteo/AROME, Meteocat zonal+pics, AEMET Harmonie GeoTIFF/GeoJSON)
- Read-only dashboard with full source attribution ✅ (static HTML on
  GitHub Pages, rebuilt after every ingest run)

## Tech
Python 3, SQLite, rasterio; GitHub Actions ingestion committing to the
`datastore` branch; minimal read-only web dashboard.
Why: [docs/adr/0001](docs/adr/0001-initial-stack.md),
[docs/adr/0002](docs/adr/0002-github-actions-data-acquisition.md).

## Data sources & attribution
Forecast and observation data: [Open-Meteo](https://open-meteo.com)
(CC-BY 4.0), [AEMET](https://www.aemet.es) and
[Meteocat](https://www.meteo.cat) — attribution required and gratefully
given. This project is non-commercial.

## License
<!-- TODO: choose a license compatible with the non-commercial posture and
source attribution requirements before publishing the repo. -->
