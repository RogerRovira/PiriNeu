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

# Cap on new (uncached) HTTP calls per process run.
MAX_NEW_CALLS = int(os.environ.get("MAX_NEW_CALLS", "50"))
# How long a cached HTTP response (success or failure) stays fresh.
CACHE_TTL_SECONDS = int(os.environ.get("CACHE_TTL_SECONDS", "3600"))

ISO_UTC = "%Y-%m-%dT%H:%M:%SZ"
