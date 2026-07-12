"""Semantic normalization: canonical units, windows and elevation bands.

Canonical unit for snow amounts: SWE millimetres (project-brief proposal).
Accumulation windows: 24 h and 48 h from a forecast's run time.

Status per source (open questions 4-5 in PLAN.md):
- Open-Meteo: implemented. Snowfall comes in cm with a documented 7:1
  snow:water ratio ("for the water equivalent in millimeter, divide by 7",
  where snowfall is taken in mm) -> SWE mm = cm * 10 / 7. Confirm against
  the precipitation/rain split on the first live payloads.
- Meteocat: STUB — real payloads (2026-07-12) show zonal `acumulacio` /
  `acumulacioNeu` as NUMERIC strings, not buckets, but summer payloads
  carry no valor for them, so the unit (mm liquid? cm snow?) stays
  unconfirmed until the first winter payloads.
- AEMET: recon resolved the precip side — `grid.precip.*` bins are liquid
  mm, i.e. SWE mm by definition (values are bin midpoints). The snow-
  specific field is presumed to be code 207 (`grid.f207`, range
  0.001–0.2, likely metres); STUB until a winter run confirms it.

Elevation bands are provisional public resort figures; the canonical
base/mid/top mapping across sources lands with the Meteocat leg.
"""
from typing import Optional

# --- Open-Meteo -----------------------------------------------------------

# snowfall_cm = precipitation_mm * 0.7 in Open-Meteo's scheme (7:1 ratio).
OPENMETEO_SNOW_CM_PER_SWE_MM = 0.7


def openmeteo_snowfall_cm_to_swe_mm(snowfall_cm: float) -> float:
    return snowfall_cm / OPENMETEO_SNOW_CM_PER_SWE_MM


# --- Meteocat / AEMET (blocked on credentials / reconnaissance) -----------

def meteocat_bucket_to_swe_mm(bucket: object) -> Optional[float]:
    raise NotImplementedError(
        "Meteocat zonal acumulacioNeu is numeric but its UNIT is only "
        "observable on winter payloads — confirm before converting "
        "(PLAN.md open question 4)")


def aemet_snow_mm_to_swe_mm(value_mm: float) -> Optional[float]:
    raise NotImplementedError(
        "AEMET grid.precip.* bins are already liquid mm (= SWE mm), but the "
        "snow field is presumed grid.f207 with UNCONFIRMED semantics — "
        "verify on a winter run first (PLAN.md open question 4)")


# --- Elevation semantics (provisional, open question 5) --------------------

# Public resort base/top elevations; mid is the midpoint. Replace with the
# canonical per-source mapping when the Meteocat leg lands.
RESORT_ELEVATIONS_M = {
    "baqueira": {"base": 1500, "mid": 2055, "top": 2610},
    "boi_taull": {"base": 2020, "mid": 2385, "top": 2751},
    "la_molina": {"base": 1700, "mid": 2072, "top": 2445},
}

# --- Accumulation windows ---------------------------------------------------

WINDOWS_HOURS = (24, 48)


def accumulated_swe_mm(conn, source: str, station: str, run_time_utc: str,
                       window_hours: int) -> Optional[float]:
    """Sum a forecast's hourly snowfall over a window, in canonical SWE mm.

    Uses the `snowfall` rows of one (source, station, run_time) forecast for
    valid times within [run_time, run_time + window). Returns None when that
    forecast has no snowfall rows in the window (missing leg != zero snow).
    Only the Open-Meteo conversion exists so far.
    """
    if source != "openmeteo":
        raise NotImplementedError(f"no canonical conversion for {source} yet")
    # datetime() normalizes both sides: stored ISO-Z strings vs SQLite's
    # "YYYY-MM-DD HH:MM:SS" output would not compare correctly as raw text.
    row = conn.execute(
        """SELECT SUM(value), COUNT(*) FROM forecast_values
           WHERE source = ? AND station = ? AND run_time_utc = ?
             AND variable = 'snowfall'
             AND datetime(valid_time_utc) >= datetime(?)
             AND datetime(valid_time_utc) < datetime(?, ?)
        """,
        (source, station, run_time_utc, run_time_utc,
         run_time_utc, f"+{window_hours} hours")).fetchone()
    total_cm, count = row
    if not count:
        return None
    return openmeteo_snowfall_cm_to_swe_mm(total_cm)
