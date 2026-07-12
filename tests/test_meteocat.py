import json

import db
import meteocat_ingest as mc
from archive import archive_payload, iter_archived, run_time_from_path

RUN = "2026-07-12T13:30:00Z"


def zones_payload() -> bytes:
    return json.dumps({
        "dataPrediccio": "2026-07-13T00:00Z",
        "dataPublicacio": "2026-07-12T12:05Z",
        "franjes": [
            {"data": "2026-07-13T00:00Z",
             "zones": [
                 {"idZona": 1, "neu": {"cota": 1800, "quantitat": 2}},
                 {"idZona": 3, "neu": {"cota": 2000, "quantitat": 1}},
                 {"idZona": 99, "neu": {"cota": 0, "quantitat": 0}},
             ]},
            {"data": "2026-07-13T12:00Z",
             "zones": [
                 {"idZona": 6, "probabilitat": 60},
             ]},
        ],
    }).encode("utf-8")


def pic_payload() -> bytes:
    return json.dumps([
        {"data": "2026-07-13T06:00Z",
         "cotes": [
             {"cota": 2500,
              "variables": [
                  {"nom": "isozero", "valor": 1900},
                  {"nom": "temperatura", "valor": -2.5, "unitat": None},
              ]},
         ]},
    ]).encode("utf-8")


def test_zone_rows_map_zones_to_stations_and_skip_unknown_zones():
    rows = mc._parse_zones(json.loads(zones_payload()), RUN, "2026-07-13")
    stations = {r[1] for r in rows}
    assert stations == {"baqueira", "boi_taull", "la_molina"}
    baqueira = {r[4]: r[5] for r in rows if r[1] == "baqueira"}
    assert baqueira == {"zonal.neu.cota": 1800.0, "zonal.neu.quantitat": 2.0}
    assert all(r[3] == "2026-07-13T00:00Z" for r in rows if r[1] == "baqueira")


def test_pic_rows_carry_variable_level_and_time():
    rows = mc._parse_pic(json.loads(pic_payload()), RUN, "baqueira",
                         "2026-07-13")
    by_var = {r[4]: r[5] for r in rows}
    assert by_var == {"pic.isozero.2500.valor": 1900.0,
                      "pic.temperatura.2500.valor": -2.5}
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
