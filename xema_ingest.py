"""Ingest the XEMA observation leg: nowcast ground truth per resort.

Auth: `METEOCAT_API_KEY` env var (X-Api-Key) — the XEMA plan on the same
key allows 750 calls/month, separate from the Predicció plan's 100.

Quota discipline:
- station-day endpoint: 1 call per station per cycle (6 stations);
  decide_legs gates cycles on >8h reading staleness (~3 cycles/day →
  ~570 calls/month nominal, ~720 on drift days)
- yesterday backfill: +1 call per station, only while that station's
  stored yesterday readings stop before 23:00Z AND it is still morning
  (fills the overnight gap once; the morning guard bounds a permanent
  upstream gap to two attempts)

Storage convention — observations, not forecasts: run_time_utc ==
valid_time_utc == the reading's own timestamp. Refetching a day upserts
the same keys, so re-ingestion and XEMA's later data revisions are
idempotent, and decide_legs can gate on MAX(run_time_utc) = the newest
reading. Only the nowcast-relevant variables go into SQLite (VARIABLES);
the archive keeps every raw payload for later re-parsing.

Payload shape (recon 2026-07-13, data/xema_recon_report.json):
[{codi: "Z1", variables: [{codi: 32, lectures: [{data, dataExtrem?,
valor, estat, baseHoraria}]}]}] — semi-hourly readings, ~43 min latency.
`estat` is XEMA's validation flag; recent readings are always unvalidated
(blank), so it is not filtered on.
"""
import json
import os
from datetime import datetime, timedelta, timezone
from typing import List, Optional

import db
from alerting import send_alert
from archive import archive_payload
from config import XEMA_STATIONS
from httpcache import cached_get

SOURCE = "xema"
BASE = "https://api.meteo.cat"

# XEMA variable code -> stored variable name. Everything else stays in the
# raw archive only (extend here + rebuild_db.py to backfill new variables).
# 32/33 at the high+valley pair give the observed lapse rate and wet-bulb
# inputs; 35 is the undercatch-prone gauge precip; 38 is new-snow ground
# truth where fitted (Z1, Z2, YN, DP — la Tosa d'Alp [ZD] has no gauge or
# snow sensor, so la_molina precip/snow obs come from Das [DP] only).
VARIABLES = {
    32: "obs.temperatura",   # °C
    33: "obs.humitat",       # %
    35: "obs.precipitacio",  # mm (semi-hourly accumulation)
    38: "obs.gruix_neu",     # cm on the ground
}

# Backfill yesterday only until this UTC hour: with the ~8h cycle gate at
# most two morning cycles can retry a gap, bounding a dead upstream day.
BACKFILL_UNTIL_HOUR = 12


def _headers() -> dict:
    key = os.environ.get("METEOCAT_API_KEY")
    if not key:
        raise RuntimeError("METEOCAT_API_KEY not set")
    return {"X-Api-Key": key}


def _get(path: str) -> bytes:
    status, body, _ = cached_get(BASE + path, headers=_headers())
    if status != 200:
        raise RuntimeError(f"XEMA returned HTTP {status} for {path}")
    return body


def _as_float(valor) -> Optional[float]:
    if isinstance(valor, bool) or valor is None:
        return None
    try:
        return float(valor)
    except (TypeError, ValueError):
        return None


def parse_xema(payload: bytes, run_time_utc: str, name: str) -> List[db.Row]:
    """One row per (station, reading, tracked variable).

    The station code and reading timestamps come from the payload itself
    (never the filename), and run_time_utc is IGNORED: observation rows
    carry their own time as both run and valid time, so live ingest and
    archive rebuild produce identical rows.
    """
    rows: List[db.Row] = []
    body = json.loads(payload)
    for station in body if isinstance(body, list) else []:
        codi = station.get("codi")
        if not codi:
            continue
        for var in station.get("variables") or []:
            variable = VARIABLES.get(var.get("codi"))
            if variable is None:
                continue
            for lecture in var.get("lectures") or []:
                when = lecture.get("data")
                value = _as_float(lecture.get("valor"))
                if when and value is not None:
                    rows.append((SOURCE, codi, str(when), str(when),
                                 variable, value))
    return rows


def needs_backfill(conn, code: str, day) -> bool:
    """True while `code`'s stored readings for `day` stop before 23:00Z."""
    newest = conn.execute(
        "SELECT MAX(valid_time_utc) FROM forecast_values"
        " WHERE source = ? AND station = ? AND valid_time_utc LIKE ?",
        (SOURCE, code, f"{day.isoformat()}%")).fetchone()[0]
    return newest is None or newest < f"{day.isoformat()}T23:00Z"


def main() -> None:
    fetched_at = datetime.now(timezone.utc)
    today = fetched_at.date()
    yesterday = today - timedelta(days=1)
    conn = db.connect()

    rows: List[db.Row] = []
    calls = 0
    for st in XEMA_STATIONS:
        code = st["code"]
        dates = [today]
        if (fetched_at.hour < BACKFILL_UNTIL_HOUR
                and needs_backfill(conn, code, yesterday)):
            dates.append(yesterday)
        for d in dates:
            name = f"day_{code}_{d.isoformat()}.json"
            body = _get(f"/xema/v1/estacions/mesurades/{code}"
                        f"/{d.year}/{d.month:02d}/{d.day:02d}")
            archive_payload(SOURCE, name, body, fetched_at)
            rows.extend(parse_xema(body, "", name))
            calls += 1
        print(f"  {code} ({st['resort']}/{st['role']}): "
              f"{len(dates)} day(s) fetched")

    count = db.upsert_rows(conn, rows)
    print(f"{SOURCE}: archived {calls} payloads, upserted {count} rows")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        send_alert(f"xema_ingest failed: {exc}")
        raise
