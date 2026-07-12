"""Ingest the Open-Meteo/AROME leg (meteofrance_seamless) for all resorts.

One multi-location request per run; the raw payload is archived BEFORE any
parsing (see CLAUDE.md conventions). Parsed values land in SQLite in long
format, in the units Open-Meteo returns them (normalization is a Milestone 2
layer). run_time_utc is the fetch time — Open-Meteo does not expose the
model run time.
"""
import json
from datetime import datetime, timezone
from typing import List

import db
from alerting import send_alert
from archive import archive_payload
from config import ISO_UTC, RESORTS
from httpcache import cached_get
from snowline import PRESSURE_LEVELS, derive_snow_line

SOURCE = "openmeteo"
API_URL = "https://api.open-meteo.com/v1/forecast"

SURFACE_VARIABLES = (
    "temperature_2m",
    "precipitation",
    "snowfall",
    "wind_speed_10m",
    "wind_direction_10m",
)
# NOTE: precipitation_probability is deliberately absent — it comes from a
# 27 km ensemble and must not touch the high-res chain (see CLAUDE.md).
HOURLY_VARIABLES = (
    SURFACE_VARIABLES
    + tuple(f"temperature_{lvl}" for lvl in PRESSURE_LEVELS)
    + tuple(f"geopotential_height_{lvl}" for lvl in PRESSURE_LEVELS)
)


def build_url() -> str:
    lats = ",".join(str(r["lat"]) for r in RESORTS)
    lons = ",".join(str(r["lon"]) for r in RESORTS)
    # Explicit per-station elevation disables the 90 m DEM downscaling and
    # keeps comparability with the AEMET pixel (see CLAUDE.md gotchas).
    elevations = ",".join(str(r["elevation_m"]) for r in RESORTS)
    return (f"{API_URL}?latitude={lats}&longitude={lons}"
            f"&elevation={elevations}"
            f"&hourly={','.join(HOURLY_VARIABLES)}"
            f"&models=meteofrance_seamless&forecast_days=3&timezone=GMT")


def _iso_utc(t: str) -> str:
    """Open-Meteo returns minute-resolution ISO times; normalize to ISO_UTC."""
    return f"{t}:00Z" if len(t) == 16 else t


def parse_openmeteo(payload: bytes, run_time_utc: str) -> List[db.Row]:
    """Parse one archived multi-location payload into long-format rows.

    The response array is zipped BY POSITION with RESORTS: element 0 carries
    no location_id key (elements 1+ do), so keying on it would break
    (see CLAUDE.md gotchas). Request order must therefore match RESORTS.
    """
    data = json.loads(payload)
    if isinstance(data, dict):
        data = [data]
    if len(data) != len(RESORTS):
        raise ValueError(
            f"expected {len(RESORTS)} location blocks, got {len(data)}")

    rows: List[db.Row] = []
    for resort, block in zip(RESORTS, data):
        hourly = block["hourly"]
        times = [_iso_utc(t) for t in hourly["time"]]
        empty = [None] * len(times)

        for variable in HOURLY_VARIABLES:
            for valid_time, value in zip(times, hourly.get(variable) or empty):
                if value is not None:
                    rows.append((SOURCE, resort["station"], run_time_utc,
                                 valid_time, variable, float(value)))

        for idx, valid_time in enumerate(times):
            temps = [(hourly.get(f"temperature_{lvl}") or empty)[idx]
                     for lvl in PRESSURE_LEVELS]
            heights = [(hourly.get(f"geopotential_height_{lvl}") or empty)[idx]
                       for lvl in PRESSURE_LEVELS]
            line_m, capped = derive_snow_line(temps, heights)
            if line_m is not None:
                rows.append((SOURCE, resort["station"], run_time_utc,
                             valid_time, "snow_line_m", float(line_m)))
                rows.append((SOURCE, resort["station"], run_time_utc,
                             valid_time, "snow_line_capped",
                             1.0 if capped else 0.0))
    return rows


def main() -> None:
    fetched_at = datetime.now(timezone.utc)
    status, body, from_cache = cached_get(build_url())
    if status != 200:
        raise RuntimeError(f"Open-Meteo returned HTTP {status}")

    # Archive BEFORE parsing: the raw file survives even if parsing breaks.
    path = archive_payload(SOURCE, "forecast.json", body, fetched_at)

    rows = parse_openmeteo(body, fetched_at.strftime(ISO_UTC))
    count = db.upsert_rows(db.connect(), rows)
    cache_note = " (from cache)" if from_cache else ""
    print(f"{SOURCE}: archived {path}{cache_note}, upserted {count} rows")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        send_alert(f"openmeteo_ingest failed: {exc}")
        raise
