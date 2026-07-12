# ADR-0002: Data acquisition on GitHub Actions with a git datastore branch

- Status: Accepted (supersedes the Raspberry Pi deployment resolved in
  PLAN.md on 2026-07-12, which never shipped)
- Date: 2026-07-12

## Context
The pipeline needs scheduled ingestion (Open-Meteo hourly; Meteocat daily
~14:00 local; AEMET 00/06/12/18 UTC + ~2h45m lag) and durable storage for
the raw-payload archive — the source of truth the whole project rests on.
The previously chosen deployment (Raspberry Pi + cron, PLAN.md) was on
hold waiting for hardware, so nothing was being collected — and Meteocat
and AEMET forecasts are unrecoverable once their window passes. The
maintainer asked for GitHub Actions instead.

GitHub Actions runners are ephemeral, so state must be pushed somewhere
after every run. The AEMET bundle is ~22 MB per run (~32 GB/year), far
beyond what a git branch tolerates; everything else is a few MB per day
compressed.

## Decision
- One hourly scheduled workflow (`.github/workflows/ingest.yml`) runs all
  legs, each gated to its own rhythm by UTC hour, plus the daily
  healthcheck. A `concurrency` group serializes runs.
- State lives on an orphan **`datastore`** branch (bootstrapped
  automatically on first run): raw archive, SQLite view, HTTP cache — the
  cache commit is what keeps the Meteocat quota guard effective across
  ephemeral runners — and the alert log. `PIRINEU_DATA_DIR` points the
  code at the checkout, so nothing in the code changes.
- **AEMET rasters are cropped to a Pyrenees window before archiving**
  (`CROP_BOUNDS` in `aemet_ingest.py`), with GDAL tags (ESCALA legend)
  preserved and GeoJSONs filtered to the same window. This bends the
  "archive the raw payload" convention, so it is guarded: the cropped
  bundle is archived only if it decodes exactly the same per-resort rows
  as the full bundle; otherwise the full bundle is archived and an alert
  fires. Crops are re-encoded lossless (upstream is JPEG-in-TIFF; a JPEG
  re-encode shifts colors and corrupts ESCALA decoding). ~22 MB/run
  becomes ~2.5 MB archived.
- Secrets (`METEOCAT_API_KEY`, optional `ALERT_WEBHOOK_URL`) are GitHub
  Actions repository secrets.

## Considered alternatives
- Raspberry Pi + cron (previous decision) — no hardware yet; every day
  not collecting is unrecoverable data.
- Full AEMET bundles as GitHub Release assets — keeps bytes verbatim but
  adds a second storage mechanism and rebuild path for data that is 99%
  outside the project's area of interest.
- git-lfs for the archive — quota costs money and the bundles are still
  redundant beyond the Pyrenees window.
- External object storage (S3/R2/B2) — another account, credential and
  billing surface for a solo non-commercial project.

## Consequences
- Easier: zero hardware, off-machine durability from day one (the
  datastore is a hosted git branch), ingestion history is auditable as
  commits, failed runs email the maintainer for free.
- Harder: GitHub cron fires late (minutes, occasionally more) — hour
  gates in the workflow allow for it; the Meteocat slot runs at both 13
  and 14 UTC with the committed HTTP cache preventing double quota spend.
- Risk: GitHub suspends schedules after 60 days without repository
  activity; datastore commits count as activity, but if ingestion ever
  pauses, re-enable manually.
- Risk accepted: the AEMET archive is no longer the verbatim upstream
  bundle. The parity check bounds the risk to "verbatim vs equivalent",
  never "lost".
- The datastore branch grows without bound (~10-12 MB/day in season,
  dominated by the four AEMET crops — roughly 2 GB per winter). Fine for
  the first season; revisit (tighter crop, shallow history, periodic
  squash, or object storage) before it gets unwieldy — a new ADR then.
