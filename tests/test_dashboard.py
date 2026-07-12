"""Dashboard generator: pages exist, attributions everywhere, honest cells."""
import db
import dashboard as dash

RUN = "2026-12-20T15:00:00Z"
D0, D1 = "2026-12-20", "2026-12-21"


def _seed(conn):
    rows = []
    for day, snow, conf in ((D0, 14.0, 2.0), (D1, 0.2, 1.0)):
        for var, val in (("snow_swe_mm", snow), ("cota_m", 1750.0),
                         ("confidence", conf), ("regime", 0.0),
                         ("n_legs_snow", 3.0),
                         ("leg.openmeteo.snow_swe_mm", snow),
                         ("leg.aemet.snow_swe_mm", snow + 1),
                         ("leg.openmeteo.cota_m", 1700.0),
                         ("leg.meteocat.cota_m", 1800.0)):
            rows.append(("consensus", "baqueira", RUN, day, var, val))
    db.upsert_rows(conn, rows)


def test_generates_pages_with_attributions_and_values(tmp_path):
    conn = db.connect(tmp_path / "dash.sqlite")
    _seed(conn)
    out = dash.generate(tmp_path / "site", conn)
    index = (out / "index.html").read_text(encoding="utf-8")
    resort = (out / "baqueira.html").read_text(encoding="utf-8")

    for page in (index, resort):
        # mandatory attributions on every page (CLAUDE.md convention)
        assert "Open-Meteo" in page and "CC-BY" in page
        assert "AEMET" in page and "Meteocat" in page
    assert "Baqueira Beret" in index
    # 14 mm SWE -> ~10 cm, Alta badge, cota shown
    assert "10&thinsp;cm" in resort and "Alta" in resort
    assert "~1750" in resort
    # the 0.2 mm day renders as no snow, hiding a meaningless cota
    assert "sense neu prevista" in resort
    # per-leg table shows the missing meteocat snow leg as a dash
    assert "<td>—</td>" in resort
    # local-time stamp rendered (UTC 15:00 -> 16:00 CET in December)
    assert "16:00" in index


def test_empty_db_yields_placeholder_index(tmp_path):
    conn = db.connect(tmp_path / "empty.sqlite")
    out = dash.generate(tmp_path / "site", conn)
    index = (out / "index.html").read_text(encoding="utf-8")
    assert "Encara no hi ha consens" in index
    assert "Meteocat" in index  # attributions even on the placeholder
