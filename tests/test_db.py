import db


def row(value):
    return ("openmeteo", "la-molina", "2026-07-12T11:00:00Z",
            "2026-07-13T06:00:00Z", "snowfall", value)


def test_upsert_is_idempotent(tmp_path):
    conn = db.connect(tmp_path / "test.sqlite")
    db.upsert_rows(conn, [row(1.2)])
    db.upsert_rows(conn, [row(1.2)])

    count, value = conn.execute(
        "SELECT COUNT(*), MAX(value) FROM forecast_values").fetchone()
    assert (count, value) == (1, 1.2)


def test_upsert_updates_value_on_conflict(tmp_path):
    conn = db.connect(tmp_path / "test.sqlite")
    db.upsert_rows(conn, [row(1.2)])
    db.upsert_rows(conn, [row(3.4)])

    count, value = conn.execute(
        "SELECT COUNT(*), MAX(value) FROM forecast_values").fetchone()
    assert (count, value) == (1, 3.4)
