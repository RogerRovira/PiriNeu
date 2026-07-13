# Changelog

All notable changes to this project are documented here. Format based on
[Keep a Changelog](https://keepachangelog.com); versions follow
[SemVer](https://semver.org).

## [Unreleased]

### Changed
- Ingest scheduling is gap-tolerant: `decide_legs.py` picks the legs for
  each firing from the datastore state (latest ingested run per source,
  daily healthcheck marker) instead of exact-hour gates, because GitHub
  Actions cron firings are routinely delayed or dropped. The schedule
  itself drops from hourly to every two hours (odd hours at :37, ~50 min
  after each AEMET cycle is published).
