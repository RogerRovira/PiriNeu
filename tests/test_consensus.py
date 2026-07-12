"""Consensus engine: regime weights, degraded modes, confidence matrix."""
from datetime import datetime, timezone

import pytest

import consensus as cs
import db

NOW = datetime(2026, 12, 20, 15, 0, tzinfo=timezone.utc)
RUN = "2026-12-20T13:00:00Z"
D0 = "2026-12-20"


def test_classify_regime_sectors():
    assert cs.classify_regime(350.0) == cs.REGIME_N
    assert cs.classify_regime(20.0) == cs.REGIME_N
    assert cs.classify_regime(120.0) == cs.REGIME_SE
    assert cs.classify_regime(225.0) == cs.REGIME_SE
    assert cs.classify_regime(270.0) == cs.REGIME_MIXED
    assert cs.classify_regime(None) == cs.REGIME_MIXED


def test_weighted_mean_renormalizes_over_present_legs():
    values = {"openmeteo": 10.0, "aemet": 20.0, "meteocat": None}
    # N weights .5/.25/.25 -> renormalized over {om,aemet}: 2/3 vs 1/3
    assert cs.weighted_mean(values, cs.REGIME_N) == pytest.approx(40 / 3)
    # SE weights .2/.4 -> 1/3 vs 2/3
    assert cs.weighted_mean(values, cs.REGIME_SE) == pytest.approx(50 / 3)
    assert cs.weighted_mean({"openmeteo": None, "aemet": None,
                             "meteocat": None}, cs.REGIME_N) is None


def test_confidence_matrix():
    agree3 = {"openmeteo": 10.0, "aemet": 11.0, "meteocat": 9.5}
    cota_ok = {"openmeteo": 1800.0, "meteocat": 1900.0}
    assert cs.confidence(agree3, cota_ok) == cs.ALTA
    # big amount spread demotes
    spread3 = {"openmeteo": 2.0, "aemet": 20.0, "meteocat": 10.0}
    assert cs.confidence(spread3, cota_ok) == cs.MITJANA
    # two legs cap at Mitjana even in agreement
    agree2 = {"openmeteo": 10.0, "aemet": 10.5, "meteocat": None}
    assert cs.confidence(agree2, cota_ok) == cs.MITJANA
    # one leg is always Baixa
    assert cs.confidence({"openmeteo": 10.0, "aemet": None,
                          "meteocat": None}, cota_ok) == cs.BAIXA
    # wildly different cotas demote when snow is expected...
    cota_bad = {"openmeteo": 1500.0, "meteocat": 2200.0}
    assert cs.confidence(agree3, cota_bad) == cs.MITJANA
    # ...but not when everyone says "no snow"
    none3 = {"openmeteo": 0.0, "aemet": 0.0, "meteocat": 0.1}
    assert cs.confidence(none3, cota_bad) == cs.ALTA


def _seed_winter_day(conn):
    rows = []
    om = lambda var, t, v: rows.append(("openmeteo", "baqueira", RUN,
                                        t, var, v))
    # Open-Meteo: 7 cm day total, freezing level, wind from the north
    om("snowfall_sum", D0, 7.0)
    for h in (9, 12):
        t = f"{D0}T{h:02d}:00:00Z"
        om("freezing_level_derived", t, 2100.0)
        om("precipitation", t, 1.0)
        om("wind_direction_700hPa", t, 350.0)
    # AEMET: 8 mm liquid in 4 cold hours + 2 mm in a warm hour (gated out)
    for h, temp in ((6, -1.0), (9, 0.0), (12, 1.0), (15, 0.5), (18, 5.0)):
        t = f"{D0}T{h:02d}:00:00Z"
        rows.append(("aemet", "baqueira", RUN, t, "grid.precip.1h", 2.0))
        rows.append(("aemet", "baqueira", RUN, t, "grid.temperature", temp))
    # Meteocat: zonal cota for baqueira's zone + peak wind from the north
    for h in (6, 12):
        rows.append(("meteocat", "zona_1", RUN, f"{D0}T{h:02d}:00Z",
                     "zonal.cota.6h", 1800.0))
        rows.append(("meteocat", "baqueira", RUN, f"{D0}T{h:02d}:00Z",
                     "pic.direccio_vent.3000", 355.0))
    db.upsert_rows(conn, rows)


def test_build_consensus_end_to_end(tmp_path):
    conn = db.connect(tmp_path / "c.sqlite")
    _seed_winter_day(conn)
    rows = cs.build_consensus(conn, now=NOW)
    got = {(r[1], r[3], r[4]): r[5] for r in rows}

    # N regime detected from Meteocat peak wind
    assert got[("baqueira", D0, "regime")] == cs.REGIME_N
    # leg inputs recorded next to the blend
    assert got[("baqueira", D0, "leg.openmeteo.snow_swe_mm")] == \
        pytest.approx(10.0)  # 7 cm / 0.7
    assert got[("baqueira", D0, "leg.aemet.snow_swe_mm")] == 8.0
    assert ("baqueira", D0, "leg.meteocat.snow_swe_mm") not in got  # abstains
    # blend: N weights renormalized over {om,aemet} -> (0.5*10+0.25*8)/0.75
    assert got[("baqueira", D0, "snow_swe_mm")] == pytest.approx(28 / 3)
    # cota blends the om (2100-300) and meteocat zonal (1800) legs
    assert got[("baqueira", D0, "leg.openmeteo.cota_m")] == 1800.0
    assert got[("baqueira", D0, "leg.meteocat.cota_m")] == 1800.0
    assert got[("baqueira", D0, "cota_m")] == 1800.0
    # two snow legs -> Mitjana ceiling
    assert got[("baqueira", D0, "confidence")] == cs.MITJANA
    # resorts without any data still get a (Baixa, no-legs) block
    assert got[("boi_taull", D0, "n_legs_snow")] == 0.0
    assert got[("boi_taull", D0, "confidence")] == cs.BAIXA


def test_stale_runs_are_excluded(tmp_path):
    conn = db.connect(tmp_path / "stale.sqlite")
    _seed_winter_day(conn)
    later = datetime(2026, 12, 22, 15, 0, tzinfo=timezone.utc)  # RUN + >30h
    assert cs.latest_fresh_run(conn, "openmeteo", later) is None
    rows = cs.build_consensus(conn, now=later)
    got = {(r[1], r[3], r[4]): r[5] for r in rows}
    assert got[("baqueira", "2026-12-22", "n_legs_snow")] == 0.0
