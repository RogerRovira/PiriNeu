# ADR-0001: Python + SQLite with GeoTIFF/GeoJSON/JSON sources (no GRIB2)

- Status: Accepted
- Date: 2026-07-12

## Context
A solo-maintained, non-commercial forecast pipeline ingests three weather
sources for three resorts on a daily rhythm — small, single-writer data
volume, all sources reachable as REST/file downloads. The system must be
rebuildable from archived raw payloads, and the maintainer works in Python.
This is the project's first stack decision; ADRs in this repo are immutable —
a reversed decision gets a new ADR that supersedes this one.

## Decision
We will build the pipeline in Python 3, store all series in SQLite using a
long format `(station, run_time_utc, valid_time_utc, variable, value)` with
idempotent upserts, read AEMET rasters with rasterio (adding pyproj if the
CRS requires it), schedule ingestion with cron, and serve results through a
minimal read-only web dashboard. Storage is UTC-only; local time appears
only in the presentation layer. Secrets live in environment variables.

## Considered alternatives
- GRIB2-based toolchain — rejected because GeoTIFF/GeoJSON/JSON serve every
  need at far lower complexity.
- AEMET OpenData REST API for gridded data — rejected because it serves PNG
  images only.
- Native `freezing_level_height` from meteofrance_seamless — rejected
  because it returns null; the snow line is derived from pressure-level
  temperature crossings instead.

## Consequences
- Easier: zero-ops storage, idempotent re-runs, full rebuild from the raw
  payload archive.
- Harder: single-writer SQLite limits concurrency (acceptable at this
  scale).
- Open: dashboard technology (static generation vs micro-framework) is
  still undecided — resolve before Milestone 3. <!-- TODO -->
