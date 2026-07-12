import db
import normalize
import pytest
from config import RESORTS


def test_openmeteo_snowfall_conversion_is_7_to_1():
    # 7 cm of snow == 10 mm water equivalent in Open-Meteo's scheme
    assert normalize.openmeteo_snowfall_cm_to_swe_mm(7.0) == pytest.approx(10.0)
    assert normalize.openmeteo_snowfall_cm_to_swe_mm(0.0) == 0.0


def test_unresolved_source_mappings_fail_loudly():
    with pytest.raises(NotImplementedError):
        normalize.meteocat_bucket_to_swe_mm("moderada")
    with pytest.raises(NotImplementedError):
        normalize.aemet_snow_mm_to_swe_mm(5.0)


def test_elevation_bands_cover_all_resorts():
    assert set(normalize.RESORT_ELEVATIONS_M) == {
        r["station"] for r in RESORTS}
    for bands in normalize.RESORT_ELEVATIONS_M.values():
        assert bands["base"] < bands["mid"] < bands["top"]


RUN = "2026-07-12T11:00:00Z"


def _seed(conn, hours_and_cm):
    rows = [("openmeteo", "baqueira", RUN,
             f"2026-07-{12 + (11 + h) // 24:02d}T{(11 + h) % 24:02d}:00:00Z",
             "snowfall", cm)
            for h, cm in hours_and_cm]
    db.upsert_rows(conn, rows)


def test_accumulated_swe_sums_only_the_window(tmp_path):
    conn = db.connect(tmp_path / "t.sqlite")
    # 0.7 cm at +1 h and +23 h (inside 24 h); 7 cm at +25 h (outside)
    _seed(conn, [(1, 0.7), (23, 0.7), (25, 7.0)])

    swe_24 = normalize.accumulated_swe_mm(conn, "openmeteo", "baqueira",
                                          RUN, 24)
    swe_48 = normalize.accumulated_swe_mm(conn, "openmeteo", "baqueira",
                                          RUN, 48)
    assert swe_24 == pytest.approx(2.0)   # 1.4 cm -> 2 mm SWE
    assert swe_48 == pytest.approx(12.0)  # + 7 cm -> +10 mm SWE


def test_accumulated_swe_none_when_no_rows(tmp_path):
    conn = db.connect(tmp_path / "t.sqlite")
    assert normalize.accumulated_swe_mm(
        conn, "openmeteo", "baqueira", RUN, 24) is None
