"""SQLite storage in long format with idempotent upserts (see ADR-0001).

Schema: (source, station, run_time_utc, valid_time_utc, variable, value).
`source` extends the documented long format so the three ingestion legs can
coexist; run_time vs valid_time exists so the system can later measure and
correct its own consensus weights.
"""
import sqlite3
from pathlib import Path
from typing import Iterable, Optional, Tuple

from config import DB_PATH

Row = Tuple[str, str, str, str, str, float]

_SCHEMA = """
CREATE TABLE IF NOT EXISTS forecast_values (
    source          TEXT NOT NULL,
    station         TEXT NOT NULL,
    run_time_utc    TEXT NOT NULL,
    valid_time_utc  TEXT NOT NULL,
    variable        TEXT NOT NULL,
    value           REAL,
    PRIMARY KEY (source, station, run_time_utc, valid_time_utc, variable)
)
"""

_UPSERT = """
INSERT INTO forecast_values
    (source, station, run_time_utc, valid_time_utc, variable, value)
VALUES (?, ?, ?, ?, ?, ?)
ON CONFLICT (source, station, run_time_utc, valid_time_utc, variable)
DO UPDATE SET value = excluded.value
"""


def connect(path: Optional[Path] = None) -> sqlite3.Connection:
    path = Path(path or DB_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute(_SCHEMA)
    return conn


def upsert_rows(conn: sqlite3.Connection, rows: Iterable[Row]) -> int:
    rows = list(rows)
    conn.executemany(_UPSERT, rows)
    conn.commit()
    return len(rows)
