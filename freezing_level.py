"""Derive the freezing level (isozero) from pressure-level temperatures.

`freezing_level_height` on meteofrance_seamless returns null (see CLAUDE.md
gotchas), so the isozero is DERIVED: scan pressure levels from the ground up
(1000 -> 925 -> 850 -> 700 hPa) and linearly interpolate the altitude of the
0 °C crossing between the bracketing pair, using the model's own
geopotential heights rather than nominal level altitudes.

Ported unchanged from the handoff openmeteo_ingest.py — these edge-case
semantics are hard-won, do not "fix" them:
- Entire column above 0 °C  -> None (no freezing level in range; irrelevant
  for snow anyway).
- Entire column below 0 °C  -> the lowest level's geopotential height,
  flagged capped=True (freezing level at or below terrain).
- Inversions (multiple crossings) -> the LOWEST crossing, the conservative
  choice for snow-line purposes; n_crossings > 1 records the inversion.
"""
from dataclasses import dataclass
from typing import Optional, Sequence

PRESSURE_LEVELS = (1000, 925, 850, 700)  # hPa, ordered ground -> up


@dataclass
class FreezingLevel:
    height_m: Optional[float]   # meters above sea level
    capped: bool = False        # True when whole column was below 0 °C
    n_crossings: int = 0        # >1 signals an inversion was present


def derive_freezing_level(temps: Sequence[Optional[float]],
                          heights: Sequence[Optional[float]]) -> FreezingLevel:
    """temps/heights ordered ground->up along PRESSURE_LEVELS."""
    pairs = [(t, h) for t, h in zip(temps, heights)
             if t is not None and h is not None]
    if len(pairs) < 2:
        return FreezingLevel(None)

    if all(t <= 0 for t, _ in pairs):
        # freezing level at/below the lowest model level: cap at terrain
        return FreezingLevel(pairs[0][1], capped=True)
    if all(t > 0 for t, _ in pairs):
        return FreezingLevel(None)

    crossings = []
    for (t_lo, h_lo), (t_hi, h_hi) in zip(pairs, pairs[1:]):
        if (t_lo > 0) != (t_hi > 0) and t_lo != t_hi:
            frac = t_lo / (t_lo - t_hi)
            crossings.append(h_lo + frac * (h_hi - h_lo))
    if not crossings:
        return FreezingLevel(None)
    return FreezingLevel(min(crossings), n_crossings=len(crossings))
