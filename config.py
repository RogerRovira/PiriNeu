"""Project configuration: resorts, paths and environment-driven limits.

Storage is UTC-only; local time appears only in the presentation layer.
"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("PIRINEU_DATA_DIR", BASE_DIR / "data"))
RAW_DIR = DATA_DIR / "raw"          # raw-payload archive: the source of truth
CACHE_DIR = DATA_DIR / "cache"      # HTTP disk cache (quota protection)
LOG_DIR = DATA_DIR / "logs"
DB_PATH = DATA_DIR / "pirineu.sqlite"  # rebuildable view of the raw archive
# Date of the last healthcheck run — decide_legs.py schedules the watchdog
# once per day off this marker (the check itself leaves no DB trace).
HEALTHCHECK_MARKER = LOG_DIR / "healthcheck_last_run"

# CANONICAL coordinates for ALL sources: Meteocat pics-metadades anchor
# peaks (fetched 2026-07-12; see CLAUDE.md gotchas). Metadades carries NO
# elevation field, so elevation_m is the Open-Meteo elevation API (90 m DEM)
# value at these exact points — consistent with the `&elevation=` we send.
RESORTS = (
    # Cap de Vaquèira (slug cap-de-vaqueira)
    {"station": "baqueira", "lat": 42.6918885, "lon": 0.9742379, "elevation_m": 2458},
    # Pica de Cerví (slug pica-de-cervi)
    {"station": "boi_taull", "lat": 42.4529432, "lon": 0.8792261, "elevation_m": 2710},
    # La Tosa d'Alp (slug la-tosa-dalp)
    {"station": "la_molina", "lat": 42.3205751, "lon": 1.8926609, "elevation_m": 2526},
)

# Meteocat pronostic anchor points (pics + refugis): forecast points whose
# isozero/upper-wind tracks each resort's massif. The PRIMARY anchor per
# resort is stored under the resort's own station name (its metadades
# coords ARE the canonical RESORTS coords above; consensus reads
# pic.isozero.totes / pic.direccio_vent.3000 under the resort station).
# Secondary anchors (selection 2026-07-13) store under their own station
# names — extra isozero coverage for winter verification. The Predicció
# plan allows only 100 calls/month, so ingest fetches ONE anchor per day
# on a primary/secondary rotation (meteocat_ingest.anchors_for_date).
METEOCAT_ANCHORS = (
    # (codi, resort, station, primary)
    ("77954ad7", "baqueira", "baqueira", True),       # Cap de Vaquèira
    ("962535ca", "baqueira", "marimanya", False),     # Tuc de Marimanya
    ("b65b37e8", "baqueira", "airoto", False),        # Airoto
    ("8245e5c9", "baqueira", "gerdar", False),        # Refugi del Gerdar
    ("246d5775", "boi_taull", "boi_taull", True),     # Pica de Cerví
    ("6e5cedc5", "boi_taull", "filia", False),        # Pic de Filià
    ("a4d20c1f", "boi_taull", "corronco", False),     # Lo Corronco
    ("4d04de5e", "la_molina", "la_molina", True),     # La Tosa d'Alp
    ("5bb98db1", "la_molina", "puigllancada", False), # Puigllançada
    ("a9f7eb3a", "la_molina", "pere_carne", False),   # Xalet-Refugi Pere Carné
)

# XEMA observation stations — nowcast ground truth (XEMA plan: 750
# calls/month on the same key, ~25/day: comfortable for 6 stations).
# Chosen 2026-07-13: a HIGH + VALLEY pair per resort, so the two observed
# temperatures bracket the profile and the freezing level can be derived
# from the measured lapse rate instead of an assumed one. Boí and la Tosa
# d'Alp sit inside their resorts; Bonaigua is on Baqueira's pass.
# CAVEAT: Das - Aeròdrom sits in the Cerdanya cold pool — on inversion
# nights its reading is anomalously cold and the pair-derived lapse rate
# is invalid (nowcast must detect inversions and fall back to the high
# station alone). Berguedà-side alternate if DP proves unusable:
# Castellar de n'Hug - el Clot del Moro [MS], 42.25943, 1.97610, 940 m.
XEMA_STATIONS = (
    {"code": "Z1", "resort": "baqueira", "role": "high",
     "name": "Bonaigua", "lat": 42.64691, "lon": 0.98486,
     "elevation_m": 2262},
    {"code": "YN", "resort": "baqueira", "role": "valley",
     "name": "Vielha - Elipòrt", "lat": 42.69737, "lon": 0.80197,
     "elevation_m": 1029},
    {"code": "Z2", "resort": "boi_taull", "role": "high",
     "name": "Boí", "lat": 42.46603, "lon": 0.88403,
     "elevation_m": 2537},
    {"code": "CT", "resort": "boi_taull", "role": "valley",
     "name": "el Pont de Suert", "lat": 42.39809, "lon": 0.74364,
     "elevation_m": 824},
    {"code": "ZD", "resort": "la_molina", "role": "high",
     "name": "la Tosa d'Alp", "lat": 42.32213, "lon": 1.89716,
     "elevation_m": 2478},
    {"code": "DP", "resort": "la_molina", "role": "valley",
     "name": "Das - Aeròdrom", "lat": 42.38603, "lon": 1.86639,
     "elevation_m": 1096},
)

# Which Meteocat Pirineu forecast zone represents each resort. Zonal rows
# are stored per-zone (station `zona_<id>`, see meteocat_ingest.py), so this
# assignment is pure interpretation: revising it needs no re-ingest.
# The API offers no zone geometry (no zones metadades endpoint; docs/site
# unreachable from the dev environment), so this is assembled from the
# payload's own zone names + published descriptions of the zone scheme, and
# is verified against accumulated data by verify_meteocat_zones.py:
# - baqueira -> 1 "Vessant nord Pirineu occidental": Baqueira/Cap de
#   Vaquèira is in Naut Aran; the north-slope zone covers Val d'Aran and
#   the north rim of Pallars Sobirà/Alta Ribagorça. Note the resort's
#   Bonaigua sector sits on the divide itself. Confidence: high.
# - boi_taull -> 5 "Vessant sud Pirineu occidental": the zone explicitly
#   covers the Barravés and BOÍ valley heads (plus upper Vall Fosca and
#   northern Pallars valley heads). Confidence: high.
# - la_molina -> 6 "Vessant sud Prepirineu oriental": Tosa d'Alp belongs to
#   the Cadí-Moixeró-Tosa alignment (eastern Prepirineu) and this scheme has
#   no north-Prepirineu zone; but zones 4 "Pirineu oriental" and 8 "Vessant
#   sud Pirineu oriental" are plausible alternatives. Confidence: LOW —
#   confirm with verify_meteocat_zones.py once winter payloads accumulate.
METEOCAT_ZONE_FOR_STATION = {"baqueira": 1, "boi_taull": 5, "la_molina": 6}

# Cap on new (uncached) HTTP calls per process run.
MAX_NEW_CALLS = int(os.environ.get("MAX_NEW_CALLS", "50"))
# How long a cached HTTP response (success or failure) stays fresh.
CACHE_TTL_SECONDS = int(os.environ.get("CACHE_TTL_SECONDS", "3600"))

ISO_UTC = "%Y-%m-%dT%H:%M:%SZ"
