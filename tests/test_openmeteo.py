import json
from datetime import datetime, timezone

import db
import openmeteo_ingest as om
from archive import archive_payload, iter_archived, run_time_from_path
from config import RESORTS
from freezing_level import PRESSURE_LEVELS

TIMES = ["2026-07-12T00:00", "2026-07-12T01:00"]
DAILY_TIMES = ["2026-07-12"]
# 5, 2, -1, -4 °C at 100/1000/1900/2800 m -> isozero at 1600 m
LEVEL_TEMPS = [5.0, 2.0, -1.0, -4.0]
LEVEL_HEIGHTS = [100.0, 1000.0, 1900.0, 2800.0]
EXPECTED_ISOZERO = 1600.0


def make_payload() -> bytes:
    """Multi-location response; element 0 has NO location_id (real quirk)."""
    blocks = []
    for i in range(len(RESORTS)):
        hourly = {"time": list(TIMES)}
        for var in om.HOURLY_VARIABLES:
            hourly[var] = [float(i), float(i) + 0.5]
        for p, temp, height in zip(PRESSURE_LEVELS, LEVEL_TEMPS, LEVEL_HEIGHTS):
            hourly[f"temperature_{p}hPa"] = [temp, temp]
            hourly[f"geopotential_height_{p}hPa"] = [height, height]
        daily = {"time": list(DAILY_TIMES)}
        for var in om.DAILY_VARIABLES:
            daily[var] = [10.0 + i]
        block = {"hourly": hourly, "daily": daily}
        if i > 0:
            block["location_id"] = i
        blocks.append(block)
    return json.dumps(blocks).encode("utf-8")


RUN_TIME = "2026-07-12T11:30:45Z"


def test_blocks_are_zipped_by_position():
    rows = om.parse_openmeteo(make_payload(), RUN_TIME)
    by_station = {
        (r[1], r[3]): r[5] for r in rows if r[4] == "temperature_2m"}
    for i, resort in enumerate(RESORTS):
        assert by_station[(resort["station"], "2026-07-12T00:00:00Z")] == float(i)


def test_freezing_level_is_derived_per_hour():
    rows = om.parse_openmeteo(make_payload(), RUN_TIME)
    derived = [r for r in rows if r[4] == "freezing_level_derived"]
    capped = [r for r in rows if r[4] == "freezing_level_capped"]
    assert len(derived) == len(RESORTS) * len(TIMES)
    assert all(r[5] == EXPECTED_ISOZERO for r in derived)
    assert all(r[5] == 0.0 for r in capped)


def test_daily_rows_keep_date_only_valid_time():
    rows = om.parse_openmeteo(make_payload(), RUN_TIME)
    daily = [r for r in rows if r[4] == "snowfall_sum"]
    assert len(daily) == len(RESORTS)
    assert all(r[3] == "2026-07-12" for r in daily)


def test_no_ensemble_probability_requested():
    assert "precipitation_probability" not in om.HOURLY_VARIABLES
    assert "precipitation_probability" not in om.build_url()


def test_wrong_block_count_raises():
    payload = json.dumps([{"hourly": {"time": []}}]).encode("utf-8")
    try:
        om.parse_openmeteo(payload, RUN_TIME)
    except ValueError as exc:
        assert "location blocks" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_rebuild_from_archive_matches_direct_ingest(tmp_path):
    """The SQLite view must be reproducible from the raw archive alone."""
    payload = make_payload()
    fetched_at = datetime(2026, 7, 12, 11, 30, 45, tzinfo=timezone.utc)
    direct_rows = om.parse_openmeteo(payload, RUN_TIME)

    archive_payload(om.SOURCE, "forecast.json", payload,
                    fetched_at=fetched_at, raw_dir=tmp_path)
    conn = db.connect(tmp_path / "rebuild.sqlite")
    for path, raw in iter_archived(om.SOURCE, raw_dir=tmp_path):
        db.upsert_rows(conn, om.parse_openmeteo(raw, run_time_from_path(path)))

    rebuilt = conn.execute(
        """SELECT source, station, run_time_utc, valid_time_utc, variable, value
           FROM forecast_values
           ORDER BY source, station, run_time_utc, valid_time_utc, variable"""
    ).fetchall()
    assert rebuilt == sorted(direct_rows)
