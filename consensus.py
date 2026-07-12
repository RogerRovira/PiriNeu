"""Regime-weighted 48h consensus with confidence labels (Milestone 3).

For each resort and each of two 24h blocks (calendar days D0/D1 UTC —
matching Meteocat's day-based zonal product), the latest fresh run of each
leg contributes:

  new snow (canonical SWE mm)
  - openmeteo: daily `snowfall_sum` (cm, 7:1 ratio -> SWE mm), falling
    back to summing hourly `snowfall`
  - aemet: sum of `grid.precip.1h` bins over hours whose pixel temperature
    is <= +1.0 degC (provisional snow gate until field 207 is confirmed)
  - meteocat: zonal `acumulacioNeu.24h` of the assigned zone — currently
    UNAVAILABLE (unit unconfirmed until winter, normalize.py raises), so
    Meteocat contributes cota and wind; the consensus degrades gracefully

  snow line (cota, m)
  - meteocat: mean `zonal.cota.6h` of the assigned zone when present
    (winter), else mean `pic.isozero.totes` - ISOZERO_TO_COTA_M
  - openmeteo: mean `freezing_level_derived` - ISOZERO_TO_COTA_M,
    preferring hours with precipitation (that's when the cota matters)
  - aemet: none (no freezing-level product in the bundle)

  wind regime (which leg family to trust — the project's core prior:
  north/Atlantic flows favour AROME, south/east Mediterranean flows favour
  AEMET+Meteocat)
  - circular mean of Meteocat `pic.direccio_vent.3000`, falling back to
    Open-Meteo `wind_direction_700hPa`, then AEMET `grid.wind_direction`

Weights and confidence thresholds are HAND-TUNED PRIORS (documented
constants below); every consensus run stores its per-leg inputs alongside
the blend, so the run_time/valid_time schema accumulates exactly the data
needed to verify and re-tune them (PLAN.md open questions).

Rows land in SQLite under source='consensus' with valid_time = the block's
date; each generation is a new run_time, preserving history.
"""
import math
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

import db
from alerting import send_alert
from config import ISO_UTC, METEOCAT_ZONE_FOR_STATION, RESORTS
from meteocat_ingest import zone_station
from normalize import openmeteo_snowfall_cm_to_swe_mm

SOURCE = "consensus"

# A leg whose newest run is older than this is stale and excluded
# (provisional staleness policy — PLAN.md open question).
MAX_RUN_AGE_HOURS = 30.0

# Snow line sits below the isozero during precipitation; Meteocat's own
# guidance is a few hundred metres — validate against zonal cota in winter.
ISOZERO_TO_COTA_M = 300.0

# AEMET snow gate: precip counts as snow when pixel temperature <= this.
AEMET_SNOW_MAX_TEMP_C = 1.0

# Regime weights (openmeteo, aemet, meteocat) — the documented prior:
# N flows -> AROME leads; S/E flows -> AEMET+Meteocat lead; else neutral.
REGIME_N, REGIME_SE, REGIME_MIXED = 0.0, 1.0, 2.0
WEIGHTS = {
    REGIME_N: {"openmeteo": 0.50, "aemet": 0.25, "meteocat": 0.25},
    REGIME_SE: {"openmeteo": 0.20, "aemet": 0.40, "meteocat": 0.40},
    REGIME_MIXED: {"openmeteo": 1 / 3, "aemet": 1 / 3, "meteocat": 1 / 3},
}

# Confidence matrix (hand-tuned): agreement thresholds…
SNOW_AGREE_MM = 2.0          # absolute slack for "we all say ~nothing"
SNOW_AGREE_FRACTION = 0.35   # relative spread ceiling for agreement
COTA_AGREE_M = 150.0
COTA_OK_M = 300.0
SNOW_MATTERS_MM = 1.0        # below this, cota disagreement can't demote
ALTA, MITJANA, BAIXA = 2.0, 1.0, 0.0


# --- SQL helpers -------------------------------------------------------------

def latest_fresh_run(conn, source: str, now: datetime) -> Optional[str]:
    run = conn.execute(
        "SELECT MAX(run_time_utc) FROM forecast_values WHERE source=?",
        (source,)).fetchone()[0]
    if run is None:
        return None
    age = now - datetime.strptime(run, ISO_UTC).replace(tzinfo=timezone.utc)
    return run if age <= timedelta(hours=MAX_RUN_AGE_HOURS) else None


def day_values(conn, source: str, station: str, run: str, variable: str,
               day: str) -> Dict[str, float]:
    """valid_time -> value for one variable on one calendar day."""
    return dict(conn.execute(
        """SELECT valid_time_utc, value FROM forecast_values
           WHERE source=? AND station=? AND run_time_utc=? AND variable=?
             AND valid_time_utc LIKE ?""",
        (source, station, run, variable, day + "%")))


# --- per-leg extractors (all return None when the leg can't speak) -----------

def openmeteo_snow_swe(conn, station: str, run: str, day: str) -> Optional[float]:
    daily = day_values(conn, "openmeteo", station, run, "snowfall_sum", day)
    if daily:
        return openmeteo_snowfall_cm_to_swe_mm(sum(daily.values()))
    hourly = day_values(conn, "openmeteo", station, run, "snowfall", day)
    if hourly:
        return openmeteo_snowfall_cm_to_swe_mm(sum(hourly.values()))
    return None


def aemet_snow_swe(conn, station: str, run: str, day: str) -> Optional[float]:
    precip = day_values(conn, "aemet", station, run, "grid.precip.1h", day)
    temp = day_values(conn, "aemet", station, run, "grid.temperature", day)
    if not precip:
        return None
    # Bins are liquid mm (= SWE mm); gate by same-hour pixel temperature.
    return sum(p for t, p in precip.items()
               if temp.get(t) is not None and temp[t] <= AEMET_SNOW_MAX_TEMP_C)


def meteocat_snow_swe(conn, station: str, run: str, day: str) -> Optional[float]:
    from normalize import meteocat_bucket_to_swe_mm
    zona = zone_station(METEOCAT_ZONE_FOR_STATION[station])
    values = day_values(conn, "meteocat", zona, run, "zonal.acumulacioNeu.24h",
                        day)
    if not values:
        return None
    try:
        converted = [meteocat_bucket_to_swe_mm(v) for v in values.values()]
    except NotImplementedError:
        return None  # unit unconfirmed until winter — leg abstains
    return sum(c for c in converted if c is not None)


def openmeteo_cota(conn, station: str, run: str, day: str) -> Optional[float]:
    level = day_values(conn, "openmeteo", station, run,
                       "freezing_level_derived", day)
    if not level:
        return None
    precip = day_values(conn, "openmeteo", station, run, "precipitation", day)
    wet = [v for t, v in level.items() if precip.get(t, 0.0) > 0.1]
    chosen = wet or list(level.values())
    return sum(chosen) / len(chosen) - ISOZERO_TO_COTA_M


def meteocat_cota(conn, station: str, run: str, day: str) -> Optional[float]:
    zona = zone_station(METEOCAT_ZONE_FOR_STATION[station])
    cotes = day_values(conn, "meteocat", zona, run, "zonal.cota.6h", day)
    if cotes:
        return sum(cotes.values()) / len(cotes)
    iso = day_values(conn, "meteocat", station, run, "pic.isozero.totes", day)
    if iso:
        return sum(iso.values()) / len(iso) - ISOZERO_TO_COTA_M
    return None


def wind_direction(conn, runs: Dict[str, Optional[str]], station: str,
                   day: str) -> Optional[float]:
    """Circular mean of the best available upper-wind direction series."""
    candidates = (
        ("meteocat", station, "pic.direccio_vent.3000"),
        ("openmeteo", station, "wind_direction_700hPa"),
        ("aemet", station, "grid.wind_direction"),
    )
    for source, st, variable in candidates:
        if not runs.get(source):
            continue
        series = day_values(conn, source, st, runs[source], variable, day)
        if series:
            x = sum(math.cos(math.radians(v)) for v in series.values())
            y = sum(math.sin(math.radians(v)) for v in series.values())
            if x or y:
                return math.degrees(math.atan2(y, x)) % 360
    return None


# --- blending ----------------------------------------------------------------

def classify_regime(direction: Optional[float]) -> float:
    if direction is None:
        return REGIME_MIXED
    if direction >= 315 or direction <= 45:
        return REGIME_N
    if 90 <= direction <= 225:
        return REGIME_SE
    return REGIME_MIXED


def weighted_mean(values: Dict[str, float], regime: float) -> Optional[float]:
    """Blend per-leg values with regime weights renormalized over the legs
    actually present — a missing leg redistributes its weight, it doesn't
    silently count as zero."""
    present = {leg: v for leg, v in values.items() if v is not None}
    if not present:
        return None
    weights = WEIGHTS[regime]
    total = sum(weights[leg] for leg in present)
    return sum(weights[leg] * v for leg, v in present.items()) / total


def confidence(snow: Dict[str, Optional[float]],
               cota: Dict[str, Optional[float]]) -> float:
    """Hand-tuned matrix: leg count sets the ceiling, disagreement demotes."""
    snow_vals = [v for v in snow.values() if v is not None]
    if len(snow_vals) <= 1:
        return BAIXA
    label = ALTA if len(snow_vals) >= 3 else MITJANA

    mean = sum(snow_vals) / len(snow_vals)
    spread = max(snow_vals) - min(snow_vals)
    if spread > max(SNOW_AGREE_MM, SNOW_AGREE_FRACTION * mean):
        label -= 1

    cota_vals = [v for v in cota.values() if v is not None]
    if mean >= SNOW_MATTERS_MM and len(cota_vals) >= 2:
        cota_spread = max(cota_vals) - min(cota_vals)
        if cota_spread > COTA_OK_M:
            label -= 1
        elif cota_spread > COTA_AGREE_M and label == ALTA:
            label -= 1
    return max(label, BAIXA)


def build_consensus(conn, now: Optional[datetime] = None) -> List[db.Row]:
    now = now or datetime.now(timezone.utc)
    gen = now.strftime(ISO_UTC)
    runs = {s: latest_fresh_run(conn, s, now)
            for s in ("openmeteo", "aemet", "meteocat")}
    days = [(now.date() + timedelta(days=i)).isoformat() for i in (0, 1)]

    rows: List[db.Row] = []
    for resort in RESORTS:
        station = resort["station"]
        for day in days:
            snow = {
                "openmeteo": openmeteo_snow_swe(conn, station,
                                                runs["openmeteo"], day)
                if runs["openmeteo"] else None,
                "aemet": aemet_snow_swe(conn, station, runs["aemet"], day)
                if runs["aemet"] else None,
                "meteocat": meteocat_snow_swe(conn, station,
                                              runs["meteocat"], day)
                if runs["meteocat"] else None,
            }
            cota = {
                "openmeteo": openmeteo_cota(conn, station,
                                            runs["openmeteo"], day)
                if runs["openmeteo"] else None,
                "meteocat": meteocat_cota(conn, station,
                                          runs["meteocat"], day)
                if runs["meteocat"] else None,
            }
            regime = classify_regime(wind_direction(conn, runs, station, day))

            out = {
                "snow_swe_mm": weighted_mean(snow, regime),
                "cota_m": weighted_mean(cota, regime),
                "confidence": confidence(snow, cota),
                "regime": regime,
                "n_legs_snow": float(sum(v is not None
                                         for v in snow.values())),
            }
            for leg, v in snow.items():
                out[f"leg.{leg}.snow_swe_mm"] = v
            for leg, v in cota.items():
                out[f"leg.{leg}.cota_m"] = v
            rows.extend((SOURCE, station, gen, day, variable, value)
                        for variable, value in out.items() if value is not None)
    return rows


def main() -> None:
    conn = db.connect()
    rows = build_consensus(conn)
    if not rows:
        raise RuntimeError("consensus produced no rows — are the legs fresh?")
    count = db.upsert_rows(conn, rows)
    print(f"{SOURCE}: upserted {count} rows")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        send_alert(f"consensus failed: {exc}")
        raise
