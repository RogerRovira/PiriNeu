"""Ingest the AEMET Harmonie-AROME leg from the download server.

Shaped by the 2026-07-12 reconnaissance (PLAN.md open question 2):
- The entry point serves ONE tar.gz of the LATEST complete run only
  (48 hourly steps, run+1h..run+48h; ~2-3 h publication lag; a missed
  00/06/12/18 cycle is unrecoverable) — hence one fetch per cycle.
- The bundled GeoTIFFs are EPSG:4326 but they are RGBA COLORMAPPED IMAGES,
  not data grids: per-resort values are decoded through each file's
  `ESCALA` GDAL tag (RGBA -> value bin). Stored values are therefore BINS:
  bin midpoint for closed bins, the lower edge for the open top bin and
  for the transparent (alpha 0) zero bin.
- Wind direction ships separately as GeoJSON points (`ang_viento`); the
  nearest point to each resort is stored. Pressure isobars are skipped.
- The model run time is derived from the bundle content (first valid time
  minus 1 h), unlike the other legs where run_time is the fetch time —
  the true run is known here and matters for verification.

The raw tar (gunzipped once, so the archive holds a plain .tar that
`archive_payload` gzips back) is archived BEFORE parsing. Field codes 207
and 228 have mislabeled CAMPO tags upstream ("press"); they are stored
under neutral names until a winter run confirms their semantics.
"""
import ast
import gzip
import io
import json
import math
import re
import tarfile
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

import requests

import db
from alerting import send_alert
from archive import archive_payload
from config import ISO_UTC, RESORTS

SOURCE = "aemet"
BUNDLE_URL = "https://www.aemet.es/es/api-eltiempo/modelos/download/harmonie/PB"
BUNDLE_NAME = "harmonie_pb.tar"  # archived gunzipped; .gz re-added by archive

# GRIB1-style field codes observed in the bundle. 207/228 CAMPO tags are
# mislabeled upstream — keep neutral names until winter confirms semantics
# (207 range 0.001-0.2 suggests snow in m; 228 range 0-140 suggests gust).
CODE_NAMES = {"11": "temperature", "32": "wind_speed", "61": "precip",
              "71": "cloud_cover", "207": "f207", "228": "f228"}

_TIF_RE = re.compile(r"down_(?P<time>[^_]+)_(?P<code>\d+)(?:_(?P<agg>\d)HH)?\.tif$")
_WIND_RE = re.compile(r"down_(?P<time>[^_]+)_direcc_viento_33\.geojson$")


def _iso_utc(t: str) -> str:
    """'2026-07-12T13:00:00+00:00' -> '2026-07-12T13:00:00Z'."""
    return datetime.fromisoformat(t).astimezone(timezone.utc).strftime(ISO_UTC)


# --- RGBA -> value decoding via the embedded ESCALA legend ------------------

def _rgba4(values) -> Optional[Tuple[int, int, int, int]]:
    """Normalize a color to 4 components (some scales/rasters omit alpha)."""
    c = [int(v) for v in values]
    if len(c) == 3:
        c.append(255)
    return tuple(c[:4]) if len(c) >= 4 else None


def _parse_escala(tag: str) -> List[dict]:
    """The ESCALA GDAL tag is a Python-literal dict (single quotes)."""
    entries = []
    for e in ast.literal_eval(tag).get("Lista RGBA", []):
        lo, hi = e["Valores"]
        rgba = _rgba4(e["RGBA"])
        if rgba is not None:
            entries.append({"lo": float(lo),
                            "hi": float(hi) if hi != "" else None,
                            "rgba": rgba})
    return entries


def _bin_value(rgba: Tuple[int, ...], escala: List[dict]) -> Optional[float]:
    """Decode one pixel: midpoint of its bin; lower edge for the open top
    bin and for the transparent zero bin (don't fabricate half-bin amounts
    where the source drew nothing)."""
    pixel = _rgba4(rgba)
    if pixel is None or not escala:
        return None
    r, g, b, a = pixel
    match = next((e for e in escala if e["rgba"] == (r, g, b, a)), None)
    if match is None and a == 0:
        # Transparent = the scale's alpha-0 bin; scales without one (cloud
        # cover, f207) simply don't draw below their lowest threshold, so
        # transparent decodes to 0 rather than dropping the sample.
        match = next((e for e in escala if e["rgba"][3] == 0), None)
        if match is None:
            return 0.0
    if match is None and a > 0:   # tolerate slight rendering drift
        match = min((e for e in escala if e["rgba"][3] > 0),
                    key=lambda e: (e["rgba"][0] - r) ** 2
                    + (e["rgba"][1] - g) ** 2 + (e["rgba"][2] - b) ** 2,
                    default=None)
    if match is None:
        return None
    if match["hi"] is None or match["rgba"][3] == 0:
        return match["lo"]
    return (match["lo"] + match["hi"]) / 2


def _sample_tif(body: bytes) -> Dict[str, Optional[float]]:
    """station -> decoded value for one colormapped GeoTIFF."""
    from rasterio.io import MemoryFile   # heavy import kept local
    with MemoryFile(body) as mem, mem.open() as src:
        escala = _parse_escala(src.tags().get("ESCALA", "{}"))
        coords = [(r["lon"], r["lat"]) for r in RESORTS]
        return {r["station"]: _bin_value(tuple(s), escala)
                for r, s in zip(RESORTS, src.sample(coords))}


def _nearest_wind(body: bytes) -> Dict[str, Optional[float]]:
    """station -> ang_viento of the nearest GeoJSON point (planar approx
    with cos(lat) scaling — fine at the ~0.5 deg point spacing)."""
    feats = json.loads(body).get("features", [])
    out: Dict[str, Optional[float]] = {}
    for r in RESORTS:
        best, best_d = None, math.inf
        coslat = math.cos(math.radians(r["lat"]))
        for f in feats:
            try:
                lon, lat = f["geometry"]["coordinates"]
                ang = float(f["properties"]["ang_viento"])
            except (KeyError, TypeError, ValueError):
                continue
            d = ((lon - r["lon"]) * coslat) ** 2 + (lat - r["lat"]) ** 2
            if d < best_d:
                best, best_d = ang, d
        out[r["station"]] = best
    return out


# --- parser (pure: archived tar -> rows) -------------------------------------

def parse_aemet(payload: bytes, run_time_utc: str = "",
                name: str = "") -> List[db.Row]:
    """Parse one archived bundle. The passed run_time (fetch time) is only a
    fallback: the true model run is derived as first valid time - 1 h."""
    members: List[Tuple[str, str, Optional[str], bytes]] = []  # kind, time...
    with tarfile.open(fileobj=io.BytesIO(payload), mode="r:*") as tf:
        for m in tf.getmembers():
            tif = _TIF_RE.search(m.name)
            wind = _WIND_RE.search(m.name)
            if tif:
                members.append(("tif", tif["time"], tif, tf.extractfile(m).read()))
            elif wind:
                members.append(("wind", wind["time"], None, tf.extractfile(m).read()))
    if not members:
        return []
    first_valid = min(datetime.fromisoformat(t) for _, t, _, _ in members)
    run = (first_valid - timedelta(hours=1)).astimezone(timezone.utc)
    run_time = run.strftime(ISO_UTC) or run_time_utc

    rows: List[db.Row] = []
    for kind, time_str, tif, body in members:
        valid = _iso_utc(time_str)
        if kind == "wind":
            samples = _nearest_wind(body)
            variable = "grid.wind_direction"
        else:
            code, agg = tif["code"], tif["agg"]
            base = CODE_NAMES.get(code, f"f{code}")
            variable = f"grid.{base}" + (f".{agg}h" if agg else "")
            samples = _sample_tif(body)
        for station, value in samples.items():
            if value is not None:
                rows.append((SOURCE, station, run_time, valid,
                             variable, float(value)))
    return rows


# --- ingestion run -----------------------------------------------------------

def _derived_run_time(tar_bytes: bytes) -> Optional[str]:
    """Cheap run-time peek from member names, without opening any raster."""
    times = []
    with tarfile.open(fileobj=io.BytesIO(tar_bytes), mode="r:*") as tf:
        for n in tf.getnames():
            m = _TIF_RE.search(n) or _WIND_RE.search(n)
            if m:
                times.append(datetime.fromisoformat(m["time"]))
    if not times:
        return None
    return (min(times) - timedelta(hours=1)).astimezone(
        timezone.utc).strftime(ISO_UTC)


def main() -> None:
    fetched_at = datetime.now(timezone.utc)
    resp = requests.get(BUNDLE_URL, timeout=300)
    if resp.status_code != 200:
        raise RuntimeError(f"AEMET returned HTTP {resp.status_code}")
    tar_bytes = gzip.decompress(resp.content)

    run_time = _derived_run_time(tar_bytes)
    if run_time is None:
        raise RuntimeError("AEMET bundle contains no recognizable members")

    conn = db.connect()
    already = conn.execute(
        "SELECT COUNT(*) FROM forecast_values WHERE source=? AND run_time_utc=?",
        (SOURCE, run_time)).fetchone()[0]
    if already:
        # Same run as last cycle (publication lag not elapsed yet): the
        # payload is byte-identical to what's already archived — skip the
        # ~30 MB duplicate rather than re-archive it.
        print(f"{SOURCE}: run {run_time} already ingested, skipping")
        return

    path = archive_payload(SOURCE, BUNDLE_NAME, tar_bytes, fetched_at)
    rows = parse_aemet(tar_bytes, fetched_at.strftime(ISO_UTC), BUNDLE_NAME)
    count = db.upsert_rows(conn, rows)
    print(f"{SOURCE}: archived {path}, run {run_time}, upserted {count} rows")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        send_alert(f"aemet_ingest failed: {exc}")
        raise
