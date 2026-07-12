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
<!-- TODO: verify after scaffolding -->
```bash
pip install -r requirements.txt          # TODO: requirements.txt pending
export METEOCAT_API_KEY=...              # never commit secrets
python openmeteo_ingest.py               # ingest the Open-Meteo/AROME leg
```

## Features (v1)
- 48h new-snow and snow-line forecast per resort
- Confidence labels (Alta/Mitjana/Baixa) computed from inter-model spread
- Nowcast correction from live XEMA observations
- Three independent ingestion legs with raw-payload archiving
- Read-only dashboard with full source attribution

## Tech
Python 3, SQLite, rasterio, cron; minimal read-only web dashboard.
Why this stack: [docs/adr/0001](docs/adr/0001-initial-stack.md).

## Data sources & attribution
Forecast and observation data: [Open-Meteo](https://open-meteo.com)
(CC-BY 4.0), [AEMET](https://www.aemet.es) and
[Meteocat](https://www.meteo.cat) — attribution required and gratefully
given. This project is non-commercial.

## License
<!-- TODO: choose a license compatible with the non-commercial posture and
source attribution requirements before publishing the repo. -->
