"""Fixtures mirror the REAL XEMA station-day payload (recon 2026-07-13,
data/xema_recon_report.json): a list of stations, each with per-variable
`lectures` carrying semi-hourly readings with `estat`/`baseHoraria`
metadata and optional `dataExtrem`.
"""
import datetime
import json

import db
import xema_ingest as xe
from archive import archive_payload, iter_archived, run_time_from_path


def day_payload() -> bytes:
    return json.dumps([
        {"codi": "Z1", "variables": [
            # humitat relativa màxima: real but untracked -> no rows
            {"codi": 3, "lectures": [
                {"data": "2026-07-13T00:00Z", "dataExtrem": "2026-07-13T00:11Z",
                 "valor": 34, "estat": " ", "baseHoraria": "SH"}]},
            {"codi": 32, "lectures": [
                {"data": "2026-07-13T00:00Z", "valor": 8.4, "estat": " ",
                 "baseHoraria": "SH"},
                {"data": "2026-07-13T00:30Z", "valor": 8.1, "estat": "V",
                 "baseHoraria": "SH"},
                # a reading without a valor yields no row
                {"data": "2026-07-13T01:00Z", "estat": " ",
                 "baseHoraria": "SH"}]},
            {"codi": 38, "lectures": [
                {"data": "2026-07-13T00:00Z", "valor": 0, "estat": " ",
                 "baseHoraria": "SH"}]},
        ]},
        {"codi": "YN", "variables": [
            {"codi": 35, "lectures": [
                {"data": "2026-07-13T00:30Z", "valor": 0.2, "estat": " ",
                 "baseHoraria": "SH"}]},
        ]},
    ]).encode("utf-8")


def test_rows_track_only_the_nowcast_variables():
    rows = xe.parse_xema(day_payload(), "", "day_Z1_2026-07-13.json")
    by_key = {(r[1], r[3], r[4]): r[5] for r in rows}
    assert by_key == {
        ("Z1", "2026-07-13T00:00Z", "obs.temperatura"): 8.4,
        ("Z1", "2026-07-13T00:30Z", "obs.temperatura"): 8.1,
        ("Z1", "2026-07-13T00:00Z", "obs.gruix_neu"): 0.0,
        ("YN", "2026-07-13T00:30Z", "obs.precipitacio"): 0.2,
    }


def test_observation_rows_use_their_own_time_as_run_time():
    # run_time == valid_time makes refetches idempotent and lets
    # decide_legs gate on MAX(run_time) = newest reading; the run_time
    # argument (the archive fetch stamp on rebuild) must be ignored.
    rows = xe.parse_xema(day_payload(), "2026-07-13T18:45:00Z", "x.json")
    assert rows and all(r[2] == r[3] for r in rows)


def test_unexpected_shapes_yield_no_rows_without_crashing():
    assert xe.parse_xema(b'{"not": "a list"}', "", "x.json") == []
    assert xe.parse_xema(b'[{"variables": [{"codi": 32}]}]', "", "x.json") == []


def test_needs_backfill_until_the_evening_readings_exist(tmp_path):
    conn = db.connect(tmp_path / "t.sqlite")
    day = datetime.date(2026, 7, 13)
    assert xe.needs_backfill(conn, "Z1", day)  # nothing stored at all
    db.upsert_rows(conn, [(xe.SOURCE, "Z1", "2026-07-13T22:30Z",
                           "2026-07-13T22:30Z", "obs.temperatura", 5.0)])
    assert xe.needs_backfill(conn, "Z1", day)  # evening gap remains
    db.upsert_rows(conn, [(xe.SOURCE, "Z1", "2026-07-13T23:30Z",
                           "2026-07-13T23:30Z", "obs.temperatura", 4.0)])
    assert not xe.needs_backfill(conn, "Z1", day)
    # per-station: another station's day is still open
    assert xe.needs_backfill(conn, "ZD", day)


def test_rebuild_parity_from_archive(tmp_path):
    fetched = datetime.datetime(2026, 7, 13, 18, 45, 0,
                                tzinfo=datetime.timezone.utc)
    archive_payload(xe.SOURCE, "day_Z1_2026-07-13.json", day_payload(),
                    fetched, tmp_path)
    conn = db.connect(tmp_path / "rebuild.sqlite")
    total = 0
    for path, raw in iter_archived(xe.SOURCE, raw_dir=tmp_path):
        total += db.upsert_rows(
            conn, xe.parse_xema(raw, run_time_from_path(path), path.name))
    stored = conn.execute("SELECT COUNT(*) FROM forecast_values").fetchone()[0]
    assert stored == total > 0
    # re-ingesting the same payload is a no-op (same PKs upserted)
    for path, raw in iter_archived(xe.SOURCE, raw_dir=tmp_path):
        db.upsert_rows(conn, xe.parse_xema(raw, run_time_from_path(path),
                                           path.name))
    assert conn.execute("SELECT COUNT(*) FROM forecast_values"
                        ).fetchone()[0] == stored
