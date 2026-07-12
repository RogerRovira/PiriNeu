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

# Coordinates/elevations from the handoff openmeteo_ingest.py — still
# PLACEHOLDERS: swap in the canonical pics-metadades coords once Meteocat
# credentials arrive (see CLAUDE.md gotchas).
RESORTS = (
    {"station": "baqueira", "lat": 42.6975, "lon": 0.9422, "elevation_m": 1800},
    {"station": "boi_taull", "lat": 42.5219, "lon": 0.8386, "elevation_m": 2000},
    {"station": "la_molina", "lat": 42.3339, "lon": 1.9497, "elevation_m": 1700},
)

# Cap on new (uncached) HTTP calls per process run.
MAX_NEW_CALLS = int(os.environ.get("MAX_NEW_CALLS", "50"))
# How long a cached HTTP response (success or failure) stays fresh.
CACHE_TTL_SECONDS = int(os.environ.get("CACHE_TTL_SECONDS", "3600"))

ISO_UTC = "%Y-%m-%dT%H:%M:%SZ"
