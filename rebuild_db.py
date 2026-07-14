"""Rebuild the SQLite view from the raw-payload archive.

The archive is the source of truth; this script proves SQLite is a
disposable, rebuildable view of it. Rebuilding into the live database is
safe too — upserts are idempotent.

Usage: python rebuild_db.py [--db PATH]   (default: data/rebuild.sqlite)
"""
import argparse

import db
from aemet_ingest import SOURCE as AEMET_SOURCE
from aemet_ingest import parse_aemet
from archive import iter_archived, run_time_from_path
from config import DATA_DIR
from meteocat_ingest import SOURCE as METEOCAT_SOURCE
from meteocat_ingest import parse_meteocat
from openmeteo_ingest import SOURCE as OPENMETEO_SOURCE
from openmeteo_ingest import parse_openmeteo
from xema_ingest import SOURCE as XEMA_SOURCE
from xema_ingest import parse_xema

# One entry per ingestion leg: fn(payload, run_time_utc, archive_name).
PARSERS = {
    OPENMETEO_SOURCE: lambda raw, run, name: parse_openmeteo(raw, run),
    METEOCAT_SOURCE: parse_meteocat,
    AEMET_SOURCE: parse_aemet,
    XEMA_SOURCE: parse_xema,
}


def rebuild(db_path) -> None:
    conn = db.connect(db_path)
    for source, parser in PARSERS.items():
        payloads = row_count = failures = 0
        for path, raw in iter_archived(source):
            try:
                rows = parser(raw, run_time_from_path(path), path.name)
            except Exception as exc:  # keep going: one bad file != lost archive
                failures += 1
                print(f"{source}: skipped {path}: {exc}")
                continue
            row_count += db.upsert_rows(conn, rows)
            payloads += 1
        print(f"{source}: rebuilt {row_count} rows from {payloads} payloads"
              f" ({failures} unparseable) into {db_path}")


if __name__ == "__main__":
    argp = argparse.ArgumentParser(description=__doc__)
    argp.add_argument("--db", default=DATA_DIR / "rebuild.sqlite",
                      help="target database path (default: data/rebuild.sqlite)")
    rebuild(argp.parse_args().db)
