"""Fixtures mirror REAL Meteocat payloads (archived 2026-07-12): zonal
franjes carry no date and wrap values in variablesValors with string
valors; pics are 3-hourly timesteps with per-cota numeric variables.
Winter-only fields (acumulacioNeu/cota with a valor) are included here the
way the schema delivers them, even though July payloads omit the valor.
"""
import json

import db
import meteocat_ingest as mc
from archive import archive_payload, iter_archived, run_time_from_path

RUN = "2026-07-12T13:30:00Z"


def zones_payload() -> bytes:
    return json.dumps({
        "dataPrediccio": "2026-07-13Z",
        "dataPublicacio": "2026-07-12T08:42Z",
        "franjes": [
            {"idTipusFranja": 5, "nom": "24h",
             "zones": [
                 {"idZona": 1, "nom": "Vessant nord Pirineu occi",
                  "variablesValors": [
                      {"nom": "acumulacio", "valor": "5", "periode": 2},
                      {"nom": "acumulacioNeu", "valor": "12", "periode": 2},
                      {"nom": "comentari", "periode": 2},
                  ]},
                 {"idZona": 4, "nom": "Pirineu oriental",
                  "variablesValors": [
                      {"nom": "acumulacioNeu", "valor": "20", "periode": 2},
                  ]},
             ]},
            # real-payload quirk: "06:00 - 12:00h" (no h on the first time)
            {"idTipusFranja": 2, "nom": "06:00 - 12:00h",
             "zones": [
                 {"idZona": 5, "nom": "Vessant sud Pirineu occid",
                  "variablesValors": [
                      {"nom": "cel", "valor": "3", "periode": 1},
                      {"nom": "cota", "valor": "1800", "periode": 1},
                      {"nom": "probabilitat", "valor": "1", "periode": 1},
                      {"nom": "comentari", "periode": 2},
                      {"nom": "acumulacio", "periode": 2},  # no valor today
                  ]},
                 {"idZona": 6, "nom": "Vessant sud Prepirineu or",
                  "variablesValors": [
                      {"nom": "tempesta", "valor": "1", "periode": 1},
                  ]},
             ]},
        ],
    }).encode("utf-8")


def pic_payload() -> bytes:
    return json.dumps([
        {"data": "2026-07-13T06:00Z",
         "cotes": [
             {"cota": "totes",
              "variables": [{"nom": "isozero", "valor": 1900},
                            {"nom": "iso-10", "valor": 3200}]},
             {"cota": "2500",
              "variables": [{"nom": "temperatura", "valor": -2.5},
                            {"nom": "velocitat vent", "valor": 18},
                            {"nom": "direccio vent", "valor": 260}]},
         ]},
    ]).encode("utf-8")


def test_zone_rows_store_every_zone_with_franja_windows():
    rows = mc._parse_zones(json.loads(zones_payload()), RUN, "2026-07-13")
    # ALL zones are kept (resort assignment is config, not parsing) —
    # including ids the current mapping doesn't use (zona_4 here).
    assert {r[1] for r in rows} == {"zona_1", "zona_4", "zona_5", "zona_6"}

    z1 = {r[4]: r[5] for r in rows if r[1] == "zona_1"}
    assert z1 == {"zonal.acumulacio.24h": 5.0,
                  "zonal.acumulacioNeu.24h": 12.0}
    assert all(r[3] == "2026-07-13T00:00Z" for r in rows if r[1] == "zona_1")

    z5 = {r[4]: r[5] for r in rows if r[1] == "zona_5"}
    # comentari (text) and acumulacio-without-valor yield no rows
    assert z5 == {"zonal.cel.6h": 3.0, "zonal.cota.6h": 1800.0,
                  "zonal.probabilitat.6h": 1.0}
    assert all(r[3] == "2026-07-13T06:00Z" for r in rows if r[1] == "zona_5")


def test_zone_name_drift_is_detected():
    body = json.loads(zones_payload())
    assert mc.check_zone_names(body) == []  # fixture uses the real names
    body["franjes"][0]["zones"][0]["nom"] = "Zona renombrada"
    body["franjes"][1]["zones"][1]["idZona"] = 99
    problems = mc.check_zone_names(body)
    assert any("renamed" in p for p in problems)
    assert any("unknown zone id 99" in p for p in problems)


def test_configured_zones_exist_in_the_observed_scheme():
    from config import METEOCAT_ZONE_FOR_STATION, RESORTS
    assert set(METEOCAT_ZONE_FOR_STATION) == {r["station"] for r in RESORTS}
    for zone_id in METEOCAT_ZONE_FOR_STATION.values():
        assert zone_id in mc.EXPECTED_ZONE_NAMES


def test_franja_window_falls_back_to_idTipusFranja():
    assert mc._franja_window({"nom": "12:00h - 18:00h"}) == (12, 6)
    assert mc._franja_window({"nom": "24h"}) == (0, 24)
    assert mc._franja_window({"nom": "???", "idTipusFranja": 4}) == (18, 6)
    assert mc._franja_window({"nom": "???", "idTipusFranja": 42}) is None


def test_pic_rows_carry_variable_level_and_time():
    rows = mc._parse_pic(json.loads(pic_payload()), RUN, "baqueira",
                         "2026-07-13")
    by_var = {r[4]: r[5] for r in rows}
    assert by_var == {"pic.isozero.totes": 1900.0,
                      "pic.iso-10.totes": 3200.0,
                      "pic.temperatura.2500": -2.5,
                      "pic.velocitat_vent.2500": 18.0,
                      "pic.direccio_vent.2500": 260.0}
    assert all(r[3] == "2026-07-13T06:00Z" for r in rows)


def test_dispatch_handles_archive_filenames_and_metadata():
    stamped = "20260712T133000Z_zones_2026-07-13.json.gz"
    assert len(mc.parse_meteocat(zones_payload(), RUN, stamped)) > 0
    stamped_pic = "20260712T133000Z_pic_baqueira_2026-07-13.json.gz"
    rows = mc.parse_meteocat(pic_payload(), RUN, stamped_pic)
    assert rows and all(r[1] == "baqueira" for r in rows)
    assert mc.parse_meteocat(b"[]", RUN, "pics_metadades.json") == []
    assert mc.parse_meteocat(b"[]", RUN,
                             "20260712T133000Z_refugis_metadades.json.gz") == []


def test_unexpected_shapes_yield_no_rows_without_crashing():
    assert mc._parse_zones({"unexpected": True}, RUN, "2026-07-13") == []
    assert mc._parse_pic({"not": "a list"}, RUN, "baqueira", "2026-07-13") == []


def test_rebuild_parity_from_archive(tmp_path):
    import datetime
    fetched = datetime.datetime(2026, 7, 12, 13, 30, 0,
                                tzinfo=datetime.timezone.utc)
    archive_payload(mc.SOURCE, "zones_2026-07-13.json", zones_payload(),
                    fetched, tmp_path)
    archive_payload(mc.SOURCE, "pic_baqueira_2026-07-13.json", pic_payload(),
                    fetched, tmp_path)

    conn = db.connect(tmp_path / "rebuild.sqlite")
    total = 0
    for path, raw in iter_archived(mc.SOURCE, raw_dir=tmp_path):
        total += db.upsert_rows(
            conn, mc.parse_meteocat(raw, run_time_from_path(path), path.name))
    stored = conn.execute("SELECT COUNT(*) FROM forecast_values").fetchone()[0]
    assert stored == total > 0
