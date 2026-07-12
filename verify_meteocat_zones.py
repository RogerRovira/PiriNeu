#!/usr/bin/env python3
"""Data-driven check of the resort -> Meteocat-zone assignment.

The Pirineu zonal endpoint offers no zone geometry (no zones metadades
endpoint exists), so config.METEOCAT_ZONE_FOR_STATION is assembled from
zone names and published descriptions. This script tests that assignment
against the data itself, with NO API calls: zonal rows are stored for all
seven zones (`zona_<id>`), and each anchor peak's forecast provides an
independent, resort-specific reference (`pic.isozero.totes`).

Signal: the snow line (`zonal.cota.6h`) of the RIGHT zone should track the
peak's isozero more closely than any other zone's. Both series come from
the same Meteocat run, so on days with snow the comparison is clean. Cota
values only appear in winter payloads — until they accumulate, the script
reports "insufficient data" rather than a verdict.

For every resort it reports, per zone: matched samples, median offset
(cota - isozero, expected around -200..-400 m), the MAD around that median
(robust tracking error, the ranking key), and flags disagreement with the
configured zone.

Usage: python verify_meteocat_zones.py [--db PATH] [--min-samples N]
"""
import argparse
import statistics
import sys
from collections import defaultdict
from datetime import datetime, timedelta

import db
from config import METEOCAT_ZONE_FOR_STATION

MIN_SAMPLES = 8  # a couple of snow episodes before any verdict


def _parse_valid(t: str):
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%MZ"):
        try:
            return datetime.strptime(t, fmt)
        except ValueError:
            continue
    return None


def load_series(conn, variable_like: str, station_like: str):
    """(station, run_time) -> {valid_datetime: value}"""
    out = defaultdict(dict)
    for station, run, valid, value in conn.execute(
            """SELECT station, run_time_utc, valid_time_utc, value
               FROM forecast_values
               WHERE source='meteocat' AND variable LIKE ? AND station LIKE ?""",
            (variable_like, station_like)):
        t = _parse_valid(valid)
        if t is not None:
            out[(station, run)][t] = value
    return out


def zone_offsets(conn, station: str):
    """zone -> list of (cota - isozero) samples for one resort's peak.

    A zonal cota (6 h franja starting at T) is matched with the mean of the
    peak isozero at T and T+3h from the SAME run.
    """
    isozero = load_series(conn, "pic.isozero.totes", station)
    cotes = load_series(conn, "zonal.cota.6h", "zona_%")
    samples = defaultdict(list)
    for (zone, run), series in cotes.items():
        ref = isozero.get((station, run))
        if not ref:
            continue
        for t, cota in series.items():
            refs = [ref[x] for x in (t, t + timedelta(hours=3)) if x in ref]
            if refs:
                samples[zone].append(cota - sum(refs) / len(refs))
    return samples


def main() -> int:
    argp = argparse.ArgumentParser(description=__doc__)
    argp.add_argument("--db", default=None)
    argp.add_argument("--min-samples", type=int, default=MIN_SAMPLES)
    args = argp.parse_args()

    conn = db.connect(args.db)
    all_ok = True
    for station, configured in METEOCAT_ZONE_FOR_STATION.items():
        print(f"\n== {station} (configured: zona_{configured}) ==")
        samples = zone_offsets(conn, station)
        scored = []
        for zone, offs in sorted(samples.items()):
            med = statistics.median(offs)
            mad = statistics.median(abs(o - med) for o in offs)
            scored.append((mad, zone, med, len(offs)))
            print(f"  {zone:8s} n={len(offs):4d} median_offset={med:+7.0f} m "
                  f"MAD={mad:6.0f} m")
        usable = [s for s in scored if s[3] >= args.min_samples]
        if not usable:
            print(f"  insufficient data (<{args.min_samples} samples/zone) — "
                  "rerun after winter payloads accumulate")
            continue
        best = min(usable)
        verdict_zone = best[1]
        if verdict_zone == f"zona_{configured}":
            print(f"  OK: best-tracking zone is the configured one "
                  f"({verdict_zone}, MAD {best[0]:.0f} m)")
        else:
            all_ok = False
            print(f"  MISMATCH: {verdict_zone} tracks {station}'s isozero "
                  f"best (MAD {best[0]:.0f} m) — review "
                  f"METEOCAT_ZONE_FOR_STATION in config.py")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
