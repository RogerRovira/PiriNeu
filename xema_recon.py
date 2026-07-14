"""XEMA API reconnaissance — groundwork for the nowcast correction leg.

Empirically answers, for the six chosen observation stations
(config.XEMA_STATIONS, a high+valley pair per resort):
- which XEMA endpoints exist (station-day readings vs per-variable) and
  their real payload shapes — the ingest parser follows reality, not docs
- which variables each station measures (temperature, precipitation,
  snow depth "gruix de neu", wind, humidity) and their codes/units
- reading cadence and publication latency (newest timestamp vs now) —
  this bounds how fresh the nowcast correction can be

Auth: METEOCAT_API_KEY (the same key as Predicció; the XEMA plan allows
750 calls/month, ~25/day). A full first run spends ~15 calls; responses
go through httpcache, so re-runs within the TTL are free.

Report lands in data/xema_recon_report.json — record the outcome in
PLAN.md (nowcast item) before building xema_ingest.py.
"""
import json
import os
import re
from datetime import datetime, timezone
from typing import List, Optional

from config import DATA_DIR, ISO_UTC, XEMA_STATIONS
from httpcache import cached_get

BASE = "https://api.meteo.cat"
REPORT_PATH = DATA_DIR / "xema_recon_report.json"

DAY_TTL = 6 * 3600        # today's readings: refetchable within the day
META_TTL = 7 * 24 * 3600  # catalogs/metadata: change rarely

# Variable families the nowcast cares about, matched against catalog noms.
INTEREST = ("temperatura", "precipita", "neu", "vent", "humitat", "pressió")

_TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}")


def _headers() -> dict:
    key = os.environ.get("METEOCAT_API_KEY")
    if not key:
        raise RuntimeError("METEOCAT_API_KEY not set")
    return {"X-Api-Key": key}


def probe(path: str, ttl: int) -> dict:
    """GET one endpoint; JSON body under 'json', errors kept for the report."""
    out = {"path": path}
    try:
        status, body, from_cache = cached_get(BASE + path, ttl_seconds=ttl,
                                              headers=_headers())
    except Exception as exc:  # budget/network — record and move on
        out["error"] = str(exc)
        return out
    out["status"] = status
    out["from_cache"] = from_cache
    if status == 200:
        try:
            out["json"] = json.loads(body)
        except ValueError:
            out["note"] = "200 but non-JSON body"
            out["body_head"] = body[:200].decode("utf-8", "replace")
    else:
        out["body_head"] = body[:300].decode("utf-8", "replace")
    return out


def timestamps(obj) -> List[str]:
    """Every ISO-looking value under a 'data' key, anywhere in the payload."""
    found: List[str] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == "data" and isinstance(v, str) and _TS_RE.match(v):
                found.append(v)
            else:
                found.extend(timestamps(v))
    elif isinstance(obj, list):
        for item in obj:
            found.extend(timestamps(item))
    return found


def variable_codes(obj) -> List:
    """codi values of every dict that carries 'lectures' or 'valor' lists —
    i.e. the variables actually present in a readings payload."""
    found: List = []
    if isinstance(obj, dict):
        if "codi" in obj and ("lectures" in obj or "valors" in obj):
            found.append(obj["codi"])
        for v in obj.values():
            found.extend(variable_codes(v))
    elif isinstance(obj, list):
        for item in obj:
            found.extend(variable_codes(item))
    return found


def summarize_readings(payload, now: datetime) -> dict:
    """Cadence + latency + variables present, from whatever shape came back."""
    stamps = sorted(set(timestamps(payload)))
    out = {"reading_count": len(stamps),
           "variables_present": sorted(set(variable_codes(payload)),
                                       key=str)}
    if stamps:
        out["oldest"] = stamps[0]
        out["newest"] = stamps[-1]
        newest = datetime.fromisoformat(
            stamps[-1].replace("Z", "+00:00"))
        if newest.tzinfo is None:
            newest = newest.replace(tzinfo=timezone.utc)
        out["latency_minutes"] = round(
            (now - newest).total_seconds() / 60)
        if len(stamps) >= 3:
            first = datetime.fromisoformat(stamps[0].replace("Z", "+00:00"))
            span = (newest - first.replace(tzinfo=newest.tzinfo))
            out["cadence_minutes"] = round(
                span.total_seconds() / 60 / (len(stamps) - 1))
    return out


def interesting_variables(catalog) -> List[dict]:
    """Catalog entries whose nom matches the nowcast-relevant families."""
    picks = []
    for item in catalog if isinstance(catalog, list) else []:
        nom = str(item.get("nom", "")).lower()
        if any(word in nom for word in INTEREST):
            picks.append({k: item.get(k)
                          for k in ("codi", "nom", "unitat", "acronim")})
    return picks


def main() -> None:
    now = datetime.now(timezone.utc)
    report = {"run_at": now.strftime(ISO_UTC), "endpoints": {},
              "stations": {}}

    # 1) Variable catalog: names/units for the codes the readings will use.
    cat = probe("/xema/v1/variables/mesurades/metadades", META_TTL)
    report["endpoints"]["variable_catalog"] = {
        "path": cat["path"], "status": cat.get("status"),
        "error": cat.get("error")}
    if cat.get("json") is not None:
        report["variable_catalog_interesting"] = \
            interesting_variables(cat["json"])
        print(f"variable catalog: {len(cat['json'])} variables, "
              f"{len(report['variable_catalog_interesting'])} of interest")

    # 2) Station metadata: confirm codes/coords/status of the chosen six.
    est = probe("/xema/v1/estacions/metadades", META_TTL)
    report["endpoints"]["station_metadata"] = {
        "path": est["path"], "status": est.get("status"),
        "error": est.get("error")}
    by_code = {}
    if isinstance(est.get("json"), list):
        by_code = {item.get("codi"): item for item in est["json"]}

    y, m, d = now.year, now.month, now.day
    for st in XEMA_STATIONS:
        code = st["code"]
        entry = {"resort": st["resort"], "role": st["role"]}
        meta = by_code.get(code)
        entry["in_metadata"] = meta is not None
        if meta:
            coord = meta.get("coordenades") or {}
            entry["metadata"] = {
                "nom": meta.get("nom"), "altitud": meta.get("altitud"),
                "lat": coord.get("latitud"), "lon": coord.get("longitud"),
                "estats": meta.get("estats")}

        # Which variables does this station measure?
        varmeta = probe(f"/xema/v1/estacions/{code}/variables/mesurades"
                        f"/metadades", META_TTL)
        entry["variable_metadata_status"] = varmeta.get("status")
        if isinstance(varmeta.get("json"), list):
            entry["variables_measured"] = interesting_variables(
                varmeta["json"])

        # Today's readings, whole station in one call (preferred for the
        # ingest budget: 6 stations x 1 call/cycle).
        day = probe(f"/xema/v1/estacions/mesurades/{code}/{y}/{m:02d}/{d:02d}",
                    DAY_TTL)
        entry["station_day_status"] = day.get("status")
        if day.get("json") is not None:
            entry["station_day"] = summarize_readings(day["json"], now)
        report["stations"][code] = entry
        print(f"{code} ({st['resort']}/{st['role']}): metadata="
              f"{entry['in_metadata']} station-day HTTP "
              f"{day.get('status', day.get('error'))} "
              f"{entry.get('station_day', '')}")

    # 3) If the station-day endpoint doesn't exist, learn the per-variable
    # shape from one probe (32 = air temperature) so the fallback design
    # (1 call per variable per day, station-filtered) can be costed.
    statuses = {e.get("station_day_status")
                for e in report["stations"].values()}
    if 200 not in statuses:
        alt = probe(f"/xema/v1/variables/mesurades/32/{y}/{m:02d}/{d:02d}"
                    f"?codiEstacio=Z1", DAY_TTL)
        report["endpoints"]["per_variable_fallback"] = {
            "path": alt["path"], "status": alt.get("status")}
        if alt.get("json") is not None:
            report["per_variable_sample"] = summarize_readings(
                alt["json"], now)

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2, ensure_ascii=False))
    print(f"report: {REPORT_PATH}")
    print("record the outcome in PLAN.md (XEMA nowcast item): endpoint "
          "shapes, variables, cadence, latency")


if __name__ == "__main__":
    main()
