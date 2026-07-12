#!/usr/bin/env python3
"""
Meteocat historical-forecast verification script.

Goal: determine empirically whether the Pirineu forecast endpoints serve
*past* target dates, and whether the returned payloads carry issue-date
metadata (dataPublicacio) proving they are archived forecasts rather than
recomputations. This decides if we can bootstrap a training archive or
must rely on collect-forward.

Usage:
    METEOCAT_API_KEY=xxxx python verify_meteocat_historics.py

Design notes:
- Quota-aware: every raw response is cached to disk (cache/), so re-runs
  never repeat a successful call. Total new calls per run are capped.
- Test matrix: for each probe date we call the zone endpoint (one call
  covers ALL zones, incl. zones 1/3/6 for Baqueira, Boi Taull, La Molina)
  and one representative peak per station (via slug, resolved from the
  handoff hex codes through the metadades endpoints).
- Output: report JSON + human-readable summary on stdout.
"""

import json
import os
import sys
import time
import urllib.request
import urllib.error
from datetime import date, timedelta
from pathlib import Path

BASE = "https://api.meteo.cat"
API_KEY = os.environ.get("METEOCAT_API_KEY", "")

CACHE_DIR = Path("cache")
REPORT_PATH = Path("verification_report.json")

MAX_NEW_CALLS = 25          # hard cap per run to protect quota
SLEEP_BETWEEN_CALLS = 1.5   # seconds, be polite

# Handoff anchor codes (codi -> station), one representative per station.
# Slugs are resolved at runtime from /pics/metadades and /refugis/metadades.
ANCHOR_CODES = {
    "77954ad7": "Baqueira Beret (Cap de Vaqueira)",
    "246d5775": "Boi Taull (Pica de Cervi)",
    "4d04de5e": "La Molina (La Tosa d'Alp)",
}

# Zone IDs of interest inside the all-zones response. Real names observed
# 2026-07-12 (the endpoint's own 7-zone scheme, NOT the allaus/BPA zones):
ZONE_IDS = {1: "Vessant nord Pirineu occidental",
            5: "Vessant sud Pirineu occidental",
            6: "Vessant sud Prepirineu oriental"}


def probe_dates(today: date) -> list[tuple[str, date]]:
    """Test matrix: labels + dates, ordered least->most ambitious."""
    return [
        ("today", today),
        ("D+2 (future horizon)", today + timedelta(days=2)),
        ("yesterday", today - timedelta(days=1)),
        ("-7 days", today - timedelta(days=7)),
        ("-30 days", today - timedelta(days=30)),
        ("last winter (-365d)", today - timedelta(days=365)),
        ("deep archive (2017-04-19)", date(2017, 4, 19)),  # docs' own example
    ]


class QuotaGuard:
    def __init__(self, limit: int):
        self.limit = limit
        self.used = 0

    def spend(self):
        if self.used >= self.limit:
            raise RuntimeError(
                f"Reached MAX_NEW_CALLS={self.limit}; rerun later to continue "
                "(cached results are kept)."
            )
        self.used += 1


def api_get(path: str, guard: QuotaGuard) -> dict:
    """GET with disk cache. Returns dict with status, body (parsed or raw)."""
    CACHE_DIR.mkdir(exist_ok=True)
    cache_file = CACHE_DIR / (path.strip("/").replace("/", "_") + ".json")
    if cache_file.exists():
        return json.loads(cache_file.read_text())

    guard.spend()
    req = urllib.request.Request(BASE + path, headers={"X-Api-Key": API_KEY})
    result: dict = {"path": path, "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            result["status"] = resp.status
            try:
                result["body"] = json.loads(raw)
            except json.JSONDecodeError:
                result["body"] = raw[:2000]
    except urllib.error.HTTPError as e:
        result["status"] = e.code
        try:
            result["body"] = json.loads(e.read().decode("utf-8", errors="replace"))
        except Exception:
            result["body"] = None
    except urllib.error.URLError as e:
        result["status"] = None
        result["error"] = str(e.reason)

    # Cache everything except transient network errors, so failed statuses
    # (404 etc.) are also remembered and never re-spent.
    if result.get("status") is not None:
        cache_file.write_text(json.dumps(result, ensure_ascii=False, indent=1))
    time.sleep(SLEEP_BETWEEN_CALLS)
    return result


def resolve_slugs(guard: QuotaGuard) -> dict:
    """Map handoff hex codes -> {slug, kind, name} via metadades endpoints."""
    mapping = {}
    for kind, path in (("pics", "/pronostic/v1/pirineu/pics/metadades"),
                       ("refugis", "/pronostic/v1/pirineu/refugis/metadades")):
        res = api_get(path, guard)
        if res.get("status") == 200 and isinstance(res["body"], list):
            for item in res["body"]:
                codi = item.get("codi")
                if codi in ANCHOR_CODES:
                    mapping[codi] = {"slug": item.get("slug"), "kind": kind,
                                     "name": item.get("descripcio")}
    return mapping


def analyze_zone_response(res: dict) -> dict:
    """Extract the facts that matter for the verdict."""
    out = {"status": res.get("status"), "has_data": False,
           "dataPrediccio": None, "dataPublicacio": None,
           "zones_of_interest_present": []}
    body = res.get("body")
    if res.get("status") == 200 and isinstance(body, dict):
        out["dataPrediccio"] = body.get("dataPrediccio")
        out["dataPublicacio"] = body.get("dataPublicacio")
        franjes = body.get("franjes") or []
        out["has_data"] = len(franjes) > 0
        seen = set()
        for fr in franjes:
            for z in fr.get("zones", []):
                zid = z.get("idZona")
                if zid in ZONE_IDS:
                    seen.add(zid)
        out["zones_of_interest_present"] = sorted(seen)
    return out


def analyze_point_response(res: dict) -> dict:
    out = {"status": res.get("status"), "has_data": False,
           "n_timesteps": 0, "has_isozero": False,
           "issue_metadata_fields": []}
    body = res.get("body")
    if res.get("status") == 200 and isinstance(body, list):
        out["n_timesteps"] = len(body)
        out["has_data"] = len(body) > 0
        for point in body:
            # look for any field that could reveal issue time
            for key in point:
                if "publicacio" in key.lower() or "emissio" in key.lower():
                    if key not in out["issue_metadata_fields"]:
                        out["issue_metadata_fields"].append(key)
            for cota in point.get("cotes", []):
                for var in cota.get("variables", []):
                    if var.get("nom") == "isozero":
                        out["has_isozero"] = True
    return out


def main() -> int:
    if not API_KEY:
        print("ERROR: set METEOCAT_API_KEY environment variable first.")
        return 1

    guard = QuotaGuard(MAX_NEW_CALLS)
    today = date.today()
    report = {"run_date": today.isoformat(), "zone_tests": [], "point_tests": [],
              "slug_mapping": {}, "calls_spent": 0}

    print("== Step 1: resolve slugs for anchor peaks ==")
    slugs = resolve_slugs(guard)
    report["slug_mapping"] = slugs
    for codi, info in slugs.items():
        print(f"  {codi} -> /{info['kind']}/{info['slug']} ({info['name']})")
    missing = set(ANCHOR_CODES) - set(slugs)
    if missing:
        print(f"  WARNING: codes not found in metadades: {missing}")

    print("\n== Step 2: zone endpoint across the date matrix ==")
    for label, d in probe_dates(today):
        path = f"/pronostic/v1/pirineu/{d.year}/{d.month:02d}/{d.day:02d}"
        try:
            res = api_get(path, guard)
        except RuntimeError as e:
            print(f"  STOP: {e}")
            break
        summary = analyze_zone_response(res)
        summary["label"], summary["date"] = label, d.isoformat()
        report["zone_tests"].append(summary)
        verdict = ("OK, archived forecast (issued "
                   f"{summary['dataPublicacio']})" if summary["has_data"]
                   else f"no data (HTTP {summary['status']})")
        print(f"  {label:26s} {d.isoformat()}  -> {verdict}")

    print("\n== Step 3: one peak per station, key dates only ==")
    # Fewer dates here to save quota: yesterday, -30d, last winter.
    point_dates = [("yesterday", today - timedelta(days=1)),
                   ("-30 days", today - timedelta(days=30)),
                   ("last winter (-365d)", today - timedelta(days=365))]
    for codi, info in slugs.items():
        for label, d in point_dates:
            path = (f"/pronostic/v1/pirineu/{info['kind']}/{info['slug']}"
                    f"/{d.year}/{d.month:02d}/{d.day:02d}")
            try:
                res = api_get(path, guard)
            except RuntimeError as e:
                print(f"  STOP: {e}")
                break
            summary = analyze_point_response(res)
            summary.update({"label": label, "date": d.isoformat(),
                            "codi": codi, "slug": info["slug"]})
            report["point_tests"].append(summary)
            verdict = (f"{summary['n_timesteps']} timesteps, "
                       f"isozero={'yes' if summary['has_isozero'] else 'NO'}"
                       if summary["has_data"]
                       else f"no data (HTTP {summary['status']})")
            print(f"  {ANCHOR_CODES[codi][:30]:32s} {label:22s} -> {verdict}")

    report["calls_spent"] = guard.used
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2))

    print(f"\nCalls spent this run: {guard.used}/{MAX_NEW_CALLS}")
    print(f"Full report: {REPORT_PATH.resolve()}")
    print("\n== Interpretation guide ==")
    print("A) Past dates return 200 + data + dataPublicacio ~2 days before")
    print("   the target -> genuine archive: historical training data OK.")
    print("B) Past dates return 200 but dataPublicacio is recent -> data is")
    print("   recomputed, NOT valid for verification. Collect-forward only.")
    print("C) Past dates 404 -> no archive. Collect-forward only, and use")
    print("   XEMA daily endpoints (which ARE historical) as ground truth.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
