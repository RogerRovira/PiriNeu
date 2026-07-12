# ADR-0003: Static HTML dashboard generated in CI, served by GitHub Pages

- Status: Accepted
- Date: 2026-07-12

## Context
Milestone 3 needs the read-only dashboard (project brief: each resort's
page shows 48h new snow, snow line, a confidence label and the mandatory
attributions). ADR-0001 left the technology open (static generation vs
micro-framework). Since ADR-0002, ingestion already runs on GitHub
Actions and the forecast changes at most hourly — there is nothing a
server could compute per-request that CI cannot precompute.

## Decision
`dashboard.py` renders plain static HTML (no JS, inline CSS, Catalan UI,
local times in Europe/Madrid, attributions on every page) from the
consensus rows in SQLite. The ingest workflow builds the site after each
run and publishes it with the official GitHub Pages actions
(`upload-pages-artifact` + `deploy-pages`). One-time manual step: enable
Pages with source "GitHub Actions" in the repository settings.

## Considered alternatives
- Micro-framework (Flask/FastAPI) on a VPS/Pi — a server to run, patch
  and pay for, serving content that only changes when CI runs anyway.
- Client-side JS app reading a JSON feed — more moving parts and worse
  no-JS/mobile behavior for what is a handful of numbers per resort.
- Committing the site to a `gh-pages` branch — the Pages actions replace
  the branch dance and keep deployment history out of git.

## Consequences
- Easier: zero runtime infrastructure; the dashboard can never be down
  independently of GitHub; every deploy is reproducible from the
  datastore.
- Harder: freshness is bounded by the ingest schedule (hourly) — fine for
  a forecast product updated at most a few times a day.
- The site inherits the ingest workflow's failure modes: if ingestion
  stops, the dashboard goes stale (the healthcheck alert covers this).
