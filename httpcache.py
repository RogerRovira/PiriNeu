"""Disk-backed HTTP GET cache with a per-run call cap (quota protection).

Failed statuses are cached too, so a broken endpoint is not hammered on
retries. New (uncached) network calls per process are capped at
MAX_NEW_CALLS; hitting the cap raises instead of silently exceeding quota.
"""
import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Tuple

import requests

from config import CACHE_DIR, CACHE_TTL_SECONDS, ISO_UTC, MAX_NEW_CALLS


class CallBudgetExceeded(RuntimeError):
    """Raised when a run tries to make more new HTTP calls than MAX_NEW_CALLS."""


_new_calls_made = 0


def cached_get(url: str,
               cache_dir: Optional[Path] = None,
               ttl_seconds: Optional[int] = None,
               timeout: int = 60,
               headers: Optional[dict] = None) -> Tuple[int, bytes, bool]:
    """GET a URL through the disk cache.

    Returns (status_code, body_bytes, from_cache). `headers` may carry
    auth (e.g. X-Api-Key) — headers are NEVER written to the cache entry.
    """
    global _new_calls_made
    cache_dir = Path(cache_dir or CACHE_DIR)
    ttl = CACHE_TTL_SECONDS if ttl_seconds is None else ttl_seconds

    key = hashlib.sha256(url.encode("utf-8")).hexdigest()
    entry_path = cache_dir / f"{key}.json"
    now = time.time()

    if entry_path.exists():
        entry = json.loads(entry_path.read_text(encoding="utf-8"))
        if now - entry["fetched_at_epoch"] < ttl:
            return entry["status"], entry["body"].encode("utf-8"), True

    if _new_calls_made >= MAX_NEW_CALLS:
        raise CallBudgetExceeded(
            f"call budget exhausted ({MAX_NEW_CALLS} new calls this run)")
    _new_calls_made += 1

    response = requests.get(url, timeout=timeout, headers=headers)
    entry = {
        "url": url,
        "status": response.status_code,
        "fetched_at_epoch": now,
        "fetched_at_utc": datetime.now(timezone.utc).strftime(ISO_UTC),
        "body": response.text,
    }
    cache_dir.mkdir(parents=True, exist_ok=True)
    entry_path.write_text(json.dumps(entry), encoding="utf-8")
    return response.status_code, response.text.encode("utf-8"), False
