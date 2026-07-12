"""Raw-payload archive: the source of truth.

Every ingest run MUST persist its raw payloads here, compressed and dated,
BEFORE any parsing happens. SQLite is a rebuildable view of this archive
(`rebuild_db.py` proves it).
"""
import gzip
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Optional, Tuple

from config import ISO_UTC, RAW_DIR

_STAMP = "%Y%m%dT%H%M%SZ"


def archive_payload(source: str, name: str, payload: bytes,
                    fetched_at: Optional[datetime] = None,
                    raw_dir: Optional[Path] = None) -> Path:
    """Store raw bytes gzip-compressed under <raw_dir>/<source>/YYYY/MM/DD/.

    Never parses or inspects the payload. Returns the path written.
    """
    fetched_at = fetched_at or datetime.now(timezone.utc)
    day_dir = Path(raw_dir or RAW_DIR) / source / fetched_at.strftime("%Y/%m/%d")
    day_dir.mkdir(parents=True, exist_ok=True)
    path = day_dir / f"{fetched_at.strftime(_STAMP)}_{name}.gz"
    with gzip.open(path, "wb") as f:
        f.write(payload)
    return path


def iter_archived(source: str,
                  raw_dir: Optional[Path] = None) -> Iterator[Tuple[Path, bytes]]:
    """Yield (path, raw bytes) for every archived payload of a source, oldest first."""
    src_dir = Path(raw_dir or RAW_DIR) / source
    if not src_dir.exists():
        return
    for path in sorted(src_dir.rglob("*.gz")):
        with gzip.open(path, "rb") as f:
            yield path, f.read()


def run_time_from_path(path: Path) -> str:
    """Recover the fetch timestamp (ISO UTC) encoded in an archive filename."""
    stamp = path.name.split("_", 1)[0]
    return datetime.strptime(stamp, _STAMP).strftime(ISO_UTC)
