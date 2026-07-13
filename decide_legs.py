"""Gap-tolerant leg scheduling for the ingest workflow (ADR-0002).

GitHub cron is best-effort: firings arrive minutes-to-an-hour late and are
routinely dropped under load (observed 2026-07-13: five firings in twelve
hours against an hourly schedule). Exact-hour gates ("run meteocat at 13")
miss their slot whenever no firing lands inside the window, so instead each
leg declares WHEN new upstream data should exist and the datastore answers
whether it was already fetched — the first firing after publication picks
it up, however late the runner wakes.

Prints the comma-separated legs for this firing, e.g. "openmeteo,aemet".
The decision needs the datastore checked out (PIRINEU_DATA_DIR) but makes
no network calls.
"""
from datetime import datetime, timedelta, timezone
from typing import List, Optional

import db
from config import HEALTHCHECK_MARKER, ISO_UTC

# AEMET Harmonie cycles at 00/06/12/18 UTC, published ~2h45m later
# (recon 2026-07-12); the server holds only the latest run.
AEMET_CYCLE_HOURS = 6
AEMET_PUBLICATION_LAG = timedelta(hours=2, minutes=45)

# Meteocat publishes once a day, ~14:00 local (12:00/13:00 UTC by DST) —
# gate at 13 UTC so it covers both. Retries stop at LAST_HOUR: every
# attempt costs ~5 calls of a tightly capped quota, so a dead-API day
# burns a bounded number of attempts instead of retrying until midnight.
METEOCAT_PUBLISH_HOUR = 13
METEOCAT_LAST_HOUR = 21

HEALTHCHECK_HOUR = 8  # daily watchdog, after the overnight ingest slots


def latest_run(conn, source: str) -> Optional[str]:
    """Newest run_time_utc ingested for a source (None = never)."""
    return conn.execute(
        "SELECT MAX(run_time_utc) FROM forecast_values WHERE source = ?",
        (source,)).fetchone()[0]


def aemet_expected_run(now: datetime) -> str:
    """Most recent 00/06/12/18 UTC cycle whose publication lag has elapsed."""
    t = now - AEMET_PUBLICATION_LAG
    return t.replace(hour=t.hour - t.hour % AEMET_CYCLE_HOURS, minute=0,
                     second=0, microsecond=0).strftime(ISO_UTC)


def decide(now: datetime, conn, healthcheck_ran: str = "") -> List[str]:
    """Legs to run at this firing. `healthcheck_ran` is the marker date
    ("YYYY-MM-DD") of the last watchdog run, empty if it never ran."""
    legs = ["openmeteo"]                       # source refreshes hourly

    # ISO_UTC strings compare lexicographically, and "" sorts before any
    # real timestamp, so a never-ingested source is always due.
    meteocat_due = f"{now:%Y-%m-%d}T{METEOCAT_PUBLISH_HOUR:02d}:00:00Z"
    if (METEOCAT_PUBLISH_HOUR <= now.hour < METEOCAT_LAST_HOUR
            and (latest_run(conn, "meteocat") or "") < meteocat_due):
        legs.append("meteocat")

    # aemet_ingest.py derives the true model run and skips re-ingesting the
    # same one, so firing while publication is late costs one download only.
    if (latest_run(conn, "aemet") or "") < aemet_expected_run(now):
        legs.append("aemet")

    if now.hour >= HEALTHCHECK_HOUR and healthcheck_ran != f"{now:%Y-%m-%d}":
        legs.append("healthcheck")

    return legs


def main() -> None:
    marker = ""
    if HEALTHCHECK_MARKER.exists():
        marker = HEALTHCHECK_MARKER.read_text(encoding="utf-8").strip()
    print(",".join(decide(datetime.now(timezone.utc), db.connect(), marker)))


if __name__ == "__main__":
    main()
