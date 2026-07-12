"""AEMET parser tests against a synthetic bundle mirroring the real one
(2026-07-12 recon): RGBA colormapped GeoTIFFs with an ESCALA legend tag,
wind-direction GeoJSON points, member names down_<ISO>_<code>[_<n>HH].
"""
import io
import json
import tarfile

import pytest

rasterio = pytest.importorskip("rasterio")

import aemet_ingest as ai
from config import RESORTS

# Legend mirroring the real ESCALA structure (Python-literal string).
PRECIP_ESCALA = str({
    "Producto": "61",
    "Lista RGBA": [
        {"Valores": [300, ""], "RGBA": ["236", "200", "200", "255"]},
        {"Valores": [1, 2], "RGBA": ["51", "245", "222", "255"]},
        {"Valores": [0.0, 0.5], "RGBA": ["19", "49", "52", "0"]},
    ],
})
TEMP_ESCALA = str({
    "Producto": "11",
    "Lista RGBA": [
        {"Valores": [10, 12], "RGBA": ["255", "224", "0", "255"]},
        {"Valores": [8, 10], "RGBA": ["200", "224", "0", "255"]},
    ],
})


def _tif(rgba, escala) -> bytes:
    """One-color 8x5 RGBA GeoTIFF covering the whole PB domain."""
    import numpy as np
    from rasterio.io import MemoryFile
    from rasterio.transform import from_bounds
    transform = from_bounds(-11.0125, 34.4875, 4.9875, 44.4875, 8, 5)
    data = np.zeros((4, 5, 8), dtype="uint8")
    for band, v in enumerate(rgba):
        data[band, :, :] = v
    with MemoryFile() as mem:
        with mem.open(driver="GTiff", height=5, width=8, count=4,
                      dtype="uint8", crs="EPSG:4326",
                      transform=transform) as dst:
            dst.write(data)
            dst.update_tags(ESCALA=escala, CAMPO="test", FUENTE="AEMET")
        return mem.read()


def _wind_geojson() -> bytes:
    # Nearest point to all three resorts is (1.0, 42.5) with 315 deg.
    return json.dumps({"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {"ID": 0, "ang_viento": 315},
         "geometry": {"type": "Point", "coordinates": [1.0, 42.5]}},
        {"type": "Feature", "properties": {"ID": 1, "ang_viento": 90},
         "geometry": {"type": "Point", "coordinates": [-8.0, 38.0]}},
    ]}).encode()


def bundle() -> bytes:
    t13, t14 = "2026-07-12T13:00:00+00:00", "2026-07-12T14:00:00+00:00"
    members = {
        f"down_{t13}_11.tif": _tif((255, 224, 0, 255), TEMP_ESCALA),
        f"down_{t13}_61_1HH.tif": _tif((51, 245, 222, 255), PRECIP_ESCALA),
        f"down_{t14}_61_1HH.tif": _tif((19, 49, 52, 0), PRECIP_ESCALA),
        f"down_{t13}_direcc_viento_33.geojson": _wind_geojson(),
        f"down_{t13}_press_1.geojson": b'{"type":"FeatureCollection","features":[]}',
    }
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tf:
        for name, body in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(body)
            tf.addfile(info, io.BytesIO(body))
    return buf.getvalue()


def test_parse_decodes_bins_run_time_and_wind():
    rows = ai.parse_aemet(bundle())
    stations = {r[1] for r in rows}
    assert stations == {r["station"] for r in RESORTS}
    # true model run = first valid (13:00) - 1h
    assert {r[2] for r in rows} == {"2026-07-12T12:00:00Z"}

    by = {(r[1], r[4], r[3]): r[5] for r in rows}
    b = "baqueira"
    # closed bin -> midpoint
    assert by[(b, "grid.temperature", "2026-07-12T13:00:00Z")] == 11.0
    assert by[(b, "grid.precip.1h", "2026-07-12T13:00:00Z")] == 1.5
    # transparent zero bin -> lower edge, not a fabricated midpoint
    assert by[(b, "grid.precip.1h", "2026-07-12T14:00:00Z")] == 0.0
    # wind direction from the nearest GeoJSON point
    assert by[(b, "grid.wind_direction", "2026-07-12T13:00:00Z")] == 315.0
    # pressure isobars are skipped
    assert not any("press" in r[4] for r in rows)


def test_open_top_bin_and_color_drift():
    escala = ai._parse_escala(PRECIP_ESCALA)
    assert ai._bin_value((236, 200, 200, 255), escala) == 300  # open top: lo
    # slightly off-palette color (rendering drift) snaps to nearest
    assert ai._bin_value((52, 244, 221, 255), escala) == 1.5
    # unknown transparent pixel maps to the alpha-0 bin's lower edge
    assert ai._bin_value((0, 0, 0, 0), escala) == 0.0
    # scales WITHOUT an alpha-0 entry (cloud cover, f207): transparent
    # means below the lowest drawn threshold -> 0, not a dropped sample
    assert ai._bin_value((0, 0, 0, 0), ai._parse_escala(TEMP_ESCALA)) == 0.0
    # 3-component RGB legends/pixels are normalized, not crashes
    assert ai._rgba4((1, 2, 3)) == (1, 2, 3, 255)


def test_crop_bundle_decodes_identically_and_shrinks_geojson():
    full = bundle()
    cropped = ai.crop_bundle(full)
    assert sorted(ai.parse_aemet(cropped)) == sorted(ai.parse_aemet(full))
    with tarfile.open(fileobj=io.BytesIO(cropped)) as tf:
        names = set(tf.getnames())
        # same members survive the crop
        with tarfile.open(fileobj=io.BytesIO(full)) as orig:
            assert names == set(orig.getnames())
        wind = json.load(tf.extractfile(
            "down_2026-07-12T13:00:00+00:00_direcc_viento_33.geojson"))
    # the far-away point (-8, 38) is outside CROP_BOUNDS and dropped
    assert [f["properties"]["ang_viento"] for f in wind["features"]] == [315]


def test_empty_or_alien_tar_yields_no_rows():
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tf:
        info = tarfile.TarInfo("README.txt")
        info.size = 2
        tf.addfile(info, io.BytesIO(b"hi"))
    assert ai.parse_aemet(buf.getvalue()) == []
