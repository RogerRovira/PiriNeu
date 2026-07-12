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

Every payload is archived BEFORE parsing; the archive — not the parser —
is the source of truth. Parsers follow the REAL payload shapes observed
2026-07-12 (see PLAN.md, Meteocat verification outcome):
- zonal: {dataPrediccio, dataPublicacio, franjes:[{idTipusFranja, nom,
  zones:[{idZona, nom, variablesValors:[{nom, valor?, periode}]}]}]}.
  franjes carry NO date — the window (24h or a 6h block) comes from the
  franja `nom`; `valor` is a STRING (categorical codes like cel/tempesta,
  or numbers like cota); variables without `valor` are simply absent that
  day (e.g. acumulacioNeu in summer).
- pics: [{data, cotes:[{cota, variables:[{nom, valor}]}]}] with cota in
  {"totes", "1500", "2000", "2500", "3000"} and numeric valor.

The slugs come from pics/metadades, whose lat/lon are the CANONICAL
coordinates for ALL sources (gotcha): config.py carries them since
2026-07-12, and every run alerts if the metadades coords ever drift.
"""
import json
import os
import re
from datetime import datetime, timedelta, timezone
from typing import List, Optional

import db
from alerting import send_alert
from archive import archive_payload
from config import ISO_UTC, RESORTS
from httpcache import cached_get

SOURCE = "meteocat"
BASE = "https://api.meteo.cat"

# Handoff anchor codes (codi -> station); slugs are resolved at runtime.
ANCHOR_PEAKS = {
    "77954ad7": "baqueira",    # Cap de Vaqueira
    "246d5775": "boi_taull",   # Pica de Cervi
    "4d04de5e": "la_molina",   # La Tosa d'Alp
}
# Zone id inside the all-zones response -> station. The endpoint uses its
# OWN 7-zone scheme (ids 1,3-8; names in the payload), NOT the allaus/BPA
# zones the handoff assumed — the old boi_taull id (3) was actually
# "Vessant nord Pirineu oriental". Observed 2026-07-12:
#   1 Vessant nord Pirineu occidental (Aran)          -> baqueira
#   5 Vessant sud Pirineu occidental (Ribagorçana)    -> boi_taull
#   6 Vessant sud Prepirineu oriental (Cadí-Moixeró?) -> la_molina
#     PROVISIONAL — no zones-metadades endpoint exists; cross-check against
#     the la-tosa-dalp pics forecast on the first winter payload.
ZONE_STATIONS = {1: "baqueira", 5: "boi_taull", 6: "la_molina"}

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


# --- value/window helpers ----------------------------------------------------

def _as_float(valor) -> Optional[float]:
    """Meteocat sends `valor` as str, int or float; text (comentari) -> None."""
    if isinstance(valor, bool) or valor is None:
        return None
    try:
        return float(valor)
    except (TypeError, ValueError):
        return None


# Fallback when a franja `nom` is unparseable: idTipusFranja -> (start, span).
_FRANJA_BY_ID = {1: (0, 6), 2: (6, 6), 3: (12, 6), 4: (18, 6), 5: (0, 24)}
_FRANJA_RE = re.compile(r"(\d{1,2}):(\d{2})")


def _franja_window(franja: dict) -> Optional[tuple]:
    """(start_hour, span_hours) of a franja.

    Real `nom` values are inconsistently formatted ("24h", "00:00h - 06:00h",
    "06:00 - 12:00h") so parse the clock times, falling back to the
    idTipusFranja mapping observed alongside them.
    """
    nom = str(franja.get("nom") or "")
    hours = [int(h) for h, _ in _FRANJA_RE.findall(nom)]
    if len(hours) == 2 and hours[1] > hours[0]:
        return hours[0], hours[1] - hours[0]
    if nom.strip() == "24h":
        return 0, 24
    return _FRANJA_BY_ID.get(franja.get("idTipusFranja"))


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
    """One row per (zone-of-interest, franja, variable-with-a-valor).

    valid_time is the franja window START on the target date, taken at face
    value from the payload's own "Z" suffix (dataPrediccio is "<date>Z");
    the window length lives in the variable name (e.g. zonal.cota.6h vs
    zonal.acumulacioNeu.24h) so the 24h summary never mixes with the blocks.
    Categorical codes (cel, tempesta, probabilitat…) are stored as their
    numeric code — the bucket semantics belong to normalize.py.
    """
    rows: List[db.Row] = []
    if not isinstance(body, dict):
        return rows
    for franja in body.get("franjes") or []:
        window = _franja_window(franja)
        if window is None:
            continue
        start, span = window
        valid = f"{target_date}T{start:02d}:00Z"
        for zone in franja.get("zones") or []:
            station = ZONE_STATIONS.get(zone.get("idZona"))
            if station is None:
                continue
            for var in zone.get("variablesValors") or []:
                value = _as_float(var.get("valor"))
                if var.get("nom") and value is not None:
                    rows.append((SOURCE, station, run_time_utc, valid,
                                 f"zonal.{var['nom']}.{span}h", value))
    return rows


def _parse_pic(body, run_time_utc: str, station: str,
               target_date: str) -> List[db.Row]:
    """One row per (timestep, cota, variable): pic.<nom>.<cota>.

    Real payloads: 8 three-hourly timesteps ("<date>THH:MMZ"), cota "totes"
    for column variables (isozero, iso-10) and fixed levels 1500/2000/2500/
    3000 for temperatura/humitat/velocitat vent/direccio vent. Spaces in
    noms become underscores so variable names stay shell/SQL-friendly.
    """
    rows: List[db.Row] = []
    if not isinstance(body, list):
        return rows
    for i, point in enumerate(body):
        valid = str(point.get("data") or f"{target_date}[t{i}]")
        for cota in point.get("cotes") or []:
            level = cota.get("cota") or cota.get("altitud") or "peak"
            for var in cota.get("variables") or []:
                value = _as_float(var.get("valor"))
                if var.get("nom") and value is not None:
                    nom = str(var["nom"]).replace(" ", "_")
                    rows.append((SOURCE, station, run_time_utc, valid,
                                 f"pic.{nom}.{level}", value))
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
    by_station = {r["station"]: r for r in RESORTS}
    for codi, info in slugs.items():
        station = ANCHOR_PEAKS[codi]
        cfg = by_station[station]
        # config.py holds the canonical pics-metadades coords; alert on drift
        # (rounded to 7 decimals there, so tolerate ~a few cm).
        if (abs(cfg["lat"] - info["lat"]) > 1e-6
                or abs(cfg["lon"] - info["lon"]) > 1e-6):
            send_alert(f"meteocat metadades coords for {station} drifted from "
                       f"config.py: {info['lat']},{info['lon']} "
                       f"vs {cfg['lat']},{cfg['lon']}")
        print(f"  {station}: {info['name']} lat={info['lat']} "
              f"lon={info['lon']} slug={info['slug']}")

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
