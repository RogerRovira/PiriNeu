"""Ingest the Open-Meteo/AROME leg (meteofrance_seamless) for all resorts.

One multi-location request per run; the raw payload is archived BEFORE any
parsing (see CLAUDE.md conventions). Parsed values land in SQLite in long
format, in the units Open-Meteo returns them — normalization to canonical
units is `normalize.py`'s job. run_time_utc is the fetch time; Open-Meteo
does not expose the model run time.

The isozero is derived per timestep (see freezing_level.py) and stored as
`freezing_level_derived` / `freezing_level_capped`, since the native
diagnostic returns null on meteofrance_seamless.
"""
import json
from datetime import datetime, timezone
from typing import List

import db
from alerting import send_alert
from archive import archive_payload
from config import ISO_UTC, RESORTS
from freezing_level import PRESSURE_LEVELS, derive_freezing_level
from httpcache import cached_get

SOURCE = "openmeteo"
API_URL = "https://api.open-meteo.com/v1/forecast"

# Variable set from the handoff script. precipitation_probability is
# deliberately absent — it comes from a 27 km ensemble and must not touch
# the high-res chain (see CLAUDE.md non-goals).
HOURLY_VARIABLES = (
    ("temperature_2m", "relative_humidity_2m", "wet_bulb_temperature_2m",
     "precipitation", "rain", "snowfall",
     "wind_speed_10m", "wind_direction_10m", "wind_gusts_10m")
    + tuple(f"temperature_{p}hPa" for p in PRESSURE_LEVELS)
    + tuple(f"geopotential_height_{p}hPa" for p in PRESSURE_LEVELS)
    + ("wind_speed_700hPa", "wind_direction_700hPa")
)
DAILY_VARIABLES = ("precipitation_sum", "snowfall_sum")


def build_url() -> str:
    lats = ",".join(str(r["lat"]) for r in RESORTS)
    lons = ",".join(str(r["lon"]) for r in RESORTS)
    # Explicit per-station elevation disables the 90 m DEM downscaling and
    # keeps comparability with the AEMET pixel (see CLAUDE.md gotchas).
    elevations = ",".join(str(r["elevation_m"]) for r in RESORTS)
    return (f"{API_URL}?latitude={lats}&longitude={lons}"
            f"&elevation={elevations}"
            f"&hourly={','.join(HOURLY_VARIABLES)}"
            f"&daily={','.join(DAILY_VARIABLES)}"
            f"&models=meteofrance_seamless"
            f"&forecast_days=4&timezone=UTC&timeformat=iso8601")


def _iso_utc(t: str) -> str:
    """Normalize Open-Meteo's minute-resolution ISO times to ISO_UTC.

    Daily timestamps are date-only ("2026-07-12") and stay that way.
    """
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
        station = resort["station"]
        hourly = block["hourly"]
        times = [_iso_utc(t) for t in hourly["time"]]
        empty = [None] * len(times)

        for variable in HOURLY_VARIABLES:
            for valid_time, value in zip(times, hourly.get(variable) or empty):
                if value is not None:
                    rows.append((SOURCE, station, run_time_utc,
                                 valid_time, variable, float(value)))

        for idx, valid_time in enumerate(times):
            temps = [(hourly.get(f"temperature_{p}hPa") or empty)[idx]
                     for p in PRESSURE_LEVELS]
            heights = [(hourly.get(f"geopotential_height_{p}hPa") or empty)[idx]
                       for p in PRESSURE_LEVELS]
            level = derive_freezing_level(temps, heights)
            if level.height_m is not None:
                rows.append((SOURCE, station, run_time_utc, valid_time,
                             "freezing_level_derived", float(level.height_m)))
                rows.append((SOURCE, station, run_time_utc, valid_time,
                             "freezing_level_capped",
                             1.0 if level.capped else 0.0))

        daily = block.get("daily") or {}
        daily_times = [_iso_utc(t) for t in daily.get("time") or []]
        for variable in DAILY_VARIABLES:
            for valid_time, value in zip(daily_times,
                                         daily.get(variable) or []):
                if value is not None:
                    rows.append((SOURCE, station, run_time_utc,
                                 valid_time, variable, float(value)))
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
    derived = sum(1 for r in rows if r[4] == "freezing_level_derived")
    cache_note = " (from cache)" if from_cache else ""
    print(f"{SOURCE}: archived {path}{cache_note}, upserted {count} rows "
          f"({derived} derived freezing levels)")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        send_alert(f"openmeteo_ingest failed: {exc}")
        raise
