"""Silent-failure watchdog: alert when no fresh data has landed.

Cron can only report a job that CRASHES; a job that runs but stores nothing
fails silently. This check inspects the database itself: if the newest
run_time_utc is older than PIRINEU_MAX_AGE_HOURS (default 26), something in
the pipeline is broken and an alert fires. Schedule it daily after the
ingest slots (see cron.example).
"""
import os
import sys
from datetime import datetime, timedelta, timezone

import db
from alerting import send_alert
from config import HEALTHCHECK_MARKER, ISO_UTC

MAX_AGE_HOURS = float(os.environ.get("PIRINEU_MAX_AGE_HOURS", "26"))


def main() -> int:
    # Record the attempt up front: decide_legs.py runs the watchdog once
    # per day off this marker, and an alerting (or crashing) check must not
    # be repeated on every subsequent firing — one alert per day is enough.
    HEALTHCHECK_MARKER.parent.mkdir(parents=True, exist_ok=True)
    HEALTHCHECK_MARKER.write_text(
        datetime.now(timezone.utc).strftime("%Y-%m-%d") + "\n",
        encoding="utf-8")

    conn = db.connect()
    latest = conn.execute(
        "SELECT MAX(run_time_utc) FROM forecast_values").fetchone()[0]
    if latest is None:
        send_alert("healthcheck: database has no forecast rows at all")
        return 1
    age = datetime.now(timezone.utc) - datetime.strptime(
        latest, ISO_UTC).replace(tzinfo=timezone.utc)
    if age > timedelta(hours=MAX_AGE_HOURS):
        send_alert(f"healthcheck: newest data is {age} old "
                   f"(limit {MAX_AGE_HOURS:g}h) — ingestion is failing silently")
        return 1
    print(f"healthcheck OK: newest run {latest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
