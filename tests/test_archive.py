import gzip
from datetime import datetime, timezone

from archive import archive_payload, iter_archived, run_time_from_path

FETCHED = datetime(2026, 7, 12, 11, 30, 45, tzinfo=timezone.utc)


def test_roundtrip_and_layout(tmp_path):
    payload = b'{"hello": "snow"}'
    path = archive_payload("openmeteo", "forecast.json", payload,
                           fetched_at=FETCHED, raw_dir=tmp_path)

    assert path.relative_to(tmp_path).parts == (
        "openmeteo", "2026", "07", "12", "20260712T113045Z_forecast.json.gz")
    with gzip.open(path, "rb") as f:
        assert f.read() == payload


def test_iter_archived_oldest_first(tmp_path):
    first = datetime(2026, 7, 11, 8, 0, 0, tzinfo=timezone.utc)
    archive_payload("openmeteo", "forecast.json", b"new", FETCHED, tmp_path)
    archive_payload("openmeteo", "forecast.json", b"old", first, tmp_path)

    payloads = list(iter_archived("openmeteo", raw_dir=tmp_path))
    assert [raw for _, raw in payloads] == [b"old", b"new"]


def test_iter_archived_missing_source_is_empty(tmp_path):
    assert list(iter_archived("nonexistent", raw_dir=tmp_path)) == []


def test_run_time_recovered_from_filename(tmp_path):
    path = archive_payload("openmeteo", "forecast.json", b"{}",
                           fetched_at=FETCHED, raw_dir=tmp_path)
    assert run_time_from_path(path) == "2026-07-12T11:30:45Z"
