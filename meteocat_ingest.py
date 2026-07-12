"""Ingest the Meteocat leg: Pirineu zonal + peak (pics) forecasts.

Auth: `METEOCAT_API_KEY` env var, sent as X-Api-Key — never in code, docs,
cache entries or the archive (payload bodies carry no credentials).

Quota discipline (the Predicció plan is tightly capped — see CLAUDE.md):
- pics/metadades: 1 call, cached for a week (slugs and canonical coords
  change essentially never)
- zonal forecast: 1 call per target date — the endpoint returns ALL zones
  per call, no zone parameter exists (gotcha)
- peak forecast: 1 call per anchor peak, today only by default; set
  METEOCAT_PICS_TOMORROW=1 to add tomorrow (3 extra calls/day)
Default daily budget: 5 calls (+1 metadades weekly).

Every payload is archived BEFORE parsing. Parsing is deliberately tolerant
and generic (numeric leaves, deterministic names): the exact response
schemas are only partially known until real payloads accumulate, and the
archive — not the parser — is the source of truth. Refine the parser
later and rebuild with rebuild_db.py.

The slugs come from pics/metadades, whose lat/lon are the CANONICAL
coordinates for ALL sources (gotcha): every run prints them next to the
config.py placeholders so the swap isn't forgotten.
"""
import json
import os
from datetime import date, datetime, timedelta, timezone
from typing import List, Optional

import db
from alerting import send_alert
from archive import archive_payload
from config import ISO_UTC
from httpcache import cached_get

SOURCE = "meteocat"
BASE = "https://api.meteo.cat"

# Handoff anchor codes (codi -> station); slugs are resolved at runtime.
ANCHOR_PEAKS = {
    "77954ad7": "baqueira",    # Cap de Vaqueira
    "246d5775": "boi_taull",   # Pica de Cervi
    "4d04de5e": "la_molina",   # La Tosa d'Alp
}
# Zone id inside the all-zones response -> station
ZONE_STATIONS = {1: "baqueira", 3: "boi_taull", 6: "la_molina"}

WEEK_SECONDS = 7 * 24 * 3600


def _headers() -> dict:
    key = os.environ.get("METEOCAT_API_KEY")
    if not key:
        raise RuntimeError("METEOCAT_API_KEY not set")
    return {"X-Api-Key": key}


def _get(path: str, ttl_seconds: Optional[int] = None) -> bytes:
    status, body, _ = cached_get(BASE + path, ttl_seconds=ttl_seconds,
                                 headers=_headers())
    if status != 200:
        raise RuntimeError(f"Meteocat returned HTTP {status} for {path}")
    return body


# --- generic, deterministic flattening -------------------------------------

_SKIP_KEYS = {"idZona"}  # identity fields, not measurements


def _numeric_leaves(obj, prefix: str = "") -> List[tuple]:
    """Yield (dotted_name, float) for every numeric leaf, depth-first.

    Deterministic for a given payload, so rebuilds reproduce identical rows
    even though the full Meteocat schema isn't pinned down yet.
    """
    out = []
    if isinstance(obj, dict):
        for key in sorted(obj):
            if key in _SKIP_KEYS:
                continue
            name = f"{prefix}.{key}" if prefix else key
            out.extend(_numeric_leaves(obj[key], name))
    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            out.extend(_numeric_leaves(item, f"{prefix}[{i}]"))
    elif isinstance(obj, (int, float)) and not isinstance(obj, bool):
        out.append((prefix, float(obj)))
    return out


# --- parsers (pure: archived payload -> rows) -------------------------------

def parse_meteocat(payload: bytes, run_time_utc: str, name: str) -> List[db.Row]:
    """Dispatch on the archive item's logical name.

    Accepts either the logical name or a full archive filename
    ("<STAMP>_<logical>.gz"). Names written by this ingester:
      zones_<YYYY-MM-DD>.json | pic_<station>_<YYYY-MM-DD>.json |
      pics/refugis_metadades.json (archived for provenance, no rows)
    """
    if name.endswith(".gz"):
        name = name[:-len(".gz")]
    stamp, _, rest = name.partition("_")
    logical = rest if (stamp.endswith("Z") and rest) else name
    if logical.startswith("zones_"):
        return _parse_zones(json.loads(payload), run_time_utc,
                            logical[len("zones_"):-len(".json")])
    if logical.startswith("pic_"):
        station, _, target = logical[len("pic_"):-len(".json")].rpartition("_")
        return _parse_pic(json.loads(payload), run_time_utc, station, target)
    return []


def _parse_zones(body: dict, run_time_utc: str, target_date: str) -> List[db.Row]:
    rows: List[db.Row] = []
    if not isinstance(body, dict):
        return rows
    for i, franja in enumerate(body.get("franjes") or []):
        valid = franja.get("data") or f"{target_date}[franja{i}]"
        for zone in franja.get("zones") or []:
            station = ZONE_STATIONS.get(zone.get("idZona"))
            if station is None:
                continue
            for variable, value in _numeric_leaves(zone):
                rows.append((SOURCE, station, run_time_utc, str(valid),
                             f"zonal.{variable}", value))
    return rows


def _parse_pic(body, run_time_utc: str, station: str,
               target_date: str) -> List[db.Row]:
    rows: List[db.Row] = []
    if not isinstance(body, list):
        return rows
    for i, point in enumerate(body):
        valid = point.get("data") or f"{target_date}[t{i}]"
        for cota in point.get("cotes") or []:
            level = cota.get("cota") or cota.get("altitud") or "peak"
            for var in cota.get("variables") or []:
                nom = var.get("nom") or "var"
                for leaf, value in _numeric_leaves(
                        {k: v for k, v in var.items() if k != "nom"}):
                    rows.append((SOURCE, station, run_time_utc, str(valid),
                                 f"pic.{nom}.{level}.{leaf}", value))
    return rows


# --- ingestion run -----------------------------------------------------------

def resolve_slugs() -> dict:
    """codi -> {slug, kind, name, lat, lon} from the metadades endpoints."""
    mapping = {}
    for kind in ("pics", "refugis"):
        body = _get(f"/pronostic/v1/pirineu/{kind}/metadades",
                    ttl_seconds=WEEK_SECONDS)
        archive_payload(SOURCE, f"{kind}_metadades.json", body)
        for item in json.loads(body):
            codi = item.get("codi")
            if codi in ANCHOR_PEAKS:
                coord = item.get("coordenades") or {}
                mapping[codi] = {
                    "slug": item.get("slug"), "kind": kind,
                    "name": item.get("descripcio"),
                    "lat": coord.get("latitud"), "lon": coord.get("longitud"),
                }
    return mapping


def main() -> None:
    fetched_at = datetime.now(timezone.utc)
    run_time = fetched_at.strftime(ISO_UTC)
    today = fetched_at.date()
    rows: List[db.Row] = []

    slugs = resolve_slugs()
    print("canonical pics-metadades coords (swap config.py placeholders!):")
    for codi, info in slugs.items():
        print(f"  {ANCHOR_PEAKS[codi]}: {info['name']} "
              f"lat={info['lat']} lon={info['lon']} slug={info['slug']}")

    zone_dates = [today, today + timedelta(days=1)]
    for d in zone_dates:
        name = f"zones_{d.isoformat()}.json"
        body = _get(f"/pronostic/v1/pirineu/{d.year}/{d.month:02d}/{d.day:02d}")
        archive_payload(SOURCE, name, body, fetched_at)
        rows.extend(_parse_zones(json.loads(body), run_time, d.isoformat()))

    pic_dates = [today]
    if os.environ.get("METEOCAT_PICS_TOMORROW") == "1":
        pic_dates.append(today + timedelta(days=1))
    for codi, info in slugs.items():
        for d in pic_dates:
            station = ANCHOR_PEAKS[codi]
            name = f"pic_{station}_{d.isoformat()}.json"
            body = _get(f"/pronostic/v1/pirineu/{info['kind']}/{info['slug']}"
                        f"/{d.year}/{d.month:02d}/{d.day:02d}")
            archive_payload(SOURCE, name, body, fetched_at)
            rows.extend(_parse_pic(json.loads(body), run_time, station,
                                   d.isoformat()))

    count = db.upsert_rows(db.connect(), rows)
    print(f"{SOURCE}: archived {2 + len(zone_dates) + len(slugs) * len(pic_dates)}"
          f" payloads, upserted {count} rows")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        send_alert(f"meteocat_ingest failed: {exc}")
        raise
