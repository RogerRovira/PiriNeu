from datetime import datetime, timezone

import db
import decide_legs


def at(hour, minute=37, day=13):
    return datetime(2026, 7, day, hour, minute, tzinfo=timezone.utc)


def conn_with(tmp_path, *runs):
    """DB holding one row per (source, run_time_utc)."""
    conn = db.connect(tmp_path / "test.sqlite")
    db.upsert_rows(conn, [(source, "baqueira", run_time,
                           "2026-07-14T06:00:00Z", "snowfall", 1.0)
                          for source, run_time in runs])
    return conn


def test_openmeteo_runs_on_every_firing(tmp_path):
    # AEMET is up to date (18 UTC cycle of the day before), so at 01 UTC
    # nothing but the always-on Open-Meteo leg is due.
    conn = conn_with(tmp_path, ("aemet", "2026-07-12T18:00:00Z"))
    assert decide_legs.decide(at(1), conn) == ["openmeteo"]


def test_empty_db_schedules_aemet(tmp_path):
    assert "aemet" in decide_legs.decide(at(1), conn_with(tmp_path))


def test_aemet_expected_run_respects_publication_lag():
    # The 12 UTC cycle publishes ~14:45: at 14:37 it is not out yet...
    assert decide_legs.aemet_expected_run(at(14)) == "2026-07-13T06:00:00Z"
    # ...at the next odd-hour firing (15:37) it is.
    assert decide_legs.aemet_expected_run(at(15)) == "2026-07-13T12:00:00Z"


def test_aemet_skipped_until_a_newer_cycle_is_published(tmp_path):
    conn = conn_with(tmp_path, ("aemet", "2026-07-13T12:00:00Z"))
    assert "aemet" not in decide_legs.decide(at(15), conn)
    assert "aemet" in decide_legs.decide(at(21), conn)  # 18 UTC cycle due


def test_meteocat_waits_for_publication_window(tmp_path):
    conn = conn_with(tmp_path)
    assert "meteocat" not in decide_legs.decide(at(11), conn)
    assert "meteocat" in decide_legs.decide(at(13), conn)
    # A dropped 13 UTC firing is caught up later the same day...
    assert "meteocat" in decide_legs.decide(at(19), conn)
    # ...but retries stop at LAST_HOUR to bound quota spend.
    assert "meteocat" not in decide_legs.decide(at(21), conn)


def test_meteocat_runs_once_per_day(tmp_path):
    conn = conn_with(tmp_path, ("meteocat", "2026-07-13T13:40:00Z"))
    assert "meteocat" not in decide_legs.decide(at(15), conn)
    assert "meteocat" in decide_legs.decide(at(13, day=14), conn)


def test_healthcheck_runs_once_per_day_after_eight(tmp_path):
    conn = conn_with(tmp_path)
    assert "healthcheck" not in decide_legs.decide(at(7), conn)
    assert "healthcheck" in decide_legs.decide(at(9), conn)
    assert "healthcheck" in decide_legs.decide(at(9), conn, "2026-07-12")
    assert "healthcheck" not in decide_legs.decide(at(9), conn, "2026-07-13")
