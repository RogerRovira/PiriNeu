"""AEMET download-server reconnaissance (PLAN.md Milestone 2, open question 2).

Empirically answers, for the Harmonie-AROME GeoTIFF/GeoJSON download server:
- publication lag after the 00/06/12/18 UTC runs (Last-Modified vs run)
- file retention (do date-parameterized downloads stay available?)
- raster CRS — the docs claim EPSG:4326, but don't assume WGS84 (gotcha)
- nodata value, resolution, and pixel values at the resort coordinates

Known entry point (AEMET numerical-models viewer, Península y Baleares):
    https://www.aemet.es/es/api-eltiempo/modelos/download/harmonie/PB
The per-field/date query parameters are not documented. To unlock the full
matrix, open the viewer (aemet.es > El Tiempo > Modelos numéricos >
HARMONIE-AROME), trigger a download with the browser's network tab open,
and pass the captured URL:

    AEMET_DOWNLOAD_URL='https://...' python aemet_recon.py

Raw responses are cached in data/cache/aemet_recon/ (never re-spent);
report lands in data/aemet_recon_report.json. Requires `rasterio` for the
raster inspection step (the rest degrades gracefully without it).
"""
import hashlib
import json
import os
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import requests

from config import DATA_DIR, ISO_UTC, MAX_NEW_CALLS, RESORTS

BASE = "https://www.aemet.es/es/api-eltiempo/modelos/download/harmonie"
ENTRY_POINTS = {
    "peninsula_balears": f"{BASE}/PB",
    "canarias_control": f"{BASE}/CAN",  # control: confirms URL scheme works
}
RUN_HOURS_UTC = (0, 6, 12, 18)
CACHE_DIR = DATA_DIR / "cache" / "aemet_recon"
REPORT_PATH = DATA_DIR / "aemet_recon_report.json"
SLEEP_BETWEEN_CALLS = 1.5


def _sniff(body: bytes) -> str:
    if body[:2] == b"PK":
        return "zip"
    if body[:4] in (b"II*\x00", b"MM\x00*"):
        return "geotiff"
    head = body[:64].lstrip()
    if head[:1] in (b"{", b"["):
        return "json"
    if head[:1] == b"<":
        return "html/xml"
    return "unknown"


def fetch(url: str, calls: list) -> dict:
    """GET with byte-level disk cache; returns metadata + cached body path."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha256(url.encode()).hexdigest()[:24]
    body_path = CACHE_DIR / f"{key}.bin"
    meta_path = CACHE_DIR / f"{key}.meta.json"
    if meta_path.exists():
        return json.loads(meta_path.read_text())

    if len(calls) >= MAX_NEW_CALLS:
        raise RuntimeError(f"call budget exhausted ({MAX_NEW_CALLS})")
    calls.append(url)
    meta = {"url": url,
            "fetched_at": datetime.now(timezone.utc).strftime(ISO_UTC)}
    try:
        resp = requests.get(url, timeout=120)
        meta["status"] = resp.status_code
        meta["content_type"] = resp.headers.get("Content-Type")
        meta["last_modified"] = resp.headers.get("Last-Modified")
        meta["content_length"] = len(resp.content)
        meta["kind"] = _sniff(resp.content)
        body_path.write_bytes(resp.content)
        meta["body_path"] = str(body_path)
    except requests.RequestException as exc:
        meta["error"] = str(exc)
        return meta  # transient: not cached, retried next run
    meta_path.write_text(json.dumps(meta))
    time.sleep(SLEEP_BETWEEN_CALLS)
    return meta


def inspect_raster(body: bytes) -> dict:
    """CRS / nodata / resolution / per-resort pixel values via rasterio."""
    try:
        import rasterio
        from rasterio.io import MemoryFile
    except ImportError:
        return {"note": "install rasterio to inspect rasters"}
    out = {}
    with MemoryFile(body) as mem, mem.open() as src:
        out["crs"] = str(src.crs)
        out["nodata"] = src.nodata
        out["bounds"] = list(src.bounds)
        out["shape"] = [src.height, src.width]
        out["resolution"] = list(src.res)
        if src.crs and src.crs.is_geographic:
            coords = [(r["lon"], r["lat"]) for r in RESORTS]
            samples = list(src.sample(coords))
            out["resort_pixels"] = {
                r["station"]: [float(v) for v in s]
                for r, s in zip(RESORTS, samples)}
        else:
            out["note"] = "projected CRS — reproject resort coords (pyproj)"
    return out


def analyze(meta: dict) -> dict:
    """Attach lag estimate and, for zip/tif bodies, raster facts."""
    if meta.get("kind") == "geotiff" and meta.get("body_path"):
        meta["raster"] = inspect_raster(Path(meta["body_path"]).read_bytes())
    elif meta.get("kind") == "zip" and meta.get("body_path"):
        with zipfile.ZipFile(meta["body_path"]) as zf:
            names = zf.namelist()
            meta["zip_members"] = names[:20]
            tifs = [n for n in names if n.lower().endswith((".tif", ".tiff"))]
            if tifs:
                meta["raster"] = inspect_raster(zf.read(tifs[0]))
    if meta.get("last_modified"):
        published = datetime.strptime(
            meta["last_modified"], "%a, %d %b %Y %H:%M:%S %Z"
        ).replace(tzinfo=timezone.utc)
        run = published.replace(minute=0, second=0, microsecond=0)
        while run.hour not in RUN_HOURS_UTC:
            run = run.replace(hour=run.hour - 1)
        meta["estimated_run_utc"] = run.strftime(ISO_UTC)
        meta["estimated_lag_minutes"] = round(
            (published - run).total_seconds() / 60)
    return meta


def main() -> None:
    calls: list = []
    report = {"run_at": datetime.now(timezone.utc).strftime(ISO_UTC),
              "entry_points": {}, "custom_url": None, "calls_spent": 0}

    for label, url in ENTRY_POINTS.items():
        print(f"probing {label}: {url}")
        meta = analyze(fetch(url, calls))
        report["entry_points"][label] = meta
        print(f"  -> HTTP {meta.get('status')} {meta.get('kind')} "
              f"({meta.get('content_length', 0)} bytes, "
              f"lag ~{meta.get('estimated_lag_minutes', '?')} min)")

    custom = os.environ.get("AEMET_DOWNLOAD_URL")
    if custom:
        print(f"probing captured viewer URL")
        report["custom_url"] = analyze(fetch(custom, calls))
    else:
        print("AEMET_DOWNLOAD_URL not set — skip per-field/date probing "
              "(capture a download URL from the viewer's network tab)")

    report["calls_spent"] = len(calls)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2))
    print(f"report: {REPORT_PATH}")
    print("record the outcome in PLAN.md (open question 2): lag, retention, "
          "CRS, nodata")


if __name__ == "__main__":
    main()
