"""The zone-assignment verifier must pick the zone whose cota tracks the
peak isozero, and stay silent (no verdict) while data is insufficient."""
import db
import verify_meteocat_zones as vz

RUN = "2026-12-01T13:30:00Z"


def _seed(conn, offsets_by_zone: dict, n_days: int):
    """Synthetic winter data: isozero for baqueira wobbles day to day; each
    zone's cota follows it with a fixed offset plus zone-specific noise."""
    rows = []
    for day in range(n_days):
        date = f"2026-12-{day + 1:02d}"
        run = f"{date}T13:30:00Z"
        for hour, iso in ((0, 2400 + 100 * (day % 3)),
                          (6, 2500 + 120 * (day % 4)),
                          (12, 2600 - 80 * (day % 3)),
                          (18, 2450 + 60 * (day % 5))):
            for h in (hour, hour + 3):
                rows.append(("meteocat", "baqueira", run,
                             f"{date}T{h:02d}:00Z", "pic.isozero.totes",
                             float(iso)))
            for zone, (offset, noise) in offsets_by_zone.items():
                wobble = noise * ((day + hour) % 5 - 2)
                rows.append(("meteocat", zone, run, f"{date}T{hour:02d}:00Z",
                             "zonal.cota.6h", float(iso + offset + wobble)))
    db.upsert_rows(conn, rows)


def test_best_tracking_zone_wins(tmp_path):
    conn = db.connect(tmp_path / "zones.sqlite")
    # zona_1 tracks tightly (-300 m, small noise); zona_4 drifts wildly
    _seed(conn, {"zona_1": (-300, 10), "zona_4": (-300, 400)}, n_days=5)
    samples = vz.zone_offsets(conn, "baqueira")
    assert len(samples["zona_1"]) >= vz.MIN_SAMPLES
    import statistics
    mad = {z: statistics.median(
        abs(o - statistics.median(offs)) for o in offs)
        for z, offs in samples.items()}
    assert mad["zona_1"] < mad["zona_4"]


def test_no_samples_without_winter_cota_rows(tmp_path):
    conn = db.connect(tmp_path / "empty.sqlite")
    db.upsert_rows(conn, [("meteocat", "baqueira", RUN,
                           "2026-12-01T00:00Z", "pic.isozero.totes", 2400.0)])
    assert vz.zone_offsets(conn, "baqueira") == {}
